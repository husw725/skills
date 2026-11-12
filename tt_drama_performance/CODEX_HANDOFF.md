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

### 2026-11-12 运营 BI 终版已发布验收（最新，覆盖下方进行中状态）

- 完成本轮用户要求：核实真实逐秒数据，浏览Core/Traffic/Audience/Derivative materials，按运营与BI用途接入分集指标、单视频观看到达/点赞分布、衍生素材目录及曝光点击；明确暂未取得观众地区、素材有效播放归因、人数分母、收入成本/ROI来源。字段、口径与优先用途见DATA_INVENTORY.md，独立审核修正冷却文案后放行。
- 最终43/43目录均已正常UI尝试，不能称43部都有数据：31部非空完整分集表共1517行、1部完整空表、11部超时未取得指标。770份观看曲线，其中324份另有点赞分布；视频失败81项明确空曲线、81项超时。素材385条，229条曝光/点击均有值，156条均缺失；231条统计响应含2条双null，不能称231条有效统计。素材失败9项HTTP422、1项操作超时。12部pending继续按视频进度续采；平台不可用不补零，不承诺历史逐秒可回查。
- 注意同名剧按ID/语言独立：新补Revenge of the Abandoned Heiress ID7627885602473661456实际60行（曾因Windows乱码误读50，已对用户更正）；Taste of You实际73集/73曲线。以后SSH日志通过Python ascii或JSON ensure_ascii读取，避免直接解码控制台中文造成数字误读。
- 11点原TTDramaDaily主接口恢复并正常结束0，919d793发布40档；终批a884c1a补齐所有目录尝试并补完7部已有可用曲线的pending，11:47:49原始S3、11:49:42快速S3、11:49:54主Git、11:50:02Pages，EPISODE_INVENTORY_FINISH_EXIT0。手动发布clear_alerts=False日志末尾沿用“主状态未成功”固定文案，不代表本次11点主任务失败：最终report无主刷新失败提示，主任务实测0。
- 终版S3与Pages真实浏览器验收：43项目录与本地全等，实际分集档全等、曲线/6条MyBoss素材、按剧懒载及缓存、双语、390px、无JS错误。首屏初始0条逐秒分片请求，本次分别2.46/2.81秒，gzip105319/109929字节。Pages构建5efde39成功。入口仍为https://starlitshorts.s3.amazonaws.com/aigc/drama/report/tt_drama/report-fast.html 与 https://husw725.github.io/tt-drama-report/ 。
- 独立终版数据审核放行：Windows43档与完整report全对象/目录ID一致，跨集版本关联、秒级范围、结构与敏感字段检查0问题。Mac终版416份档案只读审计0问题；主历史仍252/253天截止11/08，周897624、前周1169751、近30天5626863、前30天6338263保持已对账。67项测试+9旧断言和5组浏览器检查见下条；新追加.gitignore data/v2/**/*.tmp（6fb42d2）防止中断写临时文件被提交，已无跟踪tmp。
- 所有本轮临时任务已删除（生产v3、RetentionProbe、InventoryFinish）。原TTDramaDaily Ready、LastTaskResult0、下一轮15:00；原03/07/11/15/19/23及登录触发均未改。后续轮次继续pending和冷却到期失败，不需要再创建持久补采任务。未发送通知、未改凭证/TLS/ACL，原用户legacy两JSON及其他项目改动保留，无未解决冲突。
- 补扫排队脚本首次因PowerShell ErrorActionPreference=Stop将unittest正常stderr当原生命令错误而退出1，测试本身完成但采集未启动；改直接Python临时任务后成功。临时Python/PS诊断均在忽略的output/diagnostics，不进入业务代码。

### 2026-11-12 逐秒与运营 BI 已接入，生产续采进行中（覆盖下方登录受阻记录）

