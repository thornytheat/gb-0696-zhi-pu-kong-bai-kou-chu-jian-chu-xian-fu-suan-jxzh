# 空白修订：按修订序号重算、同稀释组配对、旧修订不倒退、同序号异值隔离、切换失败保留原结果、重办不新增
from decimal import Decimal
import pytest
from app.pipeline import run, sample_text
from app.modules.m4_blank.rules import median, spread
from app.modules.m5_concentration.rules import detection_limit
from app import store, revisions
from app.errors import BusinessError
from app.exporter import evidence_csv

HEADER="sample_id,kind,analyte,area,internal_area,level,dilution,unit,batch"
BASE="\n".join([HEADER,
"C0,standard,Pb,100,100,0,1,ug/L,BR1",
"C1,standard,Pb,500,100,2,1,ug/L,BR1",
"C2,standard,Pb,900,100,4,1,ug/L,BR1",
"BK1,blank,Pb,120,100,0,1,ug/L,BR1",
"BK2,blank,Pb,140,100,0,1,ug/L,BR1",
"S1,sample,Pb,320,100,0,1,ug/L,BR1",
"S2,sample,Pb,640,100,0,2,ug/L,BR1"])
REV1="\n".join([HEADER,
"RB1,blank,Pb,110,100,0,1,ug/L,BR1",
"RB2,blank,Pb,106,100,0,2,ug/L,BR1",
"RB3,blank,Pb,108,100,0,2,ug/L,BR1"])
REV1_ALT=REV1.replace("RB1,blank,Pb,110","RB1,blank,Pb,112")
REV2="\n".join([HEADER,
"RC1,blank,Pb,112,100,0,1,ug/L,BR1",
"RC2,blank,Pb,108,100,0,2,ug/L,BR1"])

@pytest.fixture(autouse=True)
def fresh_db():
    db=store.DATA_DIR/"runs.sqlite"
    if db.exists(): db.unlink()
    yield

def counts():
    with store.connect() as db:
        blanks=db.execute("SELECT COUNT(*) c FROM blank_revisions").fetchone()["c"]
        recalc=db.execute("SELECT COUNT(*) c FROM run_revisions").fetchone()["c"]
    return blanks,recalc

def test_median_even():
    assert median([Decimal("0.1"),Decimal("0.3")])==Decimal("0.2")

def test_spread_decimal():
    assert spread([Decimal("0.1"),Decimal("0.2"),Decimal("0.3")])==Decimal("0.1")

def test_spread_single_is_zero():
    assert spread([Decimal("0.1")])==0

def test_detection_limit_floor():
    assert detection_limit(Decimal(0),Decimal(2))==Decimal("0.10")

def test_detection_limit_spread_times_dilution():
    assert detection_limit(Decimal("0.05"),Decimal(2))==Decimal("0.30")

def test_pairing_uses_same_dilution_group():
    result=run(sample_text())
    row=next(r for r in result["corrected"] if r["sample_id"]=="S002")
    assert row["blank_dilution"]=="2" and row["blank_source"]=="input" and row["blank_n"]==3
    assert Decimal(row["blank_value"])==Decimal("0.05") and Decimal(row["net"])==Decimal("1.05")

def test_group_missing_quarantined():
    result=run(BASE)
    missed=[q for q in result["quarantine"] if q["reason"]=="BLANK_GROUP_MISSING"]
    assert [q["id"] for q in missed]==["S2"]

def test_lod_uses_group_spread_and_dilution():
    result=run(sample_text())
    lod={r["sample_id"]:Decimal(r["lod"]) for r in result["concentrations"]}
    assert lod["S003"]==Decimal("0.15") and lod["S002"]==Decimal("0.150")

def test_pipeline_accepts_revision_overlay():
    payload={"revision":1,"blanks":[{"sample_id":"RB1","response":"1.1","dilution":"1"},{"sample_id":"RB2","response":"1.06","dilution":"2"},{"sample_id":"RB3","response":"1.08","dilution":"2"}]}
    result=run(BASE,blank_revisions={("BR1","Pb"):payload})
    final={r["sample_id"]:r for r in result["final"]}
    assert Decimal(final["S2"]["concentration"])==Decimal("5.33") and final["S2"]["blank_revision"]==1
    assert final["S1"]["blank_source"]=="revision" and Decimal(final["S1"]["concentration"])==Decimal("1.05")

