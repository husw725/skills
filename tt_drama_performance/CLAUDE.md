# TT 短剧日报管道

TikTok 短剧数据日报（建于 2026-07-28），每日更新流程见 PLAYBOOK.md。

## 2026-11 新版页面（优先于下文旧版事实）

- 登录检测兼容 `Export` / `Export Data`。新版通过浏览器正常切换日期和分页，观察站点自己发出的响应；不直接请求或重放带签名的 API。
- 新版按 **稳定剧目 ID + 明确起止日期** 保存实际增量，数据在 `data/v2/`。剧目分页条数、ID 唯一性、机构趋势逐日覆盖和汇总必须一致；区间剧目有效播放增量之和与机构趋势/汇总精确对账。日档齐全时再按 ID 核对逐日之和与整段的播放、点赞、收藏、评论四项。
- 已实测可选择历史单日，不再依赖相邻累计快照相减。用户于11-10明确要求全部历史：默认从 `v2_history_start=2026-03-01` 逐日扫描，刷新最近3天；失败日期默认24小时后重试，机构历史修订额外重采并保存旧修订。设 history_start 为空时才使用近 `v2_backfill_days` 天的窗口。界面允许选日期不代表服务端能返回，服务端错误/未验收日期必须分别标注，不能编造历史或月环比。
- 新 Excel 有17列但没有 ID，且累计值与页面存在滞后。增长分析以页面返回的区间增量为准，不使用 Excel 累计列，也不把新旧累计直接相减。日期筛选会改变导出行数与新增列，下文“导出与范围无关”仅对旧版成立。
- 当前新版机构趋势仅返回有效播放；总播放、完播、分享等缺失字段留 null，不补0、不继续画成当前指标。旧 `daily_history.json` / XLSX / 验收台账保留，报告提供原始历史指标存档。合并系列成员集合不一致时不算该组环比。
- `python daily_update.py --audit` 在存在新版 manifest 时只读重算新版日档/区间档和逐日/整段一致性，不重写旧台账；无新版存档时沿用原审计流程。`python generate_report.py` 自动选择已有新版 manifest，旧存档仍可通过 `read_snapshot()` 读取。
- 新版主增长榜/趋势/区间分析仅用新版逐日实测，旧版合并档不再混入。报告保留双语、系列分组和累计明细，增加近7/30日增长贡献、前期比较、区间收藏/互动千播放、剧名搜索、14天内上新筛选、历史覆盖日历与任意日期分析。累计明细注明查询覆盖范围，不假称全机构所有历史剧目。自定义区间缺任一单日就不能生成完整排名；同时清空分析图，不让上次图形冒充新查询。
- `series_history.py` 是独立补充来源：通过单剧详情页UI、按30天分段保存播放/平均时长曲线。43个目录ID不等于43部均有可访问数据；当前有HTTP500/422、空曲线与稀疏日期。缺日段标partial、24h后重试，实际值保留逐点observedAt（旧段迁移注明时间来源），不补0；与机构日档重合的点逐ID核对。报告在独立卡片展示，不增加全机构已验收日数、不推导互动、不与旧累计混算。`v2_series_history` 默认true。
- `series_details.py` 通过正常Audience/Traffic页与日期操作采集单剧性别/年龄、分层渠道、账号元数据及平台账号增量，分别保留查询范围和采集时间，保存于 `data/v2/details/`；更新旧实测时保留 `details_revisions/`。`v2_series_details` 默认true，同截止日成功/失败24小时冷却，新截止日刷新。core data-range只能辅助选择日期，失败不能阻止其他tab独立采集。样本不足可只缺年龄或性别；年龄Unknown为other_pct+age_unknown_pct，不解释为未成年。
- 单剧画像不合并系列，不推导独立观众数；账号地区不当观众地区。渠道按整剧/collection_id分开，账号资料只同查询范围关联。当前实测账号delta合计与主剧目统计存在显著来源差异，报告按同ID同范围核对并披露；这些原值单独展示，不用于主增长榜、贡献率或效率计算。账号share_pct、头像签名URL、UID和未核准时长不入库。`--audit`对详情检查结构/日期/数值，不把跨来源差异算成主数据已对账；不可用仍留空。
- `episode_details.py` 单独观察Core页 `episode-views` 的无日期筛选请求，保存于 `data/v2/episodes/`。这是采集时累计快照：响应range末日可能是采集当天，不代表数据截止；固定 `queryMode=cumulative_snapshot`、`dataThrough=null`，绝不标成主报告最新日或所选区间增长。缺集留空，片段只单列表格；不由各集播放比计算用户留存。默认随 `v2_series_details` 运行，失败保留旧实测时间；新截止日刷新，同截止日24小时冷却。旧修订留在 `episode_revisions/`。
- Windows 分发：默认代理/Schannel连接失败时，Git使用单次OpenSSL+直连重试，S3保留TLS校验直连重试，不修改全局代理/证书设置。SSH非交互会话可能读不到WinCredMan凭证；实际计划任务Interactive会话已验证可push。Windows已配置 `pages_repo_dir=E:\workspace\tt-drama-report`，复用原GitHub Pages地址。临时验证任务要及时删除，验证脚本禁用webhook。