- 用户已通过Windows项目登录脚本恢复登录。本轮正常headed UI核验并接入真实episode-page、episode-second-stats及material-catalog/material-stats；没有重放签名API、没有发送通知。业务含义与待验证字段见新增DATA_INVENTORY.md。
- 代码32bdb62、63d98e4、7e077e7、5a16ccd已推送：分集完整分页、累计/新增四指标、平台完播率/平均秒数；按无跨集歧义的itemIds匹配实际单视频曲线，保存3/5/10秒到达比例、相邻秒下降百分点及点赞时点；素材目录、曝光/点击事件比；账号平均秒数与独立日期成对可选。白蓝全宽保留，新运营入口顶部可直达，按剧hash分片动态加载。
- 帮助原文核定逐秒到达分母是总播放观众，点赞时点分母是总点赞；不是有效播放分母，也不推断流失人数。My Boss发布10/30的视频11/12仍能取得曲线，不能按旧7天提示硬过滤。视频item_id可能是同集另一个已知发布版本；关闭drawer必须等隐藏；Switch episode是普通文本而不是button role。素材时长/时间原值为毫秒。账号region不是观众地区。
- 日期选择器等待真实可见日期单元格，修复Semi空壳/重绘过渡误判。主接口失败时可保留已验收主报告、独立刷新新源并限定Git提交路径，整轮仍返回4；旧主数据不被失败中间档覆盖。素材统计不完整时保留同源旧观测，不以空值覆盖。
- 首批254b81d已生产发布：14档/569分集行/480曲线（并非全目录采齐）。S3与Pages实测首屏各2.79秒、约103KB/108KB，初始0条逐秒分片请求；真实档案全等、6条MyBoss素材、曲线、切剧缓存、双语、390px、无JS错误均通过。Pages构建成功。下一批页面数据可能改变上述覆盖数。
- Mac/Windows67项测试+9条旧断言；5组真实浏览器回归通过，独立代码审核放行。Windows早期387份存档只读审计0问题，旧主历史252/253日截止11/08。11点主接口已恢复：last7/previous7/last30/previous30及11/06-08逐日精确对账通过，不沿用本轮早先HTTP500为当前永久状态。
- 当前TTDramaDaily正在11点轮次正常续采，默认每轮20分钟/每剧10新视频；不并行打开browser_profile。阶段19档/776行/512曲线/383素材，独立审核阶段放行，但375曲线只有观看到达而无点赞分布，素材156条无曝光点击值，87视频失败含80明确空曲线和7超时。不能将运行中数目当最终覆盖或全部上线。
- 尚需：等待11点原任务结束，继续处理未尝试剧目和pending，终版审计与双站验收；清理本轮临时TTDramaEpisodeProductionV320261112及TTDramaRetentionProbe20261112（原TTDramaDaily不可删/改频率）；补写终版覆盖/任务状态。临时日志在output/diagnostics/。原legacy两JSON本地修改与其他项目改动保留；新数据由Windows原Interactive身份发布。

### 2026-11-12 登录受阻复核：需用户在项目专用浏览器登录

- 用户询问是否需要协助登录。先明确分离两问题：今晨03:00:01任务LastTaskResult4，日志实际是analytics_v2.select_dates抛“日期选择器结构改变”，不是登录失效退出2；07点漏跑1次，下一轮11点。该控件适配问题尚未在本轮修复，不能称重新登录就会解决。
- quser确认melot console1于09:16登录且运行中。再次复用原Interactive身份、headed Chrome、项目原browser_profile只读打开Core，09:17:07临时探针已实际运行并退出0，但正常桌面会话仍重定向/login，无analytics响应；据此现在确需恢复项目专用浏览器的站点登录，不能仅归因为SSH解密差异。
- 指引用户在Windows双击E:\workspace\skills\tt_drama_performance\login.bat，自行完成平台登录；脚本使用.venv Python及原browser_profile，最多等10分钟，检测成功自动关闭。用户通知登录完成后继续核验真实逐秒曲线，另核对日期控件异常。
- 只读探针日志output/diagnostics/retention-session-20261112.log；临时TTDramaRetentionProbe20261112已删，LastTaskResult0，原TTDramaDaily仍Ready、设置不变。未改采集代码、真实数据/页面、持久任务或发送通知；原legacy JSON修改及其他项目改动保留，无冲突。

### 2026-11-12 逐秒指标功能文案核验（最新，仅核验，尚未采集）

- 用户询问新版页面是否还有剧的秒级流失率。本轮只读探测平台正常Core路由，未改业务代码、真实数据、页面发布或持久计划任务，未发送消息，未调用/重放签名API。
- 新证据：匿名正常页面加载的公开前端async-main.279554c841.js，中文资源明确含analytics_episode_drawer_title=分集数据、analytics_episode_finish=分集完播率、analytics_like_rate=逐秒点赞率、analytics_second_retention_rate=逐秒完播率。还含该集发布已超过7天暂无逐秒数据、播放量不足暂无该集逐秒数据、尚未发布暂无逐秒数据等提示。
- 证据边界：前端文案证明存在相关功能设计，不能证明当前账号实际可用、所有集都能采、7天内必有数据或历史能补齐。尚未取得真实曲线、请求字段、分母/单位/日期口径；不能把逐秒完播率直接写成已核准的秒级流失率，也不能从分集累计播放推导。当前episode_details仍只保存集号/累计有效播放/片段标记，尚未接入这些新指标。
- 登录核验受阻：SSH使用原browser_profile正常打开Core被重定向/login，未捕获analytics响应；尝试复用原Interactive身份的临时只读任务TTDramaRetentionProbe20261112未实际运行，LastRunTime1999、LastTaskResult267011，不能据此证明正常桌面登录态也失效。临时任务已删除，原TTDramaDaily设置未变；后续需Windows交互桌面/正常平台登录后核对具体分集页面和实际响应。用户异步澄清问题询问其看到的是整剧或单视频/分集入口，尚未收到回答。
- 独立只读审核已解码核实上述公开资源文案，结论放行（仅限前端指标存在性与未接入事实）。本地证据output/diagnostics/retention-labels-20261112.js；Windows探针产物output/diagnostics/retention-probe-20261112/，均忽略目录不公开提交。
- 开始前pull到e2d34cf，自动补采已带回大量历史档；本轮未做完整存档审计，不沿用旧48/253覆盖数作为当前统计。原两份legacy JSON改动经autostash保留，无未解决冲突。

