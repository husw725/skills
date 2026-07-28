# Windows 每日自动更新配置（不依赖任何 AI agent）

一次性配置约 5 分钟，之后每天 15:00 自动：导出数据 → 更新 report.html → 推送 git。

## 1. 安装依赖（PowerShell，装过 Python 3.9+ 即可）

```powershell
git clone https://github.com/husw725/skills.git
cd skills\tt_drama_performance
pip install playwright openpyxl
playwright install chromium
```

## 2. 首次登录（只需一次）

```powershell
python daily_update.py --login
```

会弹出一个浏览器窗口，人工登录 tiktokdramacenter.com。
登录态保存在 `browser_profile\` 目录（已被 .gitignore 排除，不会提交），之后长期复用。

## 3. 手动跑一次验证

```powershell
python daily_update.py --push
```

看到 `完成。` 且 GitHub 上出现 `data: daily update <日期>` 提交即成功。
（`--push` 需要本机 git 已配置好 GitHub 凭证；只想本地更新就去掉 `--push`。）

## 4. 建定时任务（管理员 PowerShell）

```powershell
schtasks /create /tn "TTDramaDaily" /tr "\"<仓库完整路径>\tt_drama_performance\run_daily.bat\"" /sc daily /st 15:00
```

日志在 `daily_update.log`。手动触发测试：`schtasks /run /tn TTDramaDaily`。

## 故障排查

| 现象 | 处理 |
|---|---|
| 退出码 2 / 日志提示登录失效 | 重跑 `python daily_update.py --login` |
| 退出码 3 / 导出失败 | 页面按钮可能改版，打开页面人工确认 Export Data 按钮还在 |
| 趋势数据提取警告 | 页面前端结构变了，xlsx 快照仍正常，找维护者更新 EXTRACT_JS |
| git push 失败 | 本机跑一次 `git push` 按提示配置凭证 |

任务默认带浏览器窗口运行（更稳，闪一下就关）。确认稳定后可把 bat 里命令加 `--headless`。
