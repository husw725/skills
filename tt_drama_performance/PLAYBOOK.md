# 每日数据更新流程（每天 15:00 自动执行）

目标：从 TikTok Drama Center 抓取当天数据，更新 `report.html`。
工作目录：本文件（PLAYBOOK.md）所在目录，下文所有相对路径均以它为基准。

前置条件：Chrome 已打开且已登录 tiktokdramacenter.com（claude-in-chrome 扩展可用）。
任一步骤失败重试 2 次仍失败，则跳过该数据源继续后续步骤，并在结束时报告。

## 步骤

0. **确认登录态（必做）**
   - 用浏览器工具打开 `https://www.tiktokdramacenter.com/analytics/content-performance`，等待加载完成。
   - 截图确认页面上有 "Drama Performance" 标题和 Export Data 按钮。
     若被重定向到登录页：**立即中止整个流程并通知用户**（登录态失效，需人工重新登录），
     不要尝试自动登录，也不要在没有新数据的情况下继续后面的步骤。
   - 定时任务的浏览器必须使用**持久化 profile**（与人工登录时同一个 user-data-dir），
     否则每次都是无登录态的全新环境，这一步永远过不了。

1. **导出剧目快照 xlsx**
   - 找到 "Drama Details" 卡片右上角的 **Export Data** 按钮并点击（无需改日期范围——导出内容是全量累计快照，与日期范围无关，已验证）。
   - 文件名为 `content_performance_YYYY-MM-DD*.xlsx`（YYYY-MM-DD 为当天日期，重复下载会带 `(n)` 后缀），
     落在浏览器的下载目录：本机浏览器为 `~/Downloads`；
     若在 WSL 里通过 CDP 驱动 Windows Chrome，则为 `/mnt/c/Users/<Windows用户名>/Downloads`；
     自动化浏览器（如 Playwright）则为其配置的下载目录。
   - **验证下载确实发生**：下载目录里必须存在文件名含当天日期、且修改时间在本次运行之内的新文件。
     找不到 → 重试点击一次；仍然没有 → **中止并报告"导出失败"**。
     严禁在没拿到新文件的情况下直接跑 generate_report.py 然后当作成功——那只会重新生成一份旧数据报告。
   - 把**修改时间最新**的那个文件复制为 `data/content_performance_<当天日期>.xlsx`（覆盖同名文件即可）。

   > 首次在新机器上跑：需要先在所用浏览器里人工登录一次 tiktokdramacenter.com，
   > 之后登录态保存在浏览器 profile 里即可长期复用。

2. **抓取每日趋势数据（React 状态）**
   - 在同一页面用 javascript_tool 执行 `scripts/extract_daily.js` 的完整内容。
     它会把最近 28 天的机构级每日指标存到 `window.__dump` 并返回长度。
   - 由于工具单次输出约 1000 字符，用 `window.__dump.slice(i, i+1000)` 分块读取全部内容，
     在本地拼接成完整 JSON（拼接后必须 `json.loads` 校验，并核对 daily 数组的首尾日期）。
   - 存为 `data/daily_stats_<当天日期>.json`（格式 `{"daily": [...]}`）。
     generate_report.py 会自动把它合并进 `data/daily_history.json`（按日期去重，新数据覆盖旧数据）。

3. **重新生成报告**
   ```
   cd <本目录> && python3 generate_report.py
   ```
   依赖：python3 + openpyxl（缺失时 `pip3 install openpyxl`）。
   - 确认输出行 `report.html written; N days, M dramas, K snapshot(s)`，
     N 应比昨天多 1（或持平），K 应等于 data/ 下 xlsx 文件数。

4. **收尾**
   - 报告结果必须明确回答：**今天是否拿到了新快照（xlsx 日期 = 今天）和新趋势数据**；
     再报更新到哪天的数据、剧目数、有无异常（如某剧目消失、数值大幅回落——
     累计值不应下降，若下降说明平台改口径或抓取有误，要在总结中标注）。
   - 不要提交 git、不要发送任何消息，只更新本地文件。