### 2026-11-11 五项P2已修复发布（最新，覆盖下方待修复审查）

- 用户明确要求修复。代码6f1000a、报告81bffb0已推送；独立复核最终“修正后放行”，下方5项P2全部验证关闭。保留既有业务模型与平台数据口径，不重采、不推算缺日或留存。
- series_history逐剧try现在覆盖旧档读取/迁移、记录构造、Playwright导航/等待、采集及保存；异常记入failures/failureChecks后继续下一剧。失败冷却在读档前判断，跳过不续期；坏档原字节保留。新增整循环测试覆盖坏JSON、非对象档案、导航错误、后续剧实际处理、冷却到期再次尝试。
- previous30失败保存实际checked；failure_in_cooldown按retry_hours控制同水位冷却，新水位重试，旧无时间/非法时间立即重试；跳过保持原失败时间。新测试通过真实collect控制流验证旧失败恢复、近期失败跳过、失败时间不续期、retry_hours=0及水位变化。
- 日期分析在发起时固定起止日期，await后比较输入；加载中修改/清空日期取消此次分析、清旧结果并提示重新点击，不再生成反向日期0天0播放。保留已有晚回包/预设选择隔离。真实浏览器覆盖倒序、清空、越界编辑及重新确认恢复。
- 主仓库与Pages统一run_publish_git：git diff --quiet HEAD -- 限定目标路径无差异时跳过commit，继续push/后续同步；真实diff/commit错误不吞，不依赖Git输出文案。临时真实git验证其他本地修改/untracked均保留；生产首次发布后再次执行主仓库无变化commit及Pages同步，输出UNCHANGED_MAIN_AND_PAGES_SYNC_OK。
- 已有hash分片逐字节校验并原子重建（唯一临时文件、flush/fsync、replace、失败清理）；S3/Pages复制前verify_asset验证摘要，坏分片不切快速HTML。浏览器完整性校验失败后，下次retry使用cache=reload，成功清标记，避免immutable坏缓存永久拒载。测试包含损坏恢复、模拟replace中断、阻止坏分片发布及浏览器reload选项。
- 验证：Mac/Windows50项测试+9条旧断言、三组浏览器回归通过；Windows151份存档只读审计0问题。独立复核另跑50项+9及最新HTTP回归通过。真实发布只将已有report DATA嵌入新模板，脚本先断言完全相同，未更新生成时间或AI洞察，主48/253天及现有分集画像不变。
- Windows原Interactive身份完成S3（14:32:21）、主Git（14:32:28）、Pages（14:32:35），RETRY_FIXES_PUBLISH_EXIT0，14:32:42再次无变化Pages同步成功。快速入口 https://starlitshorts.s3.amazonaws.com/aigc/drama/report/tt_drama/report-fast.html 与原分享页 https://husw725.github.io/tt-drama-report/ 均线上验证四段同源、全DATA一致、缓存、双语/剧目、390px、无JS错误及真实下载中编辑日期取消/恢复。Pages构建42973163658成功。
- 临时TTDramaRetryFixPublishValidation20261111最终LastTaskResult0后已删除；TTDramaDaily Ready，11:00:02结果0，下一轮15:00，持久频率未改。所有验证/发布进程禁用webhook，未发通知。Macpull一度TLS失败，单次HTTP/1.1重试成功，保留TLS校验与全局网络配置；autostash正常恢复原两份legacy JSON修改，无冲突、未提交其他项目改动。

### 2026-11-11 再次review：5项P2待修复（最新审查结论）

- 用户仅要求review，本轮未修业务代码、未重新采集/发布、未动真实存档或计划任务，未发送通知。审查基于65a9403；现有43项测试+9条旧断言及动态HTTP浏览器回归通过，以下未覆盖边界已在临时目录/fake/真实浏览器复现。独立采集审核确认下述前两项，主代理复现后三项；未发现P1，不能沿用此前“放行”覆盖本次新问题。
- P2（新发现）：series_history.py:181读档/upgrade_record位于逐剧try外，272行except也不捕获Playwright导航/等待错误。某剧坏JSON或ERR_EMPTY_RESPONSE会中断整批，后续剧目未访问且series_latest未保存失败冷却。独立fake101/102均复现；details/episode此前隔离修正未覆盖此模块。应把读档到保存整体放入逐剧异常隔离，保留原档，继续后续。
- P2（已知再次确认）：analytics_v2.py:419 previous30同latest失败直接continue，不判断时间/retry_hours。独立fake一个月前的失败且retry_hours=0仍不请求该区间。应记录真实失败时间并按冷却重试，不在跳过时续期。
- P2（新发现）：template.html:645仅在await前验证日期，658在await后重新读取可编辑输入框，输入变化不更新historyRequest。真实HTTP延迟首次history加载期间，11-08~11-08点击分析后将end改11-07，得到start11-08/end11-07、n0、qv0、rows0、analysisUnavailable=false的“有效”结果。应固定请求日期快照或在输入变化取消，并在异步返回后验证。
- P2（已知再次确认）：daily_update.py:933仅识别nothing to commit；无data/report变化且存在untracked时真实git输出nothing added to commit，publish_report返回4且sync_pages_repo未调用。临时真实git仓库提取该返回值再mock发布路径复现，未真实push或通知。Pages自身:475同样有此文案判定。应根据目标路径实际diff处理无变化，继续必要push/分享页同步，不能吞真正失败。
- P2（新发现，条件性）：report_delivery.py:34只因hash文件已存在就跳过写入，不校验实际字节，且最初非原子写。模拟本地生成中断/坏缓存：临时details文件改为{}后重建，manifest仍声明原SHA且复用坏文件；后续发布会把坏分片放到immutable key，页面校验拒绝，普通重试无法修复来源。应校验/原子重建分片，发布前验证摘要，完整性失败重试考虑绕过浏览器缓存。当前生产档案未声称损坏。
- 主代理复现脚本保存在忽略目录output/diagnostics/review_retry_dynamic_20261111.py；真实git无变化复现只在TemporaryDirectory及mock中。Mac原两份legacy JSON和其他项目改动保留，无未解决冲突。后续若用户要求修复，需新增对应回归并在Windows验证后再发布，不必重采现有已验收数据。

