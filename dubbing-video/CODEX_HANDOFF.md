# Codex 接手：dubbing-video

## 当前接力记录

### 2026-10-10 配音恢复，第5集已实际生成（最新）

- 用户再问网页无新成片。核验仍4成片，译稿已审至13；翻译在14导出时错误将curse匹配进cursed，拒绝自然巴葡Sou amaldiçoada。已修复export_translation复用ProtectedGlossary源词边界，不更改锁定名称/术语；14缓存直接复用导出成功，当前15翻译中。
- 用户前一轮质疑通过剧本无法判断；重新核对第5剧本明确母亲日记FLASHBACK/母亲第一人称视角。按原有整剧配音授权进行制作选角：Mother已有音色；不宣称源reader已识别，原speaker保持unknown。此前等待用户选旁白的记录被本次基于剧本的选角覆盖，没有创建Narrator_EP05。
- 新增production-casting.json显式复用已有声音，逐cue绑定speech-units指纹，必须完整覆盖unknown单元、给选择依据；声音不在bank、输入变化、已知角色覆盖均拒绝。决定写入plan production_casting并source_speaker_verified=false，受既有不可变计划与TTS指纹保护，不能混用旧断点。
- Windows已保存EP05三句Mother、EP06尾句If you don't选择Carmilla作上一句的条件续句、EP08尾称Father选择Laura、EP09倒计时Three days remaining选择Narrator_EP01。后三项是上下文制作选角，字幕台词缺剧本直接证据，源speaker仍unknown；不改变台词/时间/三天期限，不据此新增克隆。私密选择文件在忽略output，仅Windows业务生成。
- 提交5b3858e/aa7f88f已push/Windows pull，64项unittest通过；新增旧术语误命中/真缺词拒绝、unknown身份保留/已有音色限制/陈旧选择拒绝、renderer首句未完页面显示启动。旧EP04不可变计划和旧TTS缓存回归继续通过。
- 生产队列PID31300、renderer PID29416真实Running；第5配音计划36单元，4角色全部bank复用，没有clone参考/新增clone；最后核验已完成6/36个TTS单元，有已接受MiniMax task回执，三路并发继续。后续顺序渲染、提前准备当前/下一集。翻译PID10036单独处理15，不宣称32完成。
- publisher重启以加载首句前启动显示修复；S3仍仅成片+index，不上传原素材/译稿/日志。下一步核验第5合成上传，观察后续未识别角色/参考时长不足等停止，付费歧义pending禁止自动重提。代码审查入口codex review；本次费用审查未改paid重试，新增casting只能已存在bank音色。

### 2026-10-10 第5集暂停诊断与翻译恢复（最新）

- 用户反馈网页第5集停止。实际production queue已退出：build_episode_plan对3条日记unknown reader拒绝自动新克隆，既有防浪费约束正常生效。第5集36条已完成第二轮文本审核并原子暴露editorial，第6–8集也已完成editorial。
- 后续Windows翻译在第9集因ChatGPT连接超时、workspace routing discovery failed退出，非已知认证失败。已重启唯一Codex-Carmilla-Translate-Remaining，复用5–8集，实际从9集生成；最后核验进程10852存在，9集初稿已有完整JSON输出，第二轮仍在处理，不能宣称第9集审核完成。
- 已用异步问题询问用户第5集是否复用第3集已有旁白音色；尚无回复。属于配音选角，原声reader继续unknown，不可擅改为Mother或当作已听审。第5集配音队列保持停止，没有新增MiniMax调用；待用户选择后需实现显式复用映射并恢复队列，禁止随集新克隆。
- 业务提交582c158已push/Windows pull：dashboard分别显示译稿审核数/当前翻译集与生产状态；editorial未export也显示已审，暂停时标任务暂停或翻译进行中·配音暂停。翻译fatal保留当前episode/pending而非丢弃进度。Windows60项unittest全通过；真实既有publication-state沿用，成片不重传。
- 给queue-progress加入安全public_detail，说明unknown旁白选择原因，不更改停止stage。清理已核验的2个重复publisher Python子进程（停止计划任务不足以终止子进程），重启唯一发布worker PID30528；没动其他Python服务/付费渲染。
- 页面仅上传既有成片和index，30秒刷新和10分钟历史保留；下一步收到选角回复后继续第5集配音。可用codex review复审本次代码。

