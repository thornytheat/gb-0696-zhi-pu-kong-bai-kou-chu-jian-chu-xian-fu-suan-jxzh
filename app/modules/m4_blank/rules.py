from app.report import report,quarantine
from decimal import Decimal

def corrected(response,curve,blank):
    return (response-curve["intercept"])/curve["slope"]-blank

def median(values):
    ordered=sorted(values);n=len(ordered)
    return ordered[n//2] if n%2 else (ordered[n//2-1]+ordered[n//2])/2

def spread(values):
    n=len(values)
    if n<2:return Decimal(0)
    center=sum(values)/n
    return (sum((v-center)**2 for v in values)/(n-1)).sqrt()

def instrument(value,curve):
    return (value-curve["intercept"])/curve["slope"]

def input_groups(ctx):
    groups={}
    for r in ctx["normalized"]:
        if r["kind"]!="blank":continue
        curve=ctx["curves"].get((r["batch"],r["analyte"]))
        if not curve:continue
        key=(r["batch"],r["analyte"],r["dilution_value"])
        groups.setdefault(key,{"values":[],"source":"input","revision":None})
        groups[key]["values"].append(instrument(r["response"],curve))
    return groups

def overlay_revisions(groups,ctx):
    for scope,payload in (ctx.get("blank_revisions") or {}).items():
        scope=tuple(scope)
        for key in [k for k in groups if k[:2]==scope]:del groups[key]
        curve=ctx["curves"].get(scope)
        if not curve:continue
        for b in payload["blanks"]:
            key=(scope[0],scope[1],Decimal(str(b["dilution"])))
            groups.setdefault(key,{"values":[],"source":"revision","revision":payload["revision"]})
            groups[key]["values"].append(instrument(Decimal(str(b["response"])),curve))
    return groups

def summarize(groups):
    blankset={}
    for key,g in groups.items():
        blankset[key]={"median":median(g["values"]),"sd":spread(g["values"]),"n":len(g["values"]),"source":g["source"],"revision":g["revision"]}
    return blankset

def apply(ctx):
    blankset=summarize(overlay_revisions(input_groups(ctx),ctx))
    ctx["blank_groups"]=[dict(zip(("batch","analyte","dilution"),key),**v) for key,v in sorted(blankset.items(),key=lambda kv:str(kv[0]))]
    out=[]
    for r in ctx["normalized"]:
        if r["kind"] not in {"sample","control"}:continue
        key=(r["batch"],r["analyte"]);curve=ctx["curves"].get(key)
        if not curve:quarantine(ctx,r,"CURVE_MISSING");continue
        group=blankset.get((key[0],key[1],r["dilution_value"]))
        if group is None:
            quarantine(ctx,r,"BLANK_GROUP_MISSING" if any(k[:2]==key for k in blankset) else "BLANK_MISSING");continue
        x=dict(r);x["net"]=corrected(r["response"],curve,group["median"])
        x["blank_value"]=group["median"];x["blank_sd"]=group["sd"];x["blank_n"]=group["n"]
        x["blank_dilution"]=r["dilution_value"];x["blank_source"]=group["source"];x["blank_revision"]=group["revision"]
        out.append(x)
    ctx["corrected"]=out
    return report(out,样品=len(out),空白组=len(blankset))