### 2026-11-11 S3同路径动态明细已上线（最新，覆盖单文件快速入口说明）

- 用户明确要求数据分离到S3同路径文件夹动态加载，并询问尚未采集字段。已实现report_delivery.py：保留原report.html完整离线/业务读取版本；快速入口report-fast.html和Pages使用output/report-web/index.html，首屏仅嵌入核心字段。四组明细details（seriesDetails+episodeDetails）、archive（seriesHistory）、legacy（legacyDaily）、history（dayDetails）放在同路径data/<section>-<sha256>.json。
- 画像/分集与单剧历史进入视区才加载，旧档展开时加载，单日明细点击日期分析才加载。并发请求复用、加载成功缓存、20秒超时、HTTP错误与SHA校验失败明确显示重试。慢日期回包不能覆盖后来选择的预设区间。预载后全重绘曾发现remote-pending未清理，已在f04f568修复并新增回归；正常加载与预载路径均验证通过。
- 发布使用内容hash不可变文件名和一年immutable缓存，HTML no-cache；S3先上传全部gzip JSON再更新gzip HTML，旧hash文件保留供旧页面读取。Pages同一提交镜像HTML与data/，S3/Pages各自请求同源相对路径，无需改变CORS、ACL、TLS或凭证设置。原S3 report.html完整原值保留；s3_fast_report=false仅关闭额外动态入口。
- 代码d676c5b、Windows UTF-8测试修正6570999、预载修正f04f568。Mac/Windows43项单测+9条旧断言、三组真实浏览器回归通过；新HTTP回归覆盖初始不请求明细、损坏200响应拒绝/重试、404后恢复、并发共享请求、晚回包不覆盖新选择、预载清占位、全量数据一致、双语/手机。独立只读数据/代码复核最终放行；Windows151档只读审计0问题。
- 实际发布Windows原Interactive身份，最终日志dynamic-final-publish-20261111.log：13:30:05 S3、13:30:17 Pages，DYNAMIC_FINAL_PUBLISH_EXIT0。初次调用完整publish_report因本轮没有新data/report变化，git commit返回nothing added to commit而退出4（旧检测只认nothing to commit），未继续Pages；已针对本轮调用sync_s3+sync_pages_repo完成两路发布，不需要提交空数据或重复采集。该无变化提交文案兼容仍是原入口边界，未在本轮改动。
- 线上 https://starlitshorts.s3.amazonaws.com/aigc/drama/report/tt_drama/report-fast.html 首屏gzip52504字节（前一版99756，减少约47%）；Mac4.03秒、Windows5.61秒，均初始0条明细请求。四组分段全量重组与完整报告逐项一致、均同源、切语言/剧目不重下、390px无溢出或JS错误。原分享页 https://husw725.github.io/tt-drama-report/ 同样验收通过，首屏53959字节、本次2.82秒；仅为本次网络实测，不保证用户所有网络延迟。
- 本轮未再采平台数据。只读核对Windows既有audience-probe/responses.json字段名：accounts存在avg_play_date/avg_play_duration和部分非delta统计，当前normalizer未入库，需核单位/日期/口径后才可展示；episodes含item_id/item_ids但当前仅保存集号/播放/片段标记。未确认分集每日、完播、时长、互动或观众地区来源，不推算留存。缺失14部分集、部分画像及205天未验收历史仍按原机制保留原因重试，不声称已补齐。
- 临时TTDramaDynamicPublishValidation20261111最终LastTaskResult0后已删除；原TTDramaDaily Ready，11:00:02结果0，下一轮15:00，持久频率未改。验证/发布webhook运行时置空，未发消息。Mac原两份legacy JSON及其他项目修改保留，autostash正常恢复，两端无未解决冲突。

### 2026-11-11 分集可用字段问答核验