## 工作约定
- 页面默认使用用户指定的白色浅色风格：浅灰页底、白色卡片、深色正文与蓝色强调（`#1890ff` / `#1677c8`）。后续页面维护沿用 `template.html` 的这套主题；表格、浮层和图表保持同一浅色配色。
- 页面占满可用宽度（100%），保留两侧16px页内边距，不恢复1080px容器上限；SVG图表按实际容器宽度绘制，手机端保持内容不横向溢出。
- 原始 `report.html` 保留可独立打开的完整单文件HTML，兼容业务读取与离线检查。浏览器快速入口和Pages使用 `report_delivery.py` 生成的 `output/report-web/index.html`，按需请求同源 `data/<section>-<sha256>.json`：画像/分集与单剧历史在进入视区时加载，旧档在展开时、单日明细在日期分析时加载。新版生成器用 `report_codec.py` 的compact-v1无损编码减少重复字段/字符串，浏览器恢复原DATA结构；旧plain JSON仍可读。读取已生成报表请用 `read_report_payload()`，不要再正则后直接json.loads。折叠明细展开时才绘制，清空查询时须同时用 `clearDataTable()`取消旧回调；浏览器检查先等待 `document.documentElement.dataset.reportReady==='true'`。
- S3保留完整原始HTML的 `report.html` 兼容已有业务消费；默认另同步动态浏览器快速入口 `report-fast.html` 及同路径 `data/`，HTML/JSON使用HTTP `Content-Encoding:gzip`。完整数据保持一致，但首屏不再内嵌全部明细。数据段按内容hash命名、长期immutable缓存，HTML no-cache；先上传全部数据段再切HTML，旧hash不能随新发布删除。Pages在同一提交镜像index.html及data/，各站请求自身同源相对路径，不改S3桶CORS/ACL。分段读取校验SHA-256、20秒超时、有明确失败和重试提示；并发请求合并，晚回包不得覆盖更新后的日期选择。`s3_fast_report=false` 可禁用此额外入口，不改原地址。SDK若读取快速入口须按Content-Encoding处理，不能当未压缩文件直接存取。
- 本仓库每 4 小时有 Windows 定时任务自动推送数据提交。**动手改任何东西之前先 `git pull --rebase --autostash`**，改完立即 commit+push，压缩撞车窗口。report.html 冲突时：取 theirs 完成 rebase → 重新跑 generate_report.py → amend。
- **`git pull --rebase --autostash` 在 autostash 落不回去时返回码仍是 0**（已复现验证），只在 stdout 里留一行 "Applying autostash resulted in conflicts."。index 留 UU 但**没有** MERGE_HEAD/rebase-merge，`git rebase --abort` 救不了，只能解冲突后 `git add`（本地改动同时还留在 `git stash list` 里）。这之后每一轮 pull 都是 "Pulling is not possible because you have unmerged files"：采集照常、git 全废。2026-08-26 就这么静默卡了 5 天 30 轮，08-24/08-26 两份已验收快照一直没推出去。`daily_update.git_stuck()` 现在每轮开头 + 每次 pull 之后都体检 index，卡住就钉钉告警并禁掉本轮 git（S3 和本地入库照常）。