### 2026-10-10 Windows已登录，译稿worker已接入（最新）

- 用户已登录，SSH调用codex login status退出0核验。登录任务Codex-Carmilla-Login条目已清理，不复制/打印认证文件。
- 新增codex_translate_episode.py，在Windows调用已安装原生codex.exe（路径npm/node_modules/@openai/codex/node_modules/@openai/codex-win32-x64/vendor/x86_64-pc-windows-msvc/bin/codex.exe）；实际默认模型gpt-6.1-sol/provider openai，read-only、approval never，无MiniMax/MCP调用，提示词仅经stdin传入。
- 每集读取匹配剧本及其DOCX真实SHA、原字幕、全剧锁定bible、邻集剧本及最近2集译文；CLI结构化初稿+第二次语义审阅，构造源文/剧本指纹并调用现有export_translation校验。完整校验通过后原子rename editorial目录供生产读取；未解决error隔离在translation-worker，禁止交给TTS。
- Git业务提交1d32299已push/Windows pull；Windows59项测试全部通过。
- 第5集初稿已真实生成：36条，major script match=true；Connor/Carmilla源字幕疑点标error，3条日记旁白reader unknown。第一次运行在初稿阶段过早拒绝error，未到审阅；已修复允许初稿疑点进入第二轮、审阅仍有error就标pending不生产，后续文本独立继续。未新增MiniMax克隆/配音调用。
- 第5集复核现正Running：计划任务Codex-Carmilla-Translate，保存第一稿已复用，没有重做首轮。第6–32集后续任务Codex-Carmilla-Translate-Remaining已Running等待第5集审阅结束；若第5集文本有pending但复核正常结束，后续继续翻译，生产队列仍等已通过的第5集。CLI/校验异常则停，不重试盲重提。
- Windows产物output/translation-worker/episode-05/{draft-response.json,codex.private.log,codex-review.private.log}，后续reviewed-response.json；日志不得整段打印（包含项目原文），不要上传S3。output/drama-01/translation-progress.json记录当前集和pending_episodes；producer仍使用原voice-bank/锁/回执。
- 登录CLI到全流程转Windows已接入译稿生成，但不能称32集翻译完成或第5集生产已启动。下一步核验第5复核及后续任务；Connor等字幕疑点需实际原声核对，未知reader优先确定已有角色/声音，禁止随集新clone。当前4集成片可播放。

### 2026-10-10 Windows Codex CLI安装与登录等待

- 用户明确授权在Windows安装Codex CLI，用户自己登录。Windows原有Node v24.13.0，npm前缀C:/Users/melot/AppData/Roaming/npm，系统Windows11 LTSC。
- 已安装并验证codex-cli 0.162.1；入口C:/Users/melot/AppData/Roaming/npm/codex.cmd，login --help通过。使用官方@openai/codex包；Windows直下157MB原生包停滞，Mac从官方npm源下载，SHA512与官方dist.integrity一致，SCP后Windows SHA256一致；本机npm cache add后离线完成同版本安装。仅停止本次已核验的停滞npm安装进程，未动业务生产进程。
- 已通过Interactive计划任务Codex-Carmilla-Login在用户桌面Session1启动codex login；原生codex.exe PID25872核验Session1，localhost1455登录回调监听存在。用户待完成登录，不能称已认证或翻译已自动接入。计划任务无触发器，可在登录完后清理。
- 安装包临时副本Mac /tmp/codex-windows-0.162.1.tgz，Windows项目output/codex-windows-0.162.1.tgz（165053495bytes，忽略目录）；无认证值入交接/Git/S3。
- 后续用户登录后用codex login status核验，再接入Windows剧本翻译worker；保留现有Python生产队列独占付费克隆、回执与声音复用，避免Codex另开付费请求。

