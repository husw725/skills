# Windows 每日自动更新配置（不依赖任何 AI agent）

## 快速安装（推荐）

前置：装好 Python 3.9+（安装时勾选 "Add to PATH"）和 git（配好 GitHub 推送凭证）。

```powershell
git clone https://github.com/husw725/skills.git
cd skills\tt_drama_performance
.\install.bat
```

`install.bat` 一次完成：建 venv 装依赖 → 弹浏览器窗口让你登录一次 →
跑一遍完整更新验证 → 注册每天 15:00 的计划任务。全程按提示走即可。

登录态保存在 `browser_profile\`（.gitignore 已排除），长期复用；
日志在 `daily_update.log`；手动触发测试：`schtasks /run /tn TTDramaDaily`。

## 手动配置（install.bat 出问题时的备选）

```powershell
python -m venv .venv
.venv\Scripts\pip install playwright openpyxl
.venv\Scripts\playwright install chromium
.venv\Scripts\python daily_update.py --login   # 弹窗人工登录一次
.venv\Scripts\python daily_update.py --push    # 验证完整流程
schtasks /create /f /tn "TTDramaDaily" /tr "\"<仓库完整路径>\tt_drama_performance\run_daily.bat\"" /sc daily /st 15:00
```

## 故障排查

| 现象 | 处理 |
|---|---|
| 退出码 2 / 日志提示登录失效 | 重跑 `python daily_update.py --login` |
| 退出码 3 / 导出失败 | 页面按钮可能改版，打开页面人工确认 Export Data 按钮还在 |
| 趋势数据提取警告 | 页面前端结构变了，xlsx 快照仍正常，找维护者更新 EXTRACT_JS |
| git push 失败 | 本机跑一次 `git push` 按提示配置凭证 |

任务默认带浏览器窗口运行（更稳，闪一下就关）。确认稳定后可把 bat 里命令加 `--headless`。