- 用户询问更多数据，重点为每部剧每集。只读核对当前43份分集档：29部1417条，当前均为正片，字段仅集号/累计有效播放/片段标记；页面已在单剧详情展示曲线与折叠表。样例My Boss Is a Superstar39条、CEO and the Country Girl59条，条数不等于证明整剧全部集数齐全。
- 其余14部暂未取得可用值：9个HTTP422、2个导航异常、3个缺必要字段。不能承诺全剧目录覆盖、分集每日历史、完播/时长/互动/画像或用户留存；累计播放比较可提示待观察的异常集，不能推断用户流失原因。现有整剧画像/渠道/账号仍按各自来源范围展示。独立只读审核放行；本轮未重采、改业务代码、发布页面或发送通知。
- 开始记录前pull到cb9d015，原两份legacy JSON修改经autostash保留，无未解决冲突；新定时提交未改分集档。

### 2026-11-11 打开慢优化已上线（最新）

- 用户反馈早上版本打不开，并要求针对超时优化。实测原公开入口HTTP200、无JS错误，但原S3无压缩传输，优化第一阶段后仍曾约26.6秒，不能把本次发布表述为保证任何网络不超时。
- 代码736b10f：新增report_codec.py无损compact-v1字典编码，Python/浏览器解码保持null、0、负数、Unicode和特殊对象键；read_report_payload兼容旧/新报告。单文件不依赖外部脚本/请求。静态标题与加载提示先显示，主渲染后设置data-report-ready；关闭的历史表、覆盖日历、图表数据表及分集数据表延迟到展开时生成，切无数据范围清理旧回调。浅色与全宽偏好不变。
- HTML从Windows729200字节降至368080字节（约49.5%），首屏DOM4899降至1605（约67%）；本地4倍CPU降速FCP338.5ms降至134.9ms。这是编码/渲染优化，DATA全量一致，没有删减或重新采集数据。主已对账48/253天、近7日897624、近30日5626863、画像性别28/年龄22/渠道32、分集29部1417行保持原值。
- 报告825813a已通过原Windows Interactive身份实际发布S3/主Git/Pages，临时任务TTDramaPerfPublishValidation20261111退出0后删除。GitHub入口 https://husw725.github.io/tt-drama-report/ 实测HTTP200、约3.2秒、无JS错误。
- 代码6e76d56：保留原S3 report.html原始HTML及元数据，新增同目录report-fast.html gzip浏览器入口，Content-Encoding=gzip、ContentType为HTML、no-cache，定时sync_s3默认同时更新；可用s3_fast_report=false关闭镜像。未改变旧业务读取契约、TLS校验、ACL或凭证配置。独立只读审核放行。
- 新快速地址 https://starlitshorts.s3.amazonaws.com/aigc/drama/report/tt_drama/report-fast.html 已实际上传，公开读取99756字节、解压后368080字节，与生产原报告逐字节一致（Mac比较时仅规范CRLF）。实际浏览器HTTP200、gzip自动解压、单HTML请求，桌面/390px手机、历史展开、语言/剧目切换无JS错误；本次Mac加载约8.1秒。原入口继续兼容。
- 验证：Mac/Windows42项Python测试及9条旧断言通过；两端详情故障注入与性能浏览器回归通过，151份存档审计0问题。独立数据审核确认无损编码及来源边界不变，压缩镜像审核亦放行。
- 定时核验：TTDramaDaily Ready，今早07:00:02运行结果0，07:01:37完成，下一轮11:00；每日03/07/11/15/19/23及登录后3分钟，仍需Windows开机、桌面登录和平台登录态。本轮未改频率/持久任务、未发送消息；平台截止日仍11-08，并非11-11新数据。每轮刷新近3个数据日；画像/分集同截止日默认24小时冷却，主previous30 unavailable同水位保留缓存，不能统称全部24小时重试。
- Mac原有daily_history.json/snapshot_audit.json和其他项目修改保留，无未解决冲突。验证/发布进程webhook置空；原Claude/sonnet规则回退不在本轮修改范围。

### 2026-11-10 页面100%宽度已上线（最新布局偏好）

- 用户要求页面宽度100%。已移除1080px页面上限，容器占满可用宽度，保留两侧16px内边距；两类SVG图表移除1040px绘制上限，Top10条形图手机侧边距按宽度适配。浅色主题保留，CLAUDE.md已记录全宽偏好。
- 代码1ab1a1b、报告发布0bb35fb；直接用原报表DATA嵌入新模板，逐字符验证数据完全不变，未采集或改AI洞察。本地2560/1920/1280/390宽及线上1920/390均无横向溢出、无JS错误，图表viewBox等于实际容器宽度；Windows3组浏览器回归通过。
- 原S3+Git+Pages发布退出FULLWIDTH_PUBLISH_EXIT0。临时任务TTDramaFullWidthPublishValidation20261110已删除、LastTaskResult0，原TTDramaDaily仍Ready；禁用验证/发布通知，未发消息。两端无冲突，用户legacy JSON修改保留。

### 2026-11-10 白色浅色主题已上线（最新样式偏好）