### 2026-10-10 审查问题修复完成（覆盖下方未修复记录）

- 用户授权修复3项审查问题。abfa948已push并Windows pull，55项unittest全通过。新增8项覆盖计划重启不变/原译稿变化拒绝、音色与速度变更拒绝缓存、合法旧缓存免付费复用、部分旧任务绑定、渲染时新译稿到达立即准备、准备与渲染互斥。
- build_episode_plan首次计划不可变；按当前译稿与参数核对，复用原参考片段，不随voice-bank新增角色改写。真实EP04重新准备后计划SHA完全不变。若真实输入变更，保留原计划并拒绝续跑，不提示以新目录绕过缓存。
- synthesize新增synthesis-input.json和结果input_fingerprint，绑定unit/project/voice_id及参数；旧缓存核对身份字段与attempt-0请求指纹后复用。不一致或缺身份依据停止，不自动重新付费。Windows真实EP01–04共86个已生成配音单元全部读回/哈希核验/复用成功，无新增付费API调用。
- production_queue用Popen监督渲染，期间每30秒扫描下一集新译稿；PreparationScheduler保留最多两路准备，成片仍逐集。准备阶段和渲染共用production.lock互斥，避免队列准备覆盖在用素材。
- 已核验队列stage waiting后重启Codex-Carmilla-queue，部署生效；当前EP04已完成，页面4/32，EP05等待已审稿。生产/发布私密配置不变，无密钥/素材入Git。
- 本次修复费用审查：不新增付费重试；改变音色/参数均拒绝混用；已完成音频可兼容读取。后续可用/review或codex review复审。

### 2026-10-10 代码审查结果（尚未修复）

- 主代理审查当前并发提交ea73df5..7eff531，未委派独立审核。结论：暂不放行无人值守断点恢复。业务代码未修改，Windows模拟复现无付费调用。
- P1：队列重启重跑build_episode_plan会按已更新voice-bank移除新角色segments_seconds，改变计划fingerprint；render_episode拒绝已有断点。Windows复现Father参考[[0,12]]变成{}后报Episode input changed。新建输出目录会放弃原TTS缓存，不建议以此绕过错误。需持久化不可变计划，并核验实际源稿变化。
- P2：synthesize复用result只校验音频文件hash，不校验当前voice_id；更正声音库后旧句仍返回旧音色，未完成句可能使用新音色。Windows复现请求new-voice返回old-voice。需绑定音色/文本/时码/合成参数指纹，变化应提示而非静默重合成。
- P2：production_queue在subprocess.run渲染期间不扫描新译稿，仅进入渲染前提交当前/下一集准备；配音期间到达的下一集译稿不会立即并发准备。需独立持续扫描或非阻塞监督。
- 既有47项测试通过不覆盖上述续跑计划变化、voice_id变更和运行中译稿到达；临时复现脚本Windows output/code-review-repro.py。建议优先修P1再修缓存身份与动态准备。

### 2026-10-10 并发、防重复克隆与持续队列

