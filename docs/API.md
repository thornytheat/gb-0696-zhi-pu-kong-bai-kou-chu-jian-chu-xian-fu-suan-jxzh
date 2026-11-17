# 接口

`POST /api/run`：{"text":"CSV内容"}。同规则版本与输入摘要只产生一条批次。登记过空白修订的范围按现行修订计算。

`GET/POST /api/1` 至 `/api/7`：独立样例或自定义文件计算。各模块返回 report、quarantine、balance。

`POST /api/review`：id、整数revision、decision取通过或退回。旧版本409；阻断项不能通过。复核后批次冻结，不再随空白修订重算。

`POST /api/blank-revision`：batch、analyte、整数revision、text（空白复测CSV，仅空白行且同范围）。新序号启用并重算待复核批次；同序号同值返回unchanged不新增；同序号异值409并隔离；旧序号409。

`GET /api/blank-revisions`：修订登记簿，含现行、已替代、已隔离。

`GET /api/runs/{id}`：批次现行结果、原批结论、重算记录与范围内修订。

`GET /api/export/{id}`：唯一证据CSV，含空白配对、限定符、原批结论与修订登记。`GET /health`：存活检查。

错误：结构/数值422，版本冲突409，不存在404，文件过大413。逐行异常进入quarantine。
