# Windows 每日自动更新配置（不依赖任何 AI agent）

## 2026-11 新版运行

原计划任务和持久化登录 profile 继续使用。新版识别 `Export` 按钮，不会再因按钮改名误报登录失效。

- 首次更新默认从2026-03-01逐日扫描全部历史，并查询近7天、前7天、近30天；每个区间自动翻完分页并精确对账。
- 新数据单独保存在 `data/v2/`，旧快照和历史指标保留。以后默认刷新最近3天，并重采机构趋势修订过的日期。
- `config.json` 可设置 `v2_history_start`（默认2026-03-01）；设为空时只回填 `v2_backfill_days`（默认30，1~180）。`v2_refresh_days` 默认3，历史失败日期的重试间隔 `v2_history_retry_hours` 默认24小时。服务端不能返回和采集未验收的日期分别标记；前30日不可用时不显示月环比。
- `python daily_update.py --local-only --headless`：采集并更新本地报告，跳过Git/S3分发及钉钉通知，适用于维护验证。
- `python daily_update.py --audit`：有新版存档时只读复查新版数据，不打开浏览器，不发送通知。
- `python generate_report.py`：使用已验收的新版存档重新生成报告。

下文安装示例及故障表保留原流程背景，最新任务频率以现有 TTDramaDaily 为准。

## 快速安装（推荐）

前置：装好 Python 3.9+（安装时勾选 "Add to PATH"）和 git（配好 GitHub 推送凭证）。

```powershell
git clone https://github.com/husw725/skills.git
cd skills\tt_drama_performance
.\install.bat
```

`install.bat` 一次完成：建 venv 装依赖 → 生成 config.json → 弹浏览器窗口让你登录一次 →
跑一遍完整更新验证 → 注册每天 15:00 的计划任务。全程按提示走即可。

## 配置文件 config.json（install.bat 会从 config.example.json 自动生成）

```json
{
  "dingtalk_webhook": "https://oapi.dingtalk.com/robot/send?access_token=你的token",
  "git_push": true,
  "headless": false
}
```

- `dingtalk_webhook`：登录失效/导出失败时发钉钉提醒；留空则不发。
  **仓库是公开的，config.json 已被 .gitignore 排除，别把 webhook 写进任何会提交的文件。**
- `git_push`：更新完是否自动 git 提交推送。
- `headless`：true 则不弹浏览器窗口（登录态已保存时可用）。

登录态保存在 `browser_profile\`（.gitignore 已排除），长期复用；
日志在 `daily_update.log`；手动触发测试：`schtasks /run /tn TTDramaDaily`。

## 手动配置（install.bat 出问题时的备选）

```powershell
python -m venv .venv
.venv\Scripts\pip install playwright openpyxl
.venv\Scripts\playwright install chromium
.venv\Scripts\python daily_update.py --login   # 弹窗人工登录一次
.venv\Scripts\python daily_update.py --push    # 验证完整流程
schtasks /create /f /tn "TTDramaDaily" /tr "\"<仓库完整路径>\tt_drama_performance\run_daily.bat\"" /sc daily /st 03:00 /ri 240 /du 20:01
# 补一个登录触发器（重启后没登录时会跳过定时点）+ 去掉电池限制
$t=Get-ScheduledTask -TaskName 'TTDramaDaily'; $l=New-ScheduledTaskTrigger -AtLogOn -User ($env:COMPUTERNAME+'\'+$env:USERNAME); $l.Delay='PT3M'
Set-ScheduledTask -TaskName 'TTDramaDaily' -Trigger (@($t.Triggers)+$l) -Settings (New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Hours 72))
```

## 故障排查

| 现象 | 处理 |
|---|---|
| 退出码 2 / 日志提示登录失效 | 重跑 `python daily_update.py --login` |
| 退出码 3 / 导出失败 | 页面按钮可能改版，打开页面人工确认 Export Data 按钮还在 |
| 趋势数据提取警告 | 页面前端结构变了，xlsx 快照仍正常，找维护者更新 EXTRACT_JS |
| 退出码 4 / `git push` 报 `schannel: failed to receive handshake` | 间歇性 TLS 抖动，数据和 S3 已同步完、只差推送；手动 `git pull --rebase --autostash && git push` 即可，下一轮也会自己带上 |
| 任务 State=Ready 但 LastRunTime 停在昨天、NumberOfMissedRuns>0 | 触发点落在没人登录的时段（任务是 Interactive）。已有 at-logon 触发器补跑；确认它还在：`(Get-ScheduledTask TTDramaDaily).Triggers` |
| git push 失败 | 本机跑一次 `git push` 按提示配置凭证 |
| 系统没装 Chrome / 启动失败 | 手动跑 `.venv\Scripts\playwright install chromium` 下载自带浏览器（程序会自动回退用它） |

任务默认带浏览器窗口运行（更稳，闪一下就关）。确认稳定后可把 bat 里命令加 `--headless`。
