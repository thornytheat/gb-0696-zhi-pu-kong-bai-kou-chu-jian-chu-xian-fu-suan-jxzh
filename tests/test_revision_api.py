from fastapi.testclient import TestClient
from app.main import app
from app import store
import pytest

client=TestClient(app,raise_server_exceptions=False)
HEADER="sample_id,kind,analyte,area,internal_area,level,dilution,unit,batch"
REV_BR9="\n".join([HEADER,"RB1,blank,Pb,110,100,0,1,ug/L,BR9","RB2,blank,Pb,106,100,0,2,ug/L,BR9"])
REV_BR9_ALT=REV_BR9.replace("110","112")

@pytest.fixture(autouse=True)
def fresh_db():
    db=store.DATA_DIR/"runs.sqlite"
    if db.exists(): db.unlink()
    yield

def test_blank_revision_type_checks():
    assert client.post("/api/blank-revision",json={"batch":"BR9","analyte":"Pb","revision":"1","text":REV_BR9}).status_code==422
    assert client.post("/api/blank-revision",json={"batch":"BR9","analyte":"Pb","revision":True,"text":REV_BR9}).status_code==422
    assert client.post("/api/blank-revision",json={"batch":"","analyte":"Pb","revision":1,"text":REV_BR9}).status_code==422
    assert client.post("/api/blank-revision",json={"batch":"BR9","analyte":"Pb","revision":1,"text":[]}).status_code==422
    assert client.post("/api/blank-revision",json=[]).status_code==422

def test_blank_revision_flow():
    applied=client.post("/api/blank-revision",json={"batch":"BR9","analyte":"Pb","revision":1,"text":REV_BR9})
    assert applied.status_code==200 and applied.json()["status"]=="applied"
    again=client.post("/api/blank-revision",json={"batch":"BR9","analyte":"Pb","revision":1,"text":REV_BR9})
    assert again.status_code==200 and again.json()["status"]=="unchanged"
    conflict=client.post("/api/blank-revision",json={"batch":"BR9","analyte":"Pb","revision":1,"text":REV_BR9_ALT})
    assert conflict.status_code==409 and conflict.json()["error"]=="REVISION_CONFLICT"
    listed=client.get("/api/blank-revisions").json()
    assert {r["status"] for r in listed if r["batch"]=="BR9"}=={"active","quarantined"}

def test_blank_revision_stale_rejected():
    client.post("/api/blank-revision",json={"batch":"BR9","analyte":"Pb","revision":2,"text":REV_BR9})
    stale=client.post("/api/blank-revision",json={"batch":"BR9","analyte":"Pb","revision":1,"text":REV_BR9_ALT})
    assert stale.status_code==409 and stale.json()["error"]=="REVISION_STALE"

def test_run_detail_and_export_carry_revision_evidence():
    text="\n".join([HEADER,
    "C0,standard,Pb,100,100,0,1,ug/L,BR8",
    "C1,standard,Pb,500,100,2,1,ug/L,BR8",
    "C2,standard,Pb,900,100,4,1,ug/L,BR8",
    "BK1,blank,Pb,120,100,0,1,ug/L,BR8",
    "S1,sample,Pb,320,100,0,1,ug/L,BR8"])
    run_id=client.post("/api/run",json={"text":text}).json()["id"]
    rev="\n".join([HEADER,"RB1,blank,Pb,110,100,0,1,ug/L,BR8"])
    out=client.post("/api/blank-revision",json={"batch":"BR8","analyte":"Pb","revision":1,"text":rev})
    assert any(o["run_id"]==run_id for o in out.json()["runs"])
    detail=client.get(f"/api/runs/{run_id}").json()
    assert detail["signature"]=={"BR8/Pb":1} and detail["original"]["conclusion"]=="可复核"
    exported=client.get(f"/api/export/{run_id}")
    assert exported.status_code==200 and "blank_revision" in exported.text and "original_result" in exported.text
