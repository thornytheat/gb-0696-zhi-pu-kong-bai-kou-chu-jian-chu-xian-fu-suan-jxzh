from app.numbers import fmt
from app.report import report
from decimal import Decimal

LOD_SPREAD_FACTOR=Decimal(3)
LOD_FLOOR=Decimal("0.05")

def concentration(net,dilution):
    if dilution<=0:raise ValueError("稀释倍数须为正")
    return net*dilution

def detection_limit(spread,dilution):
    if dilution<=0:raise ValueError("稀释倍数须为正")
    base=spread*LOD_SPREAD_FACTOR
    if base<LOD_FLOOR:base=LOD_FLOOR
    return base*dilution

def apply(ctx):
    out=[]
    for r in ctx["corrected"]:
        x=dict(r);x["concentration"]=concentration(r["net"],r["dilution_value"]);x["lod"]=detection_limit(r["blank_sd"],r["dilution_value"]);x["unit"]="ug/L";out.append(x)
    ctx["concentrations"]=out
    return report(out,复算=len(out),单位="ug/L")
