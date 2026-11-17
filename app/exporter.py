import csv,io,json

def evidence_csv(run):
    out=io.StringIO();writer=csv.writer(out)
    writer.writerow(["run_id","sha256","rule_version","kind","line","reason","evidence"])
    manifest={"balance":run["result"]["balance"],"decision":run["decision"],"revision":run["revision"],"signature":run["signature"],"original_conclusion":run["original"]["conclusion"],"original_blocked":run["original"]["blocked"]}
    writer.writerow([run["id"],run["digest"],run["rule_version"],"manifest","","",json.dumps(manifest,ensure_ascii=False)])
    for row in run["result"].get("final",[]):
        writer.writerow([run["id"],run["digest"],run["rule_version"],"result",row.get("line",""),row.get("status",""),json.dumps(row,ensure_ascii=False)])
    if run.get("recalculations"):
        for row in run["original"].get("final",[]):
            writer.writerow([run["id"],run["digest"],run["rule_version"],"original_result",row.get("line",""),row.get("status",""),json.dumps(row,ensure_ascii=False)])
        for row in run["original"].get("quarantine",[]):
            writer.writerow([run["id"],run["digest"],run["rule_version"],"original_quarantine",row.get("line",""),row["reason"],json.dumps(row,ensure_ascii=False)])
    for row in run["result"].get("quarantine",[]):
        writer.writerow([run["id"],run["digest"],run["rule_version"],"quarantine",row.get("line",""),row["reason"],json.dumps(row,ensure_ascii=False)])
    for rec in run.get("recalculations",[]):
        writer.writerow([run["id"],run["digest"],run["rule_version"],"recalculation","",rec["status"],json.dumps(rec,ensure_ascii=False)])
    for rev in run.get("blank_revisions",[]):
        writer.writerow([run["id"],run["digest"],run["rule_version"],"blank_revision","",rev["status"],json.dumps(rev,ensure_ascii=False)])
    return "﻿"+out.getvalue()