- 用户要求Windows并发，同时千万不能重复clone浪费。代码7802bcf已GitHub push / Windows pull；Windows47项测试全部通过，包含真实独立进程争抢同角色仅一次模拟付费调用、超时跨集禁重提、旧回执恢复和准备阶段不调用配音。测试不调用付费接口。
- process_lock.py使用Windows msvcrt跨进程锁；全剧voice-bank串行创建新增声音，克隆回执集中voice-clone-receipts，先恢复旧episode回执再决定创建。歧义pending停止核查；同集production.lock和每次付费提交锁防并发重提。旧角色voice_id继续复用，不重新克隆。
- production_queue.py两路当前/下一集素材/已审稿准备，单集三路TTS，按集数合成。Windows计划任务Codex-Carmilla-queue从EP04运行，Codex-Carmilla-publish独立更新；两项均已核验Running，旧EP03任务已完成。缺已审稿时等待，不自动生成译文；异常停队列而不自动重试付费任务。
- EP03已完成并上传，当前页面3/32；新增Narrator_EP03已有，仍待听审。EP04的16条已审稿已传Windows、导出/素材检查/计划生成成功，新Father为必要首次角色，后续复用。
- 未知reader不再按集自动新建旁白：build_episode_plan在新unknown时拒绝克隆，需先确定可复用身份；Camila/Camilla/Kamila统一production_voice Carmilla。EP05以后译稿尚未完成，不能称整季自动完成。
- 费用边界：防重避免误提交；时长调整每句最多3次合成本来仍有费用，回执记录每次任务，不与意外重复克隆混淆。计划任务无开机触发/自动失败重试，不承诺机器重启后无人值守恢复。
- 代码审查入口/review或codex review；已自查密钥和素材不入Git、无付费API自动重试。

### 2026-10-10 当前核验与恢复（优先于下方历史）

- 全32集原视频/BGM/SFX均已下载至Windows并校验；第1、2集合成草稿已发布，视频流保持一致。巴葡母语听审仍未完成；时长质量提示分别2条、5条。
- HTML地址：https://starlitshorts.s3.amazonaws.com/aigc/drama/dubbing-video/carmilla-20261009/index.html 。仅发布HTML与成片；进度嵌入HTML，每30秒刷新、每10分钟记历史。
- 昨晚EP02于上海时间19:57完成，但未接上EP03；尚无整季自动编排，不能宣称无人值守连续运行。页面最后本地更新时间21:57，末尾两次SSLError；今次配音/发布进程均未运行，退出原因尚未证实，Windows最近启动时间10月8日。
- 实际分工：Codex在Mac会话中基于匹配剧本+字幕编写译稿；Windows导出校验、下载、参考音频准备、调用MiniMax、音频对齐混音、无损复制视频流及S3上传。MiniMax语音运算在云端。旧“全业务Windows”措辞需按此澄清。
- 已恢复EP03：24条已导出，计划已生成，通过SSH直接Start-Process的两个子进程未能在断开后存活，改为Windows计划任务Codex-Carmilla-dub和Codex-Carmilla-publish（当前登录用户Interactive，已启动），不依赖SSH会话。日志output/drama-01/episode-03/runner.log和runner.err.log；发布日志output/dashboard/publisher-recovery.log。必须核验计划任务状态和日志，不能只依据启动成功。
- EP03背景轨比视频短1.479秒，同步仍待核验，不能将填充尾部当同步验证。EP04本地editorial草稿待传输/导出；EP05以后未完成翻译。
- 后续继续逐集翻译审核与生产，并补全持久化编排/停机状态显示。付费任务回执与pending防重机制必须保留，不盲重试克隆/生成。代码分支codex/dubbing-video-win-smoke，最新业务提交ea73df5。
- 认证仅存在本机私密配置，不记录/打印/提交。Windows生产和发布配置需保留至任务结束。

