# 每日数据更新流程（每天 15:00 自动执行）

目标：从 TikTok Drama Center 抓取当天数据，更新 `report.html`。
工作目录：本文件（PLAYBOOK.md）所在目录，下文所有相对路径均以它为基准。

前置条件：Chrome 已打开且已登录 tiktokdramacenter.com（claude-in-chrome 扩展可用）。
任一步骤失败重试 2 次仍失败，则跳过该数据源继续后续步骤，并在结束时报告。

## 步骤

1. **导出剧目快照 xlsx**
   - 用浏览器工具打开 `https://www.tiktokdramacenter.com/analytics/content-performance`，等待加载完成。
   - 截图确认页面正常，找到 "Drama Details" 卡片右上角的 **Export Data** 按钮并点击（无需改日期范围——导出内容是全量累计快照，与日期范围无关，已验证）。
   - 文件会下载到 `~/Downloads/content_performance_YYYY-MM-DD*.xlsx`（YYYY-MM-DD 为当天日期，重复下载会带 `(n)` 后缀）。
   - 把**最新**的那个文件复制为 `data/content_performance_<当天日期>.xlsx`（覆盖同名文件即可）。

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
   - 报告结果：更新到哪天的数据、剧目数、有无异常（如某剧目消失、数值大幅回落——
     累计值不应下降，若下降说明平台改口径或抓取有误，要在总结中标注）。
   - 不要提交 git、不要发送任何消息，只更新本地文件。