## 关键事实（代码里看不出来的坑）

- 页面 Export Data 导出的 xlsx 是**各剧全量累计快照，与页面日期范围无关**（已用单日范围对比验证，两次导出字节一致）。所以剧目级日增量 = 相邻两天快照做差。
- 机构级每日趋势数据在页面 React fiber 状态里（`scripts/extract_daily.js` 提取），API 有 X-Bogus/X-Gnarly 反爬签名，不要直接调接口。
- javascript_tool 单次输出约 1000 字符，大 JSON 要 `window.__dump.slice(i, i+1000)` 分块读取后本地拼接校验。
- `generate_report.py` 会把 `data/daily_stats_*.json` 合并进 `data/daily_history.json`（按日期去重）。
- 会话内 cron（15:03）是 session-only、7天过期；已改为 Windows 计划任务 TTDramaDaily（03:00 起每 4 小时一轮，共 6 轮：03/07/11/15/19/23，run_daily.bat 开头 git pull 自动同步代码）。
- 任务是 **Interactive 登录态**运行（config.json `headless:false`，要弹真 Chrome 窗口），所以**不能**改成 "Run whether user is logged on or not"（S4U 无桌面，headed Chrome 会挂）。代价是没登录时触发点直接跳过——已加 **At-logon 触发器（延迟 3 分钟）** 补跑，并关掉了电池限制（DisallowStartIfOnBatteries/StopIfGoingOnBatteries）。2026-08-13 凌晨重启后漏掉 03:00/07:00 两轮就是这个原因。
- 平台数据滞后 2~3 天、夜里刷新、偶尔跳更。页面顶部 "data updated to YYYY-MM-DD"（中文界面"数据更新至"）**不可信**：平台会先翻这个标注、剧目行晚一天才补（2026-08-18 实测）。快照按**对账反推出来的真实截止日**命名，既不按标注也不按导出日期。
- **对账是这个管道的地基**，必须按"同口径"算（只算两份快照都在的剧）。平台会把存量老剧新纳入统计，这类剧首现带的是全量历史累计（实测 +1,730,722），混进全行求和会把偏差冲爆（8-18 那次 148.6%），反而盖掉"老剧一部都没刷新"的真问题。同口径增量 vs 官方趋势区间和：正常日子偏差 <1%（常常个位数精确相等），极灵敏，可以直接当探针。
- `true_cutoff()`：同口径增量 ≈ 趋势 (上一份, X] 区间和 的那个 X 就是这份快照的**真实截止日**，按 X 命名入库。定不出 X = 剧目行只刷了一部分 → 隔离重试。这一条同时消灭了"标注错位"和"半刷新入库"两类 bug。
- 容差 `MATCH_TOL=0.10`：平台日界切分有漂移，实测最大 ±6.8%（08-09 -6.46% / 08-10 +6.75%，符号相反、两天合计只差 0.04%，是量在日界间挪动、**不是丢数**，绝不能当残缺拒收）。而相邻候选区间相差约一整天的量（≈100%），10% 既容得下漂移又不会把两天认混。`CLEAN_TOL=0.03` 内记 ok，超了记 smear。
- 台账（`data/snapshot_audit.json`）**读不出来时绝不能当空台账继续**：空台账等于所有历史快照一起退回"未验收"，下一轮会把它们全部重采、还可能拿未验收的导出顶掉好快照。老逻辑 `except: return {}` 就吃过这个亏——2026-08-26 那次 autostash 把冲突标记写进了这个 JSON，27 档当场只剩 2 档。现在 `audit_load()` 只在文件不存在时返回空，解析失败一律抛 `AuditCorrupt`（由 `__main__` 总闸告警退出）；`--audit` 传 `strict=False` 才降级，因为它本身就是重建工具。写入走临时文件 + `os.replace` 原子替换。
- **跳过判定只认验收台账**（`data/snapshot_audit.json`），绝不能只看文件在不在。老逻辑一份半刷新快照入库后就被永久冻住、后续每轮全跳过——2026-08-18 就是这么漏掉 08-19 的。没过验收的导出一律隔离到 `data/_quarantine/`（已 gitignore），把数据日文件名腾出来，下一轮继续采。导出先落 `.candidate.xlsx`，验收通过才改名入库，已入库的好快照永不被覆盖。
- `python daily_update.py --audit`：离线全量复查（不开浏览器、不改数据），逐档对账并重建台账，列出所有对不上的区间和缺采日期。改完采集逻辑或怀疑数据时先跑这个。2026-08-31 基线：30 份快照 0 个对不上（25 ok + 4 smear）。注意 tsum/dev 会随 `daily_history.json` 刷新而微动（平台会小幅修订历史趋势值），只要 status 不变就不用管。
- **导出永远是"当前"全量累计，没有按历史日期回查的入口**——错过某天的剧目级状态就永久找不回来，只能靠对账反推重贴标签。已知永久缺单日切分：**2026-08-02、2026-08-19、2026-08-22、2026-08-25**（都折进标注正确的 2 天档，偏差 0.15%/0.00%/0.00%/0.00%）。
- 缺采**必须在页面上如实标注**，日均只能作为明确标记的估算值展示（2026-08-25 决定：趋势图合并区间用**虚线**画日均，BI 惯例估算值虚线；实测 `values` 仍留 null，估算走 `lineChart` 的 `est` 通道，tooltip 标 ≈日均）。`generate_report.py` 算出 `gaps` → 报告顶部"数据完整性说明"卡片；增长榜标 * 和"共N天合计"；单剧趋势图按自然日铺轴、合并区间内实测一律 `null`（`lineChart` 支持 null 分段 + 孤立单点画圆点），虚线段来自 `est`。
- 趋势图的**缺采阴影带**（`lineChart` 的 `bands` 参数）：留空的日子上覆一条浅金色带，带内标"缺采 / N日合计 X"。要点是**合并档的截止日本身也得留空**——它的量和前面几天粘在一起，同样拆不出单日值（8-20 档装的是 8-19+8-20）。带子向两侧各让半格，正好卡在相邻实点之间。这样单日轴上没有假点，但那个准确的区间合计能在正确位置看见，断层从"像故障"变成"明确标注的合并区间"。缺采落在轴最右端时尤其重要，否则折线停在前几天、图看着像落后了。
- **导出列按列名读，不按位置**（`generate_report.read_snapshot`/`HDR`，中英表头都认）。2026-08-24 起平台把 "Total Views/总播放" 列从导出里砍了（8→7 列），按位置读把"人均播放时长"当成总播放，同口径增量 −3.5 亿，被当成半刷新隔离了 5 轮。对账探针因此从总播放切到**合格播放 ↔ 趋势 innerfeedVv**（历史各档偏差同样 <0.2%，08-23 档精确相等）。剧目级报告已无总播放：互动率/收藏千播放分母改为累计合格播放，合格率列删除；机构级趋势仍有 vv。
- **导出时 `TargetClosedError`（窗口闪一下就关）= Chrome 主进程崩了**，转储在 `browser_profile\Crashpad\reports\*.dmp`（`pip install minidump` 后 `python -m minidump --exception x.dmp` 可读）。2026-09-20 实测：`ptype=browser`、每次同一地址 `EXCEPTION_ACCESS_VIOLATION`，根因是 `browser_profile\Default\shared_proto_db`（Chrome 共享 proto LevelDB，存下载进行中记录）里的脏记录——重试/重开 context/无头/换 Chrome 153 全无效，只去掉这个目录就好，且不影响登录态。现在 `purge_profile_db()` 在崩溃重试前自动清它（留证到 `data/_quarantine/`）。排查顺序：先看转储是不是同一地址 → 清 shared_proto_db → 再怀疑 Chrome 版本。二分手法：复制 profile（`shutil.copytree` + `ignore_patterns`）做最小复现，比猜快得多。
- 数据组织：导出 xlsx 每行是一个 contract（合同）；contract 下挂多个 collection（版本/语言）。剧目明细表 React 状态里 contractInfo.publishTimeSec = 上线时间（UTC 显示），已抓到 data/drama_meta.json，每日 collect_meta() 翻页刷新（Semi Design 分页 .semi-page-item）。
- 上线日期换算用 UTC（datetime.utcfromtimestamp），本地时区会和平台页面差一天。