- 用户指定浅色CSS，并要求后续页面沿用。`template.html` 已使用其全部主题值：light、页底#f5f7fa、白卡片、次级底#f7f9fc、深色文字、蓝色#1890ff/#1677c8；保留既有--gold变量名兼容用法，但值为用户指定蓝色。同步处理表格展开/悬浮行、提示框阴影及涨跌语义色；项目CLAUDE.md已记录默认浅色偏好。
- 本轮为纯样式修改：Windows只替换report内style块，并逐字符验证其余HTML、脚本与数据完全一致；不重新采集、不改数据或AI洞察。Mac桌面/手机实际截图检查及Windows3组浏览器回归通过，线上确认light、白卡片、指定灰底和蓝色，390px无溢出、无JS错误。
- 样式提交1afc67b、报告发布539ac7c；原S3+Git+Pages发布退出0，网址 https://husw725.github.io/tt-drama-report/ 。临时任务TTDramaLightThemePublishValidation20261110已删，原TTDramaDaily仍Ready；webhook运行内置空，未发通知。两端无冲突，Mac原有两份legacy JSON改动保留。

### 2026-11-10 三项P2已修复并发布（最新，覆盖下方待修复状态）

- 用户明确要求修复复审发现的三项P2。代码提交 `fa33bf7`，报告发布提交 `91ac9b1`；独立修复复核“修正后放行”，三项均验证关闭。
- 两个新增采集器的读档、旧档校验、冷却时间解析、采集和落盘均在逐剧异常隔离内；坏档不覆盖，记录错误并跳过该剧，继续后续标题。详情末尾汇总也带errors读取，避免坏档在循环完成后再次抛断；manifest只保存异常类型及坏档数量，不泄露坏文件内容。坏档保留供诊断，不自动覆盖或补零。
- 后端拒绝全null的画像字典；前端严格校验有限数字、类别和分布合计，只有真正可用的性别/年龄才计数，未用Number(null)凑0%。分集rows先验列表类型，缺rows或空列表的合法失败stub仍可读取；前端Array.isArray兜底。采集/观测时间缺时区的异常档同样拒绝并逐剧隔离。合法0值、缺集null、片段隔离保持原语义。
- 新增 `tests/test_collection_isolation.py`：真实collect循环+临时fake页面，覆盖坏JSON、坏schema、无时区时间，验证原档字节不变且后续标题实际刷新/落盘；新增 `tests/browser_detail_regressions.py`（Windows加 `--channel chrome`）：真实浏览器验证全null不计数、不画0%，rows={}不崩溃，正常0%、缺集及片段仍正确。
- 验证：Mac和Windows均37项测试、9条旧断言通过，3组真实浏览器回归通过；Windows `daily_update.py --audit` 151档0问题、退出0。使用现有已验收数据重建报告，本轮未再次拉取平台数据；主48天、性别28、年龄22、渠道32、分集29及主近7日897624/近30日5626863均未改变。异常注入只在临时目录或浏览器内存，不修改真实档案。
- 发布：复用原Interactive身份实际完成S3+主Git+Pages，`REVIEW_FIX_PUBLISH_EXIT 0`。线上实际注入全null画像与rows={}后无JS错误，画像计数从28正确降至27、未绘0%或异常分集；恢复后39集曲线、手机390宽及语言正常。地址保持 https://husw725.github.io/tt-drama-report/#seriesDetailsCard 。
- 收尾：临时任务 `TTDramaReviewFixPublishValidation20261110` 已删除，LastTaskResult0，原TTDramaDaily仍Ready且设置不变；验证/发布webhook运行时置空，未发送通知。Mac原有两份legacy JSON改动保留，无冲突；原Claude/sonnet洞察依然回退规则洞察，未改业务模型。

### 2026-11-10 二次代码审查：3项P2待修复（优先）

- 用户要求再次review。本轮只审查与临时故障注入复现，没有修改业务代码、生产数据、页面或Windows任务，没有发送通知；本记录优先于前一轮“修正后放行”的结论。审查代码基于50fe08b，期间拉取的6c312a9仅定时数据/报告更新，业务代码未变。
- P2：`series_details.py:232` 与 `episode_details.py:102` 的旧档读取/冷却时间解析位于逐剧异常隔离之外；单个JSON损坏会让整个补充采集函数退出，后续剧目一直得不到刷新。临时三剧目录100/101/102，100冷却跳过、101坏JSON，实测JSONDecodeError且102未访问。父入口只捕获整批异常并继续主日报，不会恢复剩余标题。
- P2：`series_details.py:165-168` 对全null的gender/age字典调用distribution，忽略其None返回；因此异常档仍能通过validate_record并进入报告。实际浏览器复现Male/Female/Unknown均显示0.0%，违反缺失不补零。应拒绝或规范化全null字典，并防前端Number(null)补零。
- P2：`episode_details.py:45-46` 以Python真假值判断无rows，允许 `rows={}` 通过验证。JS把空对象当真，`template.html:869` 执行rows.filter抛TypeError，单剧详情及后续渲染被中断。应先严格检查rows为数组/列表，前端也做类型兜底。
- 验证：现有33项测试及9条旧断言仍通过，151份实际存档结构审计0问题；三个问题通过隔离临时数据/实际浏览器复现，未声称当前线上存档已触发。需要新增逐剧坏档隔离、全null画像、非列表rows回归测试后再修复发布。Mac原有两份legacy JSON改动与其他项目改动保留，无未解决冲突。
- 独立复审同样复现这3项P2，未发现P1；本轮结论为待修复，不能沿用前轮放行视为这些边界已验收。