- 日期：2026-10-09。
- 目标：Mac 编写并推送 GitHub，Windows 拉取代码并执行；业务运行端固定为 Windows。
- 最新用户长期要求：后续所有剧/集翻译都先取得并核对匹配剧本，结合人物关系、场景与表演意图优化。无匹配剧本时继续查找，只有用户明确同意才以字幕单独翻译。对白/时间码仍以本次成片字幕为准。
- 项目新建，原目录无 CLAUDE.md 和历史交接文件；沿用上级工作区规则。
- 测试代码：`smoke_test.py`，仅使用 Python 标准库。
- GitHub：`husw725/skills` 的 `codex/dubbing-video-win-smoke` 分支，仅提交本项目文件。
- Windows：SSH 别名 `win`，独立检出至 `E:\workspace\dubbing-video-smoke`。
- 首次验证通过：提交 `5929b76` 经 GitHub 克隆到 Windows，2026-10-09 14:47（上海时间）运行返回 `status: ok`，主机 `husw`、用户 `melot`、Python `3.13.5`，退出码 0。
- 产物：`E:\workspace\dubbing-video-smoke\dubbing-video\output\smoke-result.json`；已写入后读取核验。
- 此记录随后推送并在 Windows 用 `git pull --ff-only` 更新、重跑脚本，以核验增量同步。
- 上级工作区存在其他项目的未提交修改；通过独立 Git worktree 提交本项目，保留原工作树分支与修改。
- 增量同步验证通过：Windows `git pull --ff-only` 更新至 `f940578`，再次运行返回 `status: ok`，退出码 0，工作树干净。
- 新任务（2026-10-09）：先规划与分析 20 部剧、每部平均 50 分钟，共 1,000 分钟，从原语言对白翻译/配音为巴西葡语，原画面保持不变，评估算力、费用和时间；本轮尚未授权全量生成。
- 最新用户确认：已有“背景音，声音，无志视频”三项。当前按背景音乐/音效轨、对白人声轨、无字视频理解，主方案跳过抽轨与分离；实施前核验对白是否纯净、三项是否同版本同起点同长度，以及背景轨是否包含音效。
- 环境核验：i9-14900KF、约 128 GiB 内存、RTX 4090 D 49140 MiB 显存；本次检查显存空闲仅约 4 GiB，FFmpeg 可用。未停止任何现有服务。
- 调研口径：官方价格与规划估算分开；尚无本任务素材性能实测，不承诺整批耗时。巴葡目标应明确为 `pt-BR`。
- MiniMax 备选调研：国内官方按量文档 `https://platform.minimax.cn/docs/guides/pricing-paygo.md` 已通过原始 Markdown 核验，Speech 2.8 HD 3.50 元/万输入字符、Turbo 2.00 元/万；ASR 2.50 元/小时；快速音色复刻 9.90 元/音色（首次正式合成收费，试听另计）。国际站美元价格不同，不跨站换算。
- 在 40万–80万目标计费字符假设下，HD 纯 TTS 140–280 元，增加 30% 生成用量为 182–364 元；Turbo 对应 80–160 / 104–208 元。源轨 1,000 分钟全量 ASR 基础约 41.67 元；翻译、克隆、人工另计。
- MiniMax API 的语言增强参数是 `Portuguese`，未见独立 `pt-BR` 参数；巴葡口音需选音色并实测听审。主路线仍为识别、翻译适配、角色逐句 TTS、时长对齐、混音、原视频流复制；不能将 TTS 价格当一站式全流程报价。
- 用户追问原句情绪能否跨语言保留。官方 voice_clone 的 `clone_prompt` 明确承诺增强音色相似度与稳定性，TTS `emotion` 为合成情绪控制；未验证逐句源音频到目标语言的表演自动迁移。方案需区分角色音色克隆、原句情绪/韵律分析、目标 TTS 情绪控制和样片听审，不能将其合并为已验证的原生一键功能。
- 已实现内容翻译（2026-10-09）：`translate.py`，MiniMax-M2.7 文本 API，支持 JSON/SRT。先通读全剧、生成并统一角色/称呼/术语表，再分批翻译；原台词时间窗口不变。默认本地化为自然的巴西姓名；可配置保留原名、手工锁定人名。用户尚未回答人名模式问题，当前默认值已明确告知。
- 一致性机制：全剧剧情记录、前后原文、前批译文、保护人名/术语占位符；翻译后另一次模型调用审查含义与关系，发现问题尝试修订，未解决句子标为待复核。
- 时长机制：候选措辞按巴葡音节启发式估时，默认目标差 ±20%，最多两轮修订；数字/敬称缩写标为估时不确定。所有 `tts_timing_verified=false`，必须后续用真实 TTS 音频测时，不承诺文本估时等于说话时长。
- 输出：角色表、完整译文 JSON、待复核清单、保留时码的 SRT 草稿；多集分开导出。逐批断点持久化，输入/角色表/参数变化禁止复用旧断点。
- 验证：实现提交 `dd7f09b` 已 push GitHub，Windows pull 后 21 项 unittest 全通过（使用模拟 API），4句/2集示例 dry-run 成功，原 smoke_test 回归通过；没有在 Mac 执行业务代码。未配置密钥时明确报错且不产生假译文。
- 实测边界：Windows 进程未配置 `MINIMAX_API_KEY`，且尚无用户真实台词/字幕路径，未调用付费翻译 API，未验证真实巴葡质量与配音时长。示例姓名和台词完全虚构。
- 后续：提供实际输入路径并在 Windows 配置 API Key 后，先生成/检查角色表，再跑代表性翻译及 TTS 时长校准；不把模型语义复核当人工巴葡验收。代码审查使用 `codex review` 或 `/review`。
- 首部素材（2026-10-09）：用户提供百度网盘分享，明确只下载第一集相关素材并跑通流程。分享目录为《Carmilla》，裸片目录含 32 集；另一目录为“05纯 BGM+纯SFX分离轨”，下有 SFX、纯 BGM 两个子目录。禁止误下整季。
- 已在 Windows 网页确认 EP01 裸片 `Carmilla_EP01_纯净裸片版.mp4`（页面约 81.6 MB）及 `Carmilla_Ep01_SFX.wav`（约 11.3 MB）；第一集 BGM 文件名与大小尚待核验。暂未发现独立对白目录，需下载后用 FFprobe 核验裸片中的音轨，不能直接假定存在纯对白。
- 下载目标目录已建：`E:\workspace\dubbing-video-smoke\dubbing-video\input\drama-01\episode-01`。截至本次核验未有文件落盘；百度分享下载触发登录。Windows `agent-browser` 会话 `dubbing-baidu` 保持在扫码登录页，已向用户展示二维码并请求完成登录；二维码及登录状态不提交 Git。
- 同时核验 Windows 进程和用户环境均未配置 `MINIMAX_API_KEY`；已询问现有配置位置或请用户在 Windows 配置环境变量。不得把模拟翻译测试描述为真实配音流程已跑通。
- 下一步：登录后明确仅选 EP01，下载裸片/BGM/SFX，逐项校验文件与轨道时间基准，确认对白来源；然后接入真实识别、巴葡翻译、角色 TTS 测时、混音及原视频流复制，记录实际费用与耗时。
- 登录窗口修正：原自动化浏览器为后台会话，用户在 Windows 桌面不可见。现通过一次性 Interactive 任务启动 Chrome，已核验进程在用户桌面会话 SessionId=1；启动任务随即删除。可见浏览器使用独立 `baidu-browser-profile`，仅本机 CDP 端口 9333，自动化连接会话改为 `dubbing-baidu-visible`。用户应在此窗口登录；旧二维码属于后台会话，不应继续使用。
- 下载更新：用户点击网页下载后启动已登录的官方 Windows 百度网盘 App（`E:\soft\baidunetdisk\baidunetdisk.exe`），无需网页扫码。通过用户桌面会话中的窗口操作仅下载 EP01 的裸片/BGM/SFX，各选择对话框核验单文件名，未下载整季。下载默认目录 `C:\Users\melot\Desktop\res\pics`，完成后复制到上述项目输入目录，保留下载原文件。
- 三文件已完成：裸片 85,531,919 字节；`Carmilla_Ep01_BGM.wav` 和 `Carmilla_Ep01_SFX.wav` 各 11,821,100 字节。实际客户端下载速率约 114 KB/s；此速度不代表配音处理速度。
- 已新增 `prepare_media.py`，提交 `736b1db` 经 Mac push / Windows pull 执行成功；完整解码三素材、记录 SHA-256、提取视频第一音轨为 PCM 及 16 kHz 单声道 ASR WAV。输出目录 `output\drama-01\episode-01\media`，包括 manifest 和两份音频。视频 H.264 1080×1920 / 30 fps，含 AAC 44.1 kHz 双声道；视频容器 67.082449 秒，BGM/SFX 均 67.012789 秒，无 >150 ms 时长差告警。对白纯净度与背景起点同步未听审确认。
- 原始素材下载及识别前准备完成；真实 ASR、翻译、TTS 与混音尚未运行。MiniMax 配置问题仍待用户回复，不能报告首集全流程已完成。
- CLI 事实已独立审核放行：`https://github.com/qjfoidnh/BaiduPCS-Go` 为第三方 CLI，支持 Windows、下载/断点续传及带提取码分享转存。桌面 App 登录不等于 CLI 登录；未安装或实测本次分享的 CLI 下载，不声称官方或提速。
- 最新范围：用户说明配音能力将由后续生产 MCP 提供，目前先做字幕整理和翻译；本轮不生成语音。提供了第二个百度分享“06SRT字幕”，用户重新登录网盘。通过已登录 Windows 浏览器的“普通下载”取下全 32 集字幕 ZIP，用于全剧一致性；未增下其他集的视频或音轨。
- 字幕已在 Windows 解包至 `input\drama-01\subtitles\original`，保留源 ZIP 和原文件。新增 `prepare_subtitles.py` 整理 32 集 / 643 条；EP01 `.str`、EP05 `.st` 为 SRT 扩展名误写；9 集（3/5/6/10/15/20/21/27/30）条目顺序错乱，规范副本及合并 JSON 按原时码排序，保留原编号和时间值，不移动台词。
- 全剧英语字幕已通读；用户未回答可选翻译后端问题，按已告知默认由当前 Codex 助手直接完成首集译文，不依赖 MiniMax Key，不改变既有 MiniMax 翻译后端代码。全剧姓名/术语表已建立：Laura 保留；Carmilla/Camilla/Kamila → Camila；历史本名 Mircalla 保留并记录同一角色身份；Irina 保留，Elisabeth → Elisabete，Miller 姓氏保留。Connor 等疑似识别错误不编造角色。
- 实际完成首集 24 条巴葡译文，输出保留时码的 SRT、原译文 CSV、JSON 和复核清单；文字音节估时 10 条超出 ±20%，未声明真实音频时长匹配。新增 `export_translation.py` 依据源文本/时码指纹、台词 ID 和锁定名称核验，导出 21 个拟配音单元覆盖全部 24 条；拟合并 4–5、8–9、23–24 的连续分句，所有分组、角色及 TTS 时长仍待原音频核验。
- 代码提交 `102e547` 已 Mac push / Windows pull；Windows 26 项 unittest（新增 5 项 + 原 21 项）通过，真实 643 条字幕整理和 24 条译文导出成功，保存数据重新读取核验通过。未调用付费 API，未做巴葡母语听审；后续集译文尚未生成，不能称全剧翻译已完成。
- Windows 产物：`output\drama-01\episode-01\translation`；准备包 `output\drama-01\carmilla-episode01-ptBR-preparation.zip` 含 8 文件，ZIP CRC 核验通过。复制供用户查看至本项目 `output/carmilla-episode01-ptBR-preparation.zip`。真实字幕/译文仅放 input/output 忽略目录及 Windows，不提交公开 GitHub；全剧角色表草稿在 `output\drama-01\subtitles\carmilla-series-bible.json`。
- 后续：首集文本可审阅；接入生产 MCP 时确认角色、实际语音窗口、分句连读、音色及实测时长。源字幕已有截断/识别疑点（EP5 Connor、EP18 lava、EP27 两个截断句、EP29 years），其他集翻译前需核听疑点。代码审查入口 `/review` 或 `codex review`。