def test_revision_recalculates_pending_run():
    saved=store.save(BASE,run(BASE))
    out=revisions.register("BR1","Pb",1,REV1)
    assert out["status"]=="applied"
    assert any(o["run_id"]==saved["id"] and o["status"]=="applied" for o in out["runs"])
    item=store.get(saved["id"])
    final={r["sample_id"]:r for r in item["result"]["final"]}
    assert Decimal(final["S2"]["concentration"])==Decimal("5.33") and final["S2"]["blank_source"]=="revision"
    assert item["signature"]=={"BR1/Pb":1} and item["recalculations"][0]["status"]=="applied"
    assert item["original"]["conclusion"]=="可复核"
    assert {r["sample_id"] for r in item["original"]["final"]}=={"S1"}

def test_reviewed_run_keeps_snapshot():
    saved=store.save(BASE,run(BASE))
    store.review(saved["id"],saved["revision"],"通过")
    revisions.register("BR1","Pb",1,REV1)
    item=store.get(saved["id"])
    assert item["decision"]=="通过" and item["recalculations"]==[]
    assert {r["sample_id"] for r in item["result"]["final"]}=={"S1"}
    row=item["result"]["final"][0]
    assert row["blank_source"]=="input" and row["lod"] and "qualifier" in row

def test_same_revision_same_content_no_new_results():
    store.save(BASE,run(BASE))
    revisions.register("BR1","Pb",1,REV1)
    again=revisions.register("BR1","Pb",1,REV1)
    assert again["status"]=="unchanged" and again["runs"]==[]
    assert counts()==(1,1)

def test_same_revision_different_value_quarantined():
    saved=store.save(BASE,run(BASE))
    revisions.register("BR1","Pb",1,REV1)
    with pytest.raises(BusinessError) as caught:
        revisions.register("BR1","Pb",1,REV1_ALT)
    assert caught.value.code=="REVISION_CONFLICT" and caught.value.status==409
    states={r["status"] for r in revisions.list_all() if r["batch"]=="BR1"}
    assert states=={"active","quarantined"}
    item=store.get(saved["id"])
    assert Decimal(next(r for r in item["result"]["final"] if r["sample_id"]=="S2")["concentration"])==Decimal("5.33")
    assert counts()==(2,1)

def test_older_revision_not_rolled_back():
    revisions.register("BR1","Pb",2,REV2)
    with pytest.raises(BusinessError,match="旧修订不倒退"):
        revisions.register("BR1","Pb",1,REV1)
    active=[r for r in revisions.list_all() if r["status"]=="active"]
    assert len(active)==1 and active[0]["revision_no"]==2

def test_switch_failure_keeps_original():
    text=BASE+"\nS3,sample,Pb,1280,100,0,3,ug/L,BR1"
    saved=store.save(text,run(text))
    out=revisions.register("BR1","Pb",1,REV1)
    assert any(o["run_id"]==saved["id"] and o["status"]=="failed" for o in out["runs"])
    item=store.get(saved["id"])
    assert {r["sample_id"] for r in item["result"]["final"]}=={"S1"}
    assert item["recalculations"][0]["status"]=="failed"
    assert "BLANK_UNCOVERED" in item["recalculations"][0]["reason"]
    assert item["signature"]=={}

def test_recalculation_idempotent():
    store.save(BASE,run(BASE))
    revisions.register("BR1","Pb",1,REV1)
    with store.connect() as db:
        revisions.recalculate_pending(db)
    assert counts()==(1,1)

def test_export_shows_pairing_qualifier_and_original():
    saved=store.save(BASE,run(BASE))
    revisions.register("BR1","Pb",1,REV1)
    text=evidence_csv(store.get(saved["id"]))
    for marker in ["original_result","blank_revision","recalculation","blank_dilution","blank_source","qualifier","original_conclusion"]:
        assert marker in text

def test_run_detail_lists_blank_revisions():
    saved=store.save(BASE,run(BASE))
    revisions.register("BR1","Pb",1,REV1)
    item=store.get(saved["id"])
    assert item["blank_revisions"][0]["revision_no"]==1
    assert item["original"]["conclusion"]=="可复核"

def test_revision_scope_and_kind_validated():
    with pytest.raises(BusinessError) as caught:
        revisions.register("BR1","Pb",1,BASE)
    assert caught.value.code=="KIND"
    with pytest.raises(BusinessError) as caught:
        revisions.register("BR2","Pb",1,REV1)
    assert caught.value.code=="SCOPE"
    with pytest.raises(BusinessError):
        revisions.register("BR1","Pb",0,REV1)