### 2026-11-10 单剧画像、流量、发布版本与分集已上线（最新）

- 用户明确批准将已核验的新字段接入页面。新增 `series_details.py` 与 `episode_details.py`，Windows正常入口默认随 `v2_series_details=true` 自动运行；原计划任务频率、Interactive登录方式与业务模型未改。仅观察正常Audience/Traffic/Core UI响应，不重放签名API。
- 全目录43部均已尝试并重试：性别28部、年龄22部，整剧/账号分层流量来源32部，账号元数据与平台新增明细各32部。性别与年龄可独立缺失，年龄Unknown按当前UI合并；未提供观众地区，账号地区明确单列，不代替观众所在地。正常日期筛选已实测改变性别结果，短区间年龄可因样本少被隐藏；页面标明每分区实际查询范围与采集时间，不随主增长榜日期切换。
- Core范围接口不可作其他tab可用性的门禁，已改为独立尝试；优先近期30天与可查范围交集。范围选择失败时仅可保留本轮同ID同endpoint成功响应的真实范围，显示回退标识，不改标成目标区间。失败保留旧值及原checked，成功/失败同截止日默认24小时冷却，新截止日刷新；修改旧实测保留修订档。
- 账号delta与主报表同ID同范围仍存在显著来源差异。报告逐项显示平台合计/主报表差异（当前29different、2matched、12unavailable），平台原值只在独立发布版本表，不进主榜、贡献率或互动效率。账号资料只在日期范围相同才关联，并单独披露采集时间/刷新失败。当前UI渠道映射特别注意：other_profile=作者主页，self_profile=观看历史/收藏/下载，旧词典曾不同。
- 分集43份档案中29部有值，共1417行。本源请求仅contract_id、没有日期筛选，是采集时累计快照；返回平台范围03-01~11-10不等于已验证水位，固定 `queryMode=cumulative_snapshot`、`dataThrough=null`。正片缺集保留null，实测0保留；片段/未编号内容仅在表格，不进曲线，不推算留存。分集与画像目录取ID并集，不因画像缺失藏掉可用分集。
- 缺失不能统称无数据：画像3部平台空数组、12部日期控件点击超时；渠道/账号各11部点击超时。分集14部未验收：9个HTTP422、2个导航/网络异常、3个缺少必要字段。保留原因后续重试，不用0补齐，也不能声称43部全部可用或画像历史已补齐。主机构历史仍48/253天，未增加已对账覆盖。
- 验证：Mac/Windows均33项测试及9条旧断言通过；Windows真实 `daily_update.py --local-only --headless` 退出0（14:52:10）。151份当前档审计0问题；详情/分集只验结构与来源边界，不代表跨来源相等。主近7日有效播放897624、近30日5626863、最新日148327及48天覆盖均未被新来源改变。实际HTML全43剧切换、缺年龄保留性别、分集曲线/数据表、双语、390px手机宽度均无JS错误/横向溢出。独立代码/安全/数据审核最终“修正后放行”。
- 发布：复用Windows原Interactive身份实际执行原S3+主仓库Git+Pages分发，`DETAILS_PUBLISH_EXIT 0`，临时任务LastTaskResult0；数据提交 `e97bd0a`。线上 https://husw725.github.io/tt-drama-report/#seriesDetailsCard 已实际浏览器验证：43目录、28性别、22年龄、29分集、48主日档，分集SVG/语言/手机交互正常。S3固定地址保持原样。
- 收尾：临时任务 `TTDramaDetailsPublishValidation20261110` 已删除，TTDramaDaily仍Ready，未增加持久任务；本轮验证与发布进程webhook置空，未发送通知。Mac原有 daily_history.json / snapshot_audit.json 改动经autostash完整保留，无冲突；本轮预览备份在忽略目录 `output/diagnostics/before-details-publish-pull/`。已向共享数据审核说明追加跨模块口径、范围门禁与画像映射陷阱。原Claude/sonnet洞察仍因CLI返回无法解析而回退规则洞察，未更换后端。

### 2026-11-10 单剧观众与流量页核验

