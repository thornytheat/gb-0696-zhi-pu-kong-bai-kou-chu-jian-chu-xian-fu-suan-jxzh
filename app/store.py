import sqlite3, json, hashlib
from datetime import datetime, timezone
from app.config import DATA_DIR, RULE_VERSION
from app.errors import BusinessError

def connect():
    DATA_DIR.mkdir(parents=True,exist_ok=True)
    db=sqlite3.connect(DATA_DIR/"runs.sqlite", timeout=15)
    db.row_factory=sqlite3.Row
    db.execute("CREATE TABLE IF NOT EXISTS runs (id TEXT PRIMARY KEY, digest TEXT NOT NULL, result TEXT NOT NULL, revision INTEGER NOT NULL DEFAULT 0, decision TEXT NOT NULL DEFAULT '待复核', created TEXT NOT NULL)")
    runs_cols={r[1] for r in db.execute("PRAGMA table_info(runs)")}
    if "text" not in runs_cols: db.execute("ALTER TABLE runs ADD COLUMN text TEXT")
    if "signature" not in runs_cols: db.execute("ALTER TABLE runs ADD COLUMN signature TEXT NOT NULL DEFAULT '{}'")
    db.execute("CREATE TABLE IF NOT EXISTS blank_revisions (id INTEGER PRIMARY KEY AUTOINCREMENT, batch TEXT NOT NULL, analyte TEXT NOT NULL, revision_no INTEGER NOT NULL, digest TEXT NOT NULL, payload TEXT NOT NULL, status TEXT NOT NULL, created TEXT NOT NULL, UNIQUE(batch,analyte,revision_no,digest))")
    db.execute("CREATE TABLE IF NOT EXISTS run_revisions (id INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT NOT NULL, signature TEXT NOT NULL, result TEXT, status TEXT NOT NULL, reason TEXT, created TEXT NOT NULL, UNIQUE(run_id,signature))")
    return db

def now():
    return datetime.now(timezone.utc).isoformat()

def save(text, result, signature=None):
    digest=hashlib.sha256((RULE_VERSION+"\n"+text).encode()).hexdigest()
    ident=digest[:16]
    with connect() as db:
        db.execute("INSERT OR IGNORE INTO runs(id,digest,text,result,signature,created) VALUES(?,?,?,?,?,?)",(ident,digest,text,json.dumps(dict(result,rule_version=RULE_VERSION),ensure_ascii=False),json.dumps(signature or {},sort_keys=True),now()))
    return get(ident)

def get(ident):
    with connect() as db:
        row=db.execute("SELECT * FROM runs WHERE id=?",(ident,)).fetchone()
        if row is None: raise BusinessError("NOT_FOUND","批次不存在",404)
        recalculations=[dict(r) for r in db.execute("SELECT signature,status,reason,created FROM run_revisions WHERE run_id=? ORDER BY id",(ident,))]
        latest=db.execute("SELECT signature,result FROM run_revisions WHERE run_id=? AND status='applied' ORDER BY id DESC LIMIT 1",(ident,)).fetchone()
        revisions=[dict(r) for r in db.execute("SELECT batch,analyte,revision_no,digest,status,created FROM blank_revisions ORDER BY batch,analyte,revision_no,id")]
    item=dict(row)
    original=json.loads(item["result"])
    item["original"]={"blocked":original.get("blocked"),"conclusion":"阻断" if original.get("blocked") else "可复核","balance":original.get("balance"),"final":original.get("final",[]),"quarantine":original.get("quarantine",[]),"signature":json.loads(item.get("signature") or "{}")}
    if latest:
        item["result"]=json.loads(latest["result"]);item["signature"]=json.loads(latest["signature"])
    else:
        item["result"]=original;item["signature"]=json.loads(item.get("signature") or "{}")
    for r in recalculations: r["signature"]=json.loads(r["signature"])
    item["recalculations"]=recalculations
    scopes={(r["batch"],r["analyte"]) for r in item["result"].get("normalized",[])}
    item["blank_revisions"]=[r for r in revisions if (r["batch"],r["analyte"]) in scopes]
    item["rule_version"]=item["result"].get("rule_version","2026.11.18.1")
    return item

def history():
    with connect() as db:
        return [dict(r) for r in db.execute("SELECT id,revision,decision,created FROM runs ORDER BY created DESC LIMIT 40")]

def review(ident,revision,decision):
    if not isinstance(decision,str) or decision not in {"通过","退回"}: raise BusinessError("DECISION","复核决定无效")
    current=get(ident)
    if decision=="通过" and current["result"].get("blocked"):
        raise BusinessError("BLOCKED","存在阻断项，请先修正数据",409)
    with connect() as db:
        changed=db.execute("UPDATE runs SET revision=revision+1,decision=? WHERE id=? AND revision=?",(decision,ident,revision)).rowcount
        if not changed: raise BusinessError("STALE","版本已更新，请刷新",409)
    return get(ident)
