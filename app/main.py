from fastapi import FastAPI, Body, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from app.errors import BusinessError, object_payload
from app.pipeline import run, sample_text
from app import store, revisions
from app.exporter import evidence_csv
from pathlib import Path
import importlib
app=FastAPI(title='质谱空白扣除与检出限复算')
app.mount("/static",StaticFiles(directory=Path(__file__).parent/"static"),name="static")
templates=Jinja2Templates(directory=Path(__file__).parent/"templates")
MODULES=['仪器接收', '内标归一', '标曲拟合', '空白扣除', '浓度复算', '质控判定', '结果复核']
for n,slug in enumerate(['intake', 'internal', 'curve', 'blank', 'concentration', 'quality', 'review'],1):
    app.include_router(importlib.import_module(f"app.modules.m{n}_{slug}.handler").router)
@app.exception_handler(BusinessError)
async def domain_error(request,exc):
    return JSONResponse({"error":exc.code,"message":str(exc)},status_code=exc.status)
@app.get("/health")
def health(): return {"status":"ok"}
def fresh_save(text):
    payloads=revisions.active_payloads()
    result=run(text,blank_revisions=payloads)
    return store.save(text,result,revisions.signature_for(result,payloads))
@app.get("/",response_class=HTMLResponse)
def home(request:Request): return page(request,1)
@app.get("/module/{module}",response_class=HTMLResponse)
def page(request:Request,module:int):
    if module not in range(1,8): raise BusinessError("MODULE","模块不存在",404)
    ident=request.query_params.get("run_id")
    item=store.get(ident) if ident else fresh_save(sample_text())
    return templates.TemplateResponse(request=request,name="workbench.html",context={"title":'质谱空白扣除与检出限复算',"modules":MODULES,"active":module,"run":item,"report":item["result"]["reports"][module-1]})
@app.post("/api/run")
def calculate(payload:object=Body(default=None)):
    payload=object_payload(payload)
    text=payload.get("text",sample_text())
    if not isinstance(text,str): raise BusinessError("TEXT","输入须为文本")
    return fresh_save(text)
@app.get("/api/runs")
def list_runs(): return store.history()
@app.get("/api/runs/{ident}")
def run_detail(ident:str): return store.get(ident)
@app.post("/api/review")
def review(payload:object=Body(...)):
    payload=object_payload(payload)
    if not isinstance(payload.get("id"),str) or not isinstance(payload.get("decision"),str): raise BusinessError("REVIEW","复核编号与决定须为文本")
    if type(payload.get("revision")) is not int: raise BusinessError("REVISION","版本须为整数")
    return store.review(str(payload.get("id","")),payload["revision"],payload.get("decision"))
@app.post("/api/blank-revision")
def blank_revision(payload:object=Body(...)):
    payload=object_payload(payload)
    if not isinstance(payload.get("batch"),str) or not payload.get("batch","").strip(): raise BusinessError("SCOPE","批次须为文本")
    if not isinstance(payload.get("analyte"),str) or not payload.get("analyte","").strip(): raise BusinessError("SCOPE","检测项须为文本")
    if type(payload.get("revision")) is not int: raise BusinessError("REVISION","修订序号须为整数")
    if not isinstance(payload.get("text"),str): raise BusinessError("TEXT","输入须为文本")
    return revisions.register(payload["batch"].strip(),payload["analyte"].strip(),payload["revision"],payload["text"])
@app.get("/api/blank-revisions")
def blank_revisions(): return revisions.list_all()
@app.get("/api/export/{ident}")
def export(ident:str):
    return Response(evidence_csv(store.get(ident)),media_type="text/csv",headers={"Content-Disposition":"attachment; filename=evidence.csv"})
@app.get("/api/sample")
def sample(): return {"text":sample_text()}
