# TT 短剧日报管道

TikTok 短剧数据日报（建于 2026-07-28），每日更新流程见 PLAYBOOK.md。

## 工作约定
- 本仓库每 4 小时有 Windows 定时任务自动推送数据提交。**动手改任何东西之前先 `git pull --rebase --autostash`**，改完立即 commit+push，压缩撞车窗口。report.html 冲突时：取 theirs 完成 rebase → 重新跑 generate_report.py → amend。

## 关键事实（代码里看不出来的坑）

- 页面 Export Data 导出的 xlsx 是**各剧全量累计快照，与页面日期范围无关**（已用单日范围对比验证，两次导出字节一致）。所以剧目级日增量 = 相邻两天快照做差。
- 机构级每日趋势数据在页面 React fiber 状态里（`scripts/extract_daily.js` 提取），API 有 X-Bogus/X-Gnarly 反爬签名，不要直接调接口。
- javascript_tool 单次输出约 1000 字符，大 JSON 要 `window.__dump.slice(i, i+1000)` 分块读取后本地拼接校验。
- `generate_report.py` 会把 `data/daily_stats_*.json` 合并进 `data/daily_history.json`（按日期去重）。
- 会话内 cron（15:03）是 session-only、7天过期；已改为 Windows 计划任务 TTDramaDaily（03:00 起每 4 小时一轮，共 6 轮：03/07/11/15/19/23，run_daily.bat 开头 git pull 自动同步代码）。
- 任务是 **Interactive 登录态**运行（config.json `headless:false`，要弹真 Chrome 窗口），所以**不能**改成 "Run whether user is logged on or not"（S4U 无桌面，headed Chrome 会挂）。代价是没登录时触发点直接跳过——已加 **At-logon 触发器（延迟 3 分钟）** 补跑，并关掉了电池限制（DisallowStartIfOnBatteries/StopIfGoingOnBatteries）。2026-08-13 凌晨重启后漏掉 03:00/07:00 两轮就是这个原因。
- 平台数据滞后 2~3 天、夜里刷新、偶尔跳更；页面顶部 "data updated to YYYY-MM-DD"（中文界面"数据更新至"）是数据真实截止日，快照按它命名，不按导出日期。
- **平台刷新不是原子的**：刚翻新数据日时导出可能只含部分剧（实测 22→14），daily_update 有守卫（比上一份少≥2部即丢弃重试）。
- 数据组织：导出 xlsx 每行是一个 contract（合同）；contract 下挂多个 collection（版本/语言）。剧目明细表 React 状态里 contractInfo.publishTimeSec = 上线时间（UTC 显示），已抓到 data/drama_meta.json，每日 collect_meta() 翻页刷新（Semi Design 分页 .semi-page-item）。
- 上线日期换算用 UTC（datetime.utcfromtimestamp），本地时区会和平台页面差一天。
