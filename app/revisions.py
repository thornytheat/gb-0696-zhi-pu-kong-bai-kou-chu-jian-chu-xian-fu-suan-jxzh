import json, hashlib
from app import store
from app.config import RULE_VERSION
from app.errors import BusinessError
from app.reader import read_rows
from app.modules.m1_intake.rules import FIELDS
from app.modules.m2_internal.rules import response
from app.numbers import number
from app.pipeline import run

SWITCH_FAIL_REASONS={"BLANK_MISSING","BLANK_GROUP_MISSING"}

def parse_blank_revision(text,batch,analyte):
    rows,bad,_=read_rows(text,FIELDS)
    if bad: raise BusinessError("REVISION_ROWS","修订文件含异常行")
    blanks=[];seen=set()
    for r in rows:
        if r["batch"]!=batch or r["analyte"]!=analyte: raise BusinessError("SCOPE","修订行超出批次或检测项范围")
        if r["kind"]!="blank": raise BusinessError("KIND","修订仅接受空白行")
        if r["sample_id"] in seen: raise BusinessError("REVISION_DUP","修订内编号重复")
        seen.add(r["sample_id"])
        dilution=number(r["dilution"])
        if dilution<=0: raise BusinessError("DILUTION","稀释倍数须大于零")
        blanks.append({"sample_id":r["sample_id"],"response":str(response(r["area"],r["internal_area"])),"dilution":str(dilution)})
    if not blanks: raise BusinessError("BLANK_REQUIRED","修订须含空白行")
    return blanks

def digest_payload(payload):
    return hashlib.sha256(json.dumps(payload,sort_keys=True,ensure_ascii=False).encode()).hexdigest()

def register(batch,analyte,revision_no,text):
    if revision_no<1: raise BusinessError("REVISION","修订序号须为正整数")
    payload={"blanks":parse_blank_revision(text,batch,analyte)}
    digest=digest_payload(payload)
    with store.connect() as db:
        same_no=db.execute("SELECT * FROM blank_revisions WHERE batch=? AND analyte=? AND revision_no=?",(batch,analyte,revision_no)).fetchall()
        for row in same_no:
            if row["digest"]==digest:
                if row["status"]=="active": return {"status":"unchanged","revision":{"batch":batch,"analyte":analyte,"revision_no":revision_no,"digest":digest},"runs":[]}
                if row["status"]=="superseded": raise BusinessError("REVISION_STALE","旧修订不倒退",409)
                raise BusinessError("REVISION_CONFLICT","同序号异值已隔离",409)
        if same_no:
            db.execute("INSERT INTO blank_revisions(batch,analyte,revision_no,digest,payload,status,created) VALUES(?,?,?,?,?,'quarantined',?)",(batch,analyte,revision_no,digest,json.dumps(payload,ensure_ascii=False),store.now()))
            db.commit()
            raise BusinessError("REVISION_CONFLICT","同序号异值已隔离",409)
        active=db.execute("SELECT * FROM blank_revisions WHERE batch=? AND analyte=? AND status='active'",(batch,analyte)).fetchone()
        if active and revision_no<=active["revision_no"]:
            raise BusinessError("REVISION_STALE","旧修订不倒退",409)
        if active: db.execute("UPDATE blank_revisions SET status='superseded' WHERE id=?",(active["id"],))
        db.execute("INSERT INTO blank_revisions(batch,analyte,revision_no,digest,payload,status,created) VALUES(?,?,?,?,?,'active',?)",(batch,analyte,revision_no,digest,json.dumps(payload,ensure_ascii=False),store.now()))
        outcomes=recalculate_pending(db)
    return {"status":"applied","revision":{"batch":batch,"analyte":analyte,"revision_no":revision_no,"digest":digest},"runs":outcomes}

def active_payloads(db=None):
    own=db is None
    db=db or store.connect()
    try:
        rows=db.execute("SELECT batch,analyte,revision_no,payload FROM blank_revisions WHERE status='active'").fetchall()
    finally:
        if own: db.close()
    return {(r["batch"],r["analyte"]):dict(json.loads(r["payload"]),revision=r["revision_no"]) for r in rows}

def signature_for(result,payloads):
    scopes={(r["batch"],r["analyte"]) for r in result.get("normalized",[])}
    return {f"{b}/{a}":payloads[(b,a)]["revision"] for (b,a) in sorted(scopes) if (b,a) in payloads}

def current_signature(db,run_row):
    latest=db.execute("SELECT signature FROM run_revisions WHERE run_id=? AND status='applied' ORDER BY id DESC LIMIT 1",(run_row["id"],)).fetchone()
    return json.loads((latest["signature"] if latest else run_row["signature"]) or "{}")

def switch_failure(result,revised_scopes):
    missed={q["reason"] for q in result["quarantine"] if q["reason"] in SWITCH_FAIL_REASONS and (q["raw"].get("batch"),q["raw"].get("analyte")) in revised_scopes}
    return "BLANK_UNCOVERED:"+",".join(sorted(missed)) if missed else None

def recalculate_pending(db):
    outcomes=[]
    active={(r["batch"],r["analyte"]):r for r in db.execute("SELECT * FROM blank_revisions WHERE status='active'").fetchall()}
    if not active: return outcomes
    for row in db.execute("SELECT * FROM runs WHERE decision='待复核'").fetchall():
        if not row["text"]: continue
        scopes={(r["batch"],r["analyte"]) for r in json.loads(row["result"]).get("normalized",[])}
        relevant={s:rev for s,rev in active.items() if s in scopes}
        if not relevant: continue
        signature={f"{s[0]}/{s[1]}":rev["revision_no"] for s,rev in sorted(relevant.items())}
        if signature==current_signature(db,row): continue
        sig_text=json.dumps(signature,sort_keys=True)
        payloads={s:dict(json.loads(rev["payload"]),revision=rev["revision_no"]) for s,rev in relevant.items()}
        try:
            result=run(row["text"],blank_revisions=payloads)
            failure=switch_failure(result,set(relevant))
            if failure:
                db.execute("INSERT OR IGNORE INTO run_revisions(run_id,signature,status,reason,created) VALUES(?,?,?,?,?)",(row["id"],sig_text,"failed",failure,store.now()))
                outcomes.append({"run_id":row["id"],"status":"failed","reason":failure,"signature":signature})
            else:
                db.execute("INSERT OR IGNORE INTO run_revisions(run_id,signature,result,status,created) VALUES(?,?,?,?,?)",(row["id"],sig_text,json.dumps(dict(result,rule_version=RULE_VERSION),ensure_ascii=False),"applied",store.now()))
                outcomes.append({"run_id":row["id"],"status":"applied","signature":signature})
        except BusinessError as e:
            db.execute("INSERT OR IGNORE INTO run_revisions(run_id,signature,status,reason,created) VALUES(?,?,?,?,?)",(row["id"],sig_text,"failed",e.code,store.now()))
            outcomes.append({"run_id":row["id"],"status":"failed","reason":e.code,"signature":signature})
    return outcomes

def list_all():
    with store.connect() as db:
        return [dict(r) for r in db.execute("SELECT batch,analyte,revision_no,digest,status,created FROM blank_revisions ORDER BY batch,analyte,revision_no,id")]
