# Codex 接手：tt_drama_performance

迁移日期：2026-10-09。这里保存接手入口；原项目文件与 Claude 记录仍然保留。

## 先读什么

- `CLAUDE.md`
- `PLAYBOOK.md`
- `.agents/claude-migration/RECENT_CLAUDE.md`：最近最多 3 个会话的文本摘录。
- `.agents/claude-migration/SESSION_INDEX.json`：所有找到的原会话路径。

## 仍需 Claude 的业务调用

以下代码发现了 Claude CLI / Anthropic 调用。Codex 已能维护它们；接手开发不会自动更换运行模型。要停用 Claude，先适配输入、图片、输出解析和验证。

- `generate_report.py`

## 当前接力记录

- 2026-11-10 最新排查（优先于下面 10-09 记录）：用户反馈 Windows 登录失败并要求分析页面更新。SSH 使用现有 browser_profile 实测能进入数据页，故当前“登录失效”是旧 `logged_in()` 只等待 `Export Data` 的误判；新按钮为 `Export`。11:00 计划任务退出码 2，下一轮 15:00。
- 页面改版证据：顶部文字改为 `Only data from March 1, 2026 onward is shown, updated through 2026-11-08`，旧 data_date 正则返回 None；默认近 7 天，EXTRACT_JS 仅返回 metrics.innerfeedVv，切近 30 天可提取 10-10 至 11-08 共 30 个日值，旧报告需要的 vv/vvFinish/playDuration/likeCnt/commentCnt/favouriteCnt/shareCnt 未在该提取结果中返回。原 META_JS 与分页脚本仍可获取 ID/上线时间，已实测第一页和第二页；collections 为空，不应据此清空旧关联。
- 新 Excel 是 17 列中文表头：剧集、封面、发布时间、集数、总时长、制作类型、原语言是否中文、题材、累计有效播放量、新增有效播放量、人均播放时长（秒）、累计收藏、新增收藏、累计评论、新增评论、累计点赞、新增点赞。没有 ID，旧 read_snapshot 实测抛“表头不认识”。不能仅改按钮就视为修复。
- 原“导出与日期范围无关”的前提已失效：近 7 天导出 34 行；近 30 天 37 行，多出 CEO Loves My Voice / My Boss's Son Wants Me / Tender Betrayal，新增列随区间改变。My Boss Is a Superstar 页面累计有效播放为 2,804，导出为 2,674；导出累计点赞 868 小于近 7 天新增点赞 883。此为实测差异，原因及新旧累计口径尚未确定，不能强行放宽验收或补零缺失指标。
- 本次仅诊断，未改业务代码、未入库测试导出、未生成或分发报告、未发送通知；测试文件保存在 Windows output/diagnostics，页面截图已复制到本地 output/diagnostics/login-20261110.png。Windows 最新入库为 11-01，报告/S3/Git 近期另有代理连接失败，7892 监听存在，不等于外网连接正常。
- 待办：整体适配按钮与日期识别、日期筛选和稳定 ID 映射、仅有有效播放的趋势与历史字段兼容；先确认新导出累计口径再恢复验收入库。若继续适配，涉及数据口径冲突，建议 high 推理；本轮未读取或改变模型设置。
- 本次本地 git pull --rebase --autostash 成功（7d3b44a），autostash 正常恢复，无未解决冲突；保留用户现有 daily_history.json / snapshot_audit.json 修改，Windows 未同步数据亦保留。

### 2026-10-09 历史排查

- 当前状态：2026-10-09 已通过 SSH 检查 Windows `E:\workspace\skills\tt_drama_performance` 的最新日志、快照、验收台账和计划任务；本次为诊断，未修改业务代码或远端状态。
- 最近任务与结论：15:00 登录失效（TTDramaDaily 退出码 2）；15:17 已恢复访问，但平台标注 10-07 的导出仅 24 部剧，上份 30 部，触发 `export_short` 并隔离。缺少 Seduced by the Dark Lord I Swore To Kill、Falling for the Superstar、Revenge of the Abandoned Heriess、They Bullied the Wrong Heiress、The Count of Monte Cristo、Undercover In the Dungeon。Chrome 首次下载 TargetClosedError 后自动清理 shared_proto_db，重试已成功，不是本轮最终失败原因。
- 下一步：核实缺少的 6 部剧是平台正式移除还是临时漏导出，确认后再决定是否调整验收。10-06 之前数轮也未通过对账（共同剧目增量 129,313，候选趋势区间 163,017 / 292,330），不能仅凭页面标注强行入库。
- 验证：最新已入库截止日 10-04（30 部剧，14 天合并档，台账 smear，偏差 +5.90%）；report.html 更新于 10-08 13:32。TTDramaDaily Ready，下一次 10-09 19:00，漏跑数 0；ShortDramaDataConsole Running。本地修改仅交接记录；写入前尝试 git pull --rebase --autostash，但 GitHub TLS 连接失败，未完成同步，未提交推送。

## 继续方式

首次在本目录运行 `codex`，输入“读接手记录，接着上次工作继续”。后续在同目录运行 `codex resume --last`；选择历史用 `codex resume`。这会恢复 Codex 会话，Claude 历史通过以上交接资料读取。