- 2026-10-09 MCP最新：用户更新认证，已更新本机原认证配置，不记录敏感值。mflix和mflix-review均远端initialize成功；review tools/list、getProjects、getProjectReviewMaterials成功。Carmilla项目ID59。
- Windows已下载并校验 `input/drama-01/screenplay/Carmilla_Complete_32_Episodes_FINAL.v1.docx`（asset319，95108bytes，32集）及 `Carmilla_Revised_Episodes_1-3.v2.pdf`（asset333，103561bytes，8页），DOCX CRC/PDF解析通过。同目录download-manifest.json保存SHA256、ID/版本，无认证/下载URL；另有txt和版本说明。Mac审阅副本在output/carmilla-screenplay。
- 首集字幕主要对白与完整稿吻合；修订稿开场及对白有变化，留作对照。两份平台状态均待审核，不能视为审批定稿。剩余31集未逐集核对，未修改现有翻译，无平台上传、评论或审核操作。

- 2026-10-09 用户授权 MiniMax MCP 小样实测：Windows 从首集 source-audio.wav 截取 Laura 候选声段0.8–8.4/25.6–34.8秒，拼成16.8秒、1,481,838bytes单声道WAV（未人工听审说话人）。通过mflix createFilePresignedUrl上传成功，再uploadMiniMaxVoice创建 `studio_carmilla_laura_test_80bf6efd4dce`，克隆调用8.35秒。
- 使用已保存音色调用generateAudio：speech-2.8-hd / Portuguese / fearful / speed1.0，测试文本“Sete dias. É só o que me resta.”；任务36533状态2成功。下载WAV232,994bytes，PCM16bit/32kHz/mono，3.622344秒；完整解码及Mac副本SHA256通过。首两字幕语音窗口合计3.1秒、含停顿跨幅7.2秒，本次未做时码对齐。
- 小样路径 Windows `output/drama-01/episode-01/minimax-smoke`；Mac `output/minimax-smoke`有生成WAV、参考WAV、test-report.json。临时认证文件两端已删除；服务返回文件仅留忽略目录。实测费用接口未返回；不能把接口支持fearful等同原句情绪自动迁移，音色相似度、巴西口音和表达效果均待试听。只做一次克隆/一次合成，无全剧生成。