- 用户询问性别、年龄、地区是否已有及更多可展示数据；本轮只做来源核验，尚未接入生产报告，不得把“平台样本有数据”说成“我方页面已展示”。
- Windows 现有登录态正常UI抽查 CEO and the Country Girl、My Boss Is a Superstar、Falling for the Superstar；3部 `audience-stats` 均HTTP200/code0，有性别与年龄比例。日期请求分别为10-27~11-08、10-30~11-08、10-27~11-08；尚未切换范围做对比，不能据请求带日期就宣称已验证区间口径，更不能宣称43部/全部历史均有画像。
- Audience页面只展示性别及年龄。性别保留Unknown；年龄UI为18–24、25–34、35+、Unknown，当前样本Unknown合并 `other_pct` 与 `age_unknown_pct`，不能直接把other标成未成年。未发现观众地区分布；`accounts.region`是发布账号地区，不是观众所在地。
- 3部 `traffic-added` 有账号增量；2部实收 `traffic-stats`/`accounts`，有流量来源占比、账号播放/点赞/评论/收藏及部分平均观看时长。channels同时含无collection_id的整剧层和有collection_id的账号层，不可相加；账号share_pct不能未经核验便等同区间新增播放贡献比例。未捕获响应不等于确认无数据。
- 建议优先接入单剧画像（显式未知、范围及更新时间）、整剧与账号流量来源、发布账号表现对比；分集完播/时长/曝光点击需再核字段及口径，逐集播放变化不能冒充用户留存。原始响应与截图仅在Windows `output/diagnostics/audience-probe/`，含临时签名头像地址，不公开提交。
- 独立数据审核结论“放行”：样本范围、未知年龄映射、账号地区与观众地区区别、渠道层级和未验证指标边界均已复核。本轮未改采集/报告代码、未发布或发送通知。

### 2026-11-10 新版已上线；全部历史仍未补齐（优先）

- 用户已明确授权：整体优化新版采集/报告，以新版单日细数据取代旧合并档主分析，并逐日补采所有历史（按页面声明从2026-03-01开始）。旧文件必须保留，不能拿旧合并档冒充补齐。
- 已实现 `analytics_v2.py`：仅观察正常浏览器日期/分页操作触发的响应；按稳定ID保存区间Delta；分页完整、ID唯一、日期覆盖、剧目/机构增量精确对账；逐日再按ID与整周/整月核对播放/点赞/收藏/评论；历史修订保留原记录；全历史失败留证并24小时重试。两个来源水位可不同，但各自必须覆盖区间，剧目分页自身必须一致，累计表只用最新剧目水位。
- 已实现 `report_v2.py` 与模板扩展：主增长/趋势/比较只用新版数据，旧指标在独立档案；近7/30日贡献与互动效率、名称搜索、新剧筛选、任意日期分析、历史覆盖日历；缺日不生成完整排名并同步清图。原Windows任务入口/模型依赖保留。
- 数据已正式落在 Windows `data/v2/` 并推送Git；`output/diagnostics/v2-trial/` 仅为早期试验，不是生产最新状态。03-01~11-08的253天均已逐日尝试并重试；全机构单日档48天（最近连续10-04~11-08共36天，另12个历史日），205天未验收：204个服务端错误、1个机构趋势缺日。不能声称全部历史已补齐，不能用旧档或0填缺失。
- 独立审核按ID复算：近7日qv897624、like43303、fav8033、com327；前7日qv1169751、like119681、fav14944、com525；近30日qv5626863、like393291、fav68179、com2402。逐日与整段逐剧四指标差异均为0；近7日播放环比-23.3%。
- 单剧详情正常UI目录43个ID，按30天分段另得14部、739个播放日值、273个平均时长日值。322个播放点与主日档同ID重合且差异0；其余只有单剧页来源，不算机构已对账覆盖。独立卡片可选剧目、日期、播放/时长；文案明确核对统计属于全档播放，不代表当前区间或时长已核对。
- 验证：Windows正常入口 `--local-only --headless` 退出0；Windows与本地23项测试、9条旧断言通过；原55份XLSX读取兼容。独立审核最终“放行”。65份主/补充档案离线复核0问题；线上页面实测schema2、48天、14部、739/273日值，搜索/日期/语言交互无JS错误，手机宽390=文档宽390。
- 发布：Windows原Interactive身份实际完成S3、主仓库Git与Pages同步，`FINAL_PUBLISH_EXIT 0`，GitHub Pages构建成功且线上验证通过： https://husw725.github.io/tt-drama-report/ 。Windows配置了原Pages仓库目录（其他配置值保留），网络回退保留TLS校验，不改全局设置；SSH WinCredMan问题不影响原Interactive身份推送。
- 收尾：临时任务 `TTDramaV2PublishValidation20261110` 已删除；原 TTDramaDaily Ready，未改频率/Interactive设置，核验时下一轮11-10 15:00、漏跑0。验证进程禁用webhook，未发送钉钉。Mac原有两份数据JSON改动经autostash保留、原字节另有本地诊断备份；两端无未解决冲突，其他项目改动未提交。
- 待办仅为外部数据缺失与后续补采：原任务按24小时失败冷却继续重试；单剧失败按每个ID的failureChecks计时，不被新manifest续期冻结。保留平台错误/空曲线/未验收的区别；若平台恢复，按精确对账验收补入。业务Claude/sonnet调用未换后端，当前CLI洞察返回无法解析时仍回退规则洞察。

### 2026-11-10 初始诊断（历史）

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