- 2026-10-09 剧本优化完成首集v2：24条逐句对照asset319/v1；7条调整措辞/停顿。Laura恐惧追踪、母亲虚弱临终、Camila痛苦悔意有逐句剧本依据。17条角色由剧本支持；7条说明原稿标SUPERIMPOSE，实际朗读者未知，已标待核听。全24条原文/时间码保留，人名术语映射不变；12条文本估时超出±20%，未重新合成或声称对齐成功。
- 持久化流程：新增AGENTS.md规则和screenplay_context.py；translate.py准备角色表、翻译、审核均带匹配剧本上下文；默认要求--screenplay-context。上下文包含SHA256/版本/逐cue源文和角色证据，匹配状态或源文变化拒绝导入，指纹变化拒绝旧断点/未重审人工译稿；禁止跨角色合并拟配音单元。真实剧本、译文仍仅留忽略目录，不公开提交。
- 提交d8bc2fe已push/Windows pull；32项测试通过（新增6项覆盖版本不匹配、遗漏/陈旧cue、模型上下文、旧断点拒绝、导出指纹、跨角色分组）。真实首集导出、字幕时码、人名一致性、剧本SHA256及11文件ZIP CRC全部核验通过；旧译文仍保留可读。未调用付费翻译或新增TTS。
- 新输出 Windows output/drama-01/episode-01/translation-v2；准备包output/drama-01/carmilla-episode01-ptBR-script-v2.zip，Mac同名output副本。当前仅首集完成剧本优化，剩余31集译文未生成；后续按新流程逐集核对剧本，再翻译及实测配音时长。代码审查用/review或codex review。
