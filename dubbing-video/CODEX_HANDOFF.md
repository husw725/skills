# Codex 接手：dubbing-video

## 当前接力记录

### 2026-10-16 等三集反馈期间，全剧返修前只读初筛已完成

- 用户认可先做全剧检查，等待EP02 v3/EP07 v2/EP29 v2反馈后再决定修复。此次只排查Carmilla原v1，未改字幕/译稿/音频/视频/Review或队列，0TTS/clone/付费调用；第二部继续暂停正式生产。
- audit_series_readiness.py已Mac push/Windows pull，业务在Windows执行；固定32集project59，读原plan/render-report/source/context/锁定bible，输入SHA先采后读、结束复核；输出限定忽略output/新目录。032d58c已同步，5测试两端通过，实际旧32集数据完整读取通过。
- 输入涵盖643条原字幕、645条编辑source行、642个生产意群。EP01有合法多cue合并，EP32两条双人原cue派生四行，原28cue/编辑30行；按source_cue_windows/拼合源文/剧本annotations及原cue拆分来源和窗口连续性核对，不能把合并/拆分误报。独立审查指出初版单cue假设后已修正再运行；当前计划/报告与源文本/时码/注释无P1绑定差异命中，不等于原转写或旧剧本版本无误。
- 初筛276候选行包括40条历史评论，自动规则涉及200个意群（未经人工处置的原始口径，排除下述单条假阳性后199个待核意群，不是200个确认缺陷）。163组最后合成请求speed>1.25，其中22组另有atempo>1.25，后者为前者子集不能相加为185句错。27处同角色连续碎句分组候选，23组证据speaker unknown，锁定术语缺失规则无命中，未发现报告拟合音频跨下一组起点。以上参数及规则不能替代听审。
- 唯一negation候选：EP07 e07-8 You knew my mother, didn't you? → Você conhecia minha mãe, né?，人工确认是自然反问，不是漏掉主句否定；已在manual-triage.private.json记录false_positive_text_screen，原audit快照不覆写。不是修译稿或新音频验收。
- 只读结果两端output/series-readiness-20261016：audit.json、逐集README.md、repair-candidates.csv、bilingual-corpus.private.json；人工说明analyst-notes.md和manual-triage.private.json另存并已同步Windows，明确规则局限及下一步。详细对白、script evidence、历史comments不进Git。历史40条不同commentId/assetId分别保留，未把旧评论当新版本通过。
- 优先队列：EP13英语残留/EP31杂音先定位分轨，不能猜因删正确巴葡；EP29 e29-8原字幕How many years./Quantos anos?与剧本minions差异、证据读者unknown，原音频暂留；EP11 Tentei transferi-la / há quinze anos连续意群及发音复核。没有自动修复/重新clone/全季重配。
- 等待Review148当前2557/v3、2558/v2、2559/v2专业反馈，以版本+时间+引用短语定位，确认有效方法后按意群小样验证再扩展。未新增未来自动任务或监控，不把无评论当通过；母语/情绪/音色/混音待听审。audit_review_feedback独立实际报告复核修正计数表头后放行：README时长列是可重叠规则记录，163/22不能相加认定185句错误；原始200与人工处置后199分别标清。代码审查codex review或/review。

### 2026-10-16 扩展代表集专业复审（EP07/29混合v2，三集与评审文档已发布）

- 用户追加授权选两集，按当前经验重新处理、让专业人员尽量暴露问题并用于优化。选Carmilla EP07（短惊呼/长问句/tola/冷声旁白）与EP29（四角色/男性警报/冷讽威胁/节奏）。可选路线问题合理等待未答后已说明按推荐混合方案执行；不是纯Cartesia、不是全季重跑。第二部仍仅前置准备、不启动生产。
- 原reviewed screenplay-context与字幕逐条核对，原计划的source text/start/end与source.json精确一致；当前剧本上下文与原plan annotations一致。使用用户final.html同SHA作为表演与版本参考；EP29实际对应33集分镜表EP-30。原译文字词与字幕时码未改，仅同角色意群合并和合成标点/大小写调整。保留否定、所有人、今夜/明日等信息。
- EP07 17cue→13group：12Cartesia+1MiniMax（Laura CAMILA短惊呼fearful），13新TTS；EP29 19cue→15group：11Cartesia+3MiniMax（Father两组fearful、Irina冷威胁calm）+1原音频，14新TTS。27新任务37884–37910成功，0新增clone，复用现有两套voice-bank。Cartesia pt-BR/accent支持元数据及葡语情绪无已验证保证，fearful/calm不等于表演合格。
- EP29 e29-8原字幕How many years./Quantos anos?与剧本Her minions不一致；source reader证据保持unknown，生产暂配Carmilla单独保留。该旧fitted SHA相同，不重复付费或补写剧本；评审明确要求听核原字幕/说话人，不能宣称已修复。
- Windows output/diagnostic-review-config.json，输出output/drama-01/episode-07/diagnostic-v2和episode-29/diagnostic-v2；diagnostic_review_episodes.py固定范围/路径、完整source覆盖与text/time校验、上下文版本/资产/SRT/voice-bank/请求指纹、paid receipt/pending与独立锁；max2并发两集。合成文本只允许原译文字词一致的标点/大小写调整，不跨角色，atempo>1.25停止而非截断/盲重生成。
- 成片：EP07 75.839秒、SHA07ecb43ccdf4cca23a8657da479ff7ddcb996051a918dfae19fa64628a4decc1，maxatempo1.109；EP29 91.753秒、SHA75676c9734788c31bd08072e298c115e22664f3b0cea33d64d8f8882154a49a7，maxatempo1.219。完整解码/视频流一致通过，原BGM/SFX保留、不混source_audio。利用部分句后空隙，需音画节奏听审。两集native/speaker/performance均false。
- 代码8239f0b/efc05f0/7dbb0a4/3df7c73已Mac push、Windows pull，18测试Mac/Windows通过（含发布重复执行只一次mutation、旧链保留和拒绝另一版本/变更SHA）。共享规则独立audit_review_feedback源计划/报告/代码安全审查放行诊断候选，母语验收待完成。
- Review发布：限定148 FINAL_CUT原2359(EP07)/2381(EP29)追加v2；S3仅成片、SHA文件名/远端完整GET SHA读回；发布锁+request fingerprint+safe_submit防重，回读旧v1/新v2链。EP07新2558/v2、EP29新2559/v2均完成，旧2359/v1、2381/v1保留，EP02链2354/v1→2478/v2→2557/v3保持。Review148当前三视频均待审status8。有限Windows任务Codex-Carmilla-Diagnostic-EP07-29和Codex-Carmilla-Diagnostic-Publish均完成；无全季队列或定时重试。第29集初次完整GET网络ResponseStreamingError，仅停止本轮存储读worker32360，改5MiB Range逐段3次有界重试、成功整段才更新SHA，全部字节顺序校验通过；未重合成/克隆，未重复Review mutation。
- diagnostic_review_brief.py已生成并上传Review148 DOCUMENT2560（待审8）评审说明：三集具体版本/ID、双语意群表、定位时间/已知疑点、译文/发音/口音/表演/音色/同步/混音分别反馈；请求整集听审、明确通过项，没评论不等于验收。公开DOCX不含voice_id/生成请求；忽略的feedback-learning-matrix.private.json记录模型/音色/参数/时间/任务与输入指纹用于后续定位。版本/时间/引用短语定位，已证实问题与假设分开，小样复验，不自动反复clone或全季重生成。
- 回执Windows output/review-publication/148/Carmilla/{diagnostic-ep07-v2,diagnostic-ep29-v2,diagnostic-brief-20261016}；Mac只读副本output/cartesia-v3-repair。独立Review API读回上述3视频当前版本与DOCUMENT2560、旧链均一致。实际DOCX42246B、本地/远端SHA一致，3表18/14/16行对应45组61cue，未公开voice_id/合成请求；输入指纹绑定原plan/report/publication避免旧DOCX复用。后续按新asset/版本读取专业反馈，不能把老评论混成新验收。无新增评审意见时不声称学会或解决口音问题。audit_review_feedback最终复核三条版本链、实际DOCX/矩阵与回执后技术交付放行；Windows生成/发布runner-exit均0。真实素材/译稿/回执/认证仅忽略input/output，不入Git；代码审查codex review或/review。

### 2026-10-16 基于v2反馈定点重生成（v3混合模型候选，已发布）

- 用户授权依据反馈优化并重新生成；继承代表集Review工作流，处理Carmilla EP02两短呼喊，不全季重跑。当前MCP仍只有Cartesia language/speed，无AddAccents或巴葡emotion控制；官方emotion文档只支持英语。因此未盲重跑同Cartesia请求，定点使用已有MiniMax Laura音色，其他15个Cartesia v2意群保留。用户追问是否混合，已明确说明方案与音色衔接风险；未收到取消/纯Cartesia要求。
- 原reviewed screenplay上下文及用户final.html EP02一致支持Laura：e02-16绝望地不要、e02-18被咬尖叫不；两评论无时间戳，仍只作为定位候选，不宣称一一对应。原25字幕、译文/时码与剧本上下文均未改。
- 合成层实验：016使用官方(gasps)+半角括号IPA nɐ̃w̃，018仅IPA，MiniMax speech-2.8-hd/Portuguese/fearful/speed1.0；正确原字幕Não.../NÃO!保留，IPA不写回译文。原英语Laura MiniMax clone直接复用，0新clone；2个新任务37882/37883均成功，不自动重试。官方支持IPA/2.8 gasps但未验证鼻化解析及尖叫效果，不能声明发音或恐惧表演已解决。
- Windows inputconfig output/feedback-v3-config.json；输出 output/drama-01/episode-02/feedback-v3。新增repair_episode_feedback.py固定EP02/59/Review148-old2478、两unit/Laura、独立输出路径；bind base报告SHA、原计划/上下文/字幕、旧音色、资产SHA、原对白轨SHA、15段fittedSHA和逐请求指纹，pending锁防重复付费。
- 实际016自然0.61秒，018自然1.66秒，两段atempo约1.0；018实际音频延至约56.655秒，字幕仍55–55.933秒，利用到下一说话人前的候选空隙，需音画节奏听审。其余15组fitted SHA逐一相同；重建对白patch外PCM逐样本一致，原视频流SHA一致且完整解码通过。
- 最终候选Carmilla_EP02_pt-BR_feedback_v3.mp4，SHA256 0b1892f4ccb3aede2ee4f11d862ccb6f22dac514b4e6d7ce69d4424ef8f81e3e。native_ptBR_listening_reviewed/scream_verified/phonetic_control_verified仍false，报告明确Cartesia v2+两MiniMax反馈补丁，不把混合版本叫纯Cartesia。
- 新业务代码330b066已Mac push/Windows pull；10项边界/防重测试Mac和Windows通过，原v2数据读取核验通过。audit_provider_recommendations官方文档审核放行小样实验，audit_review_feedback独立代码/混合报告技术放行，母语验收待完成。新增review_feedback_v3.py安全审查放行，仅Review148 EP02旧2478追加v3，保留2354/v1与2478/v2，读回新ID和SHA后才报告完成。不发comment/audit，不改其他集。
- 已发布完成：Review148 EP02新asset2557/version3，保留2354/v1与2478/v2。S3 multipart上传单一成片并GET SHA读回；publication-result.json及history-after.private.json在output/review-publication/148/Carmilla/feedback-ep02-v3。公开链接 https://starlitshorts.s3.amazonaws.com/aigc/drama/dubbing-video/carmilla-20261009/review-revisions/Carmilla_EP02_pt-BR_feedback_v3-0b1892f4ccb3.mp4 。真实音频/译稿/回执只放忽略input/output，密钥不入Git。代码审查codex review或/review。

### 2026-10-16 已读取Cartesia EP02 v2专业反馈（仅分析）

- 独立audit_review_feedback核对3份原始快照放行：版本/2条评论计数、无时间戳、发音表演与词义分离、旧anos未获验收结论均准确。

- 用户让查看新一集反馈。只读Review148/EP02版本链：2354/v1与2478/v2，均status8；逐版本评论pageSize100，v1有1条7326（anos欧葡），v2有2条不同ID7488、7489，均无replies/音画时间戳，分别保留，不混版本。原始快照及feedback-analysis.json在output/review-feedback/2026-10-16。
- 7488：这里的não语气很怪，应该是恐惧的尖叫。7489：这里的não是用英语读的，不对，而且语气应该是恐惧的尖叫。多标签2条情绪、1条发音，共3分类，不是3评论；未明确指出词义翻译错误。
- 优先定位候选是Laura e02-16 Não... 49.433–50.233、e02-18 NÃO! 55.000–55.933秒。评论无音画时间戳，其他句也有não，不能将两个commentId直接一一绑定两个cue。未听审，不宣称已确定具体成因。
- 当时render-report证明两音色accent_support unknown、emotion_control_applied false，是已知验证缺口而非错误根因的听审结论。Quinze anos本次未被评论不等于已通过。建议先定位两条，再核对Laura巴葡口音支持和可用恐惧表演控制，定点小样验收，不重复clone或全剧重生成。
- 本轮未生成/克隆/修改译文/上传/发评论/审核，第二部仍不启动；等待后续实施指示或更具体定位证据。

### 2026-10-14 Cartesia代表集试制完成，Review EP02 v2已上传

- 最新明确授权：测试MCP新克隆平台，做代表性一集并上传Review v2供专业复审。选第一部Carmilla EP02（评审7326指出Quinze anos欧葡发音），不恢复第二部或全季生成。原25条剧本优化译文、原字幕文本/时码保持；同角色连续分句审核为17个合成意群。
- 实时MCP核验新增uploadVoice(platform minimax/cartesia)，generateAudio新增sonic-3.6和language地区字段。使用Cartesia sonic-3.6、language pt-BR；两个角色Laura/Carmilla复用既有源参考音频，各新增一次Cartesia克隆，独立全剧bank保存。旧MiniMax声音/回执/成片不改。新clone返回voiceId但language/description为空、没有accents信息，不能认定已添加巴西口音。当前MCP未暴露AddAccents；英语原声clone可能地区回退，需要母语听审。
- Windows输入config output/cartesia-pilot-config.json；新声音及不可重复提交回执 output/drama-01/cartesia-pilot-voices；单集 output/drama-01/episode-02/cartesia-v2-pilot。clone/reference/request/input指纹、全局bank锁、单集锁、每次receipt锁/pending保证不自动重复付费。克隆与生成均一次提交，歧义停止核查。
- 成功2次新平台clone、18个生成任务（1个Quinze anos小样+17个意群，task37816–37833），全部状态2。费用金额服务未返回，不声称免费。Cartesia巴葡情绪参数不受已验证支持，本次不传MiniMax emotion；报告emotion_control_applied=false，剧本表演意图仅作听审依据。
- 首次后处理发现4组过度压缩；只复用已有18个任务重新拟合/混音，没有新增付费调用。e02-2、e02-3、e02-6/7、e02-16分别借后方对白空隙0.277/0.307/1.190/1.410秒，不跨下一组起点，原字幕不改。空隙未经听审不能称静音；4组音画节奏仍待审。最终高压缩>1.25告警0，最大atempo1.238；原首次报告另存render-report-before-gap-adjustment.json，不作为上传版本。
- Windows最终Carmilla_EP02_pt-BR_Cartesia_v2.mp4：89871340字节，82.175秒，SHA256 86ee551ee2458acceaa2abe8cd72a404dce47b5fcb6e2f01bf007cd07d4f4591。完整解码通过，复制原video payload SHA一致；仅新对白+BGM/SFX，未混入source_audio。native_ptBR_listening_reviewed/speaker_audio_verified均false，不能宣布解决专业反馈。
- Windows review_cartesia_pilot.py通过Review预签名上传该单一成片、GET SHA读回，然后updateReviewMaterialVersion至项目148 PT Transalte/Carmilla EP02 FINAL_CUT；旧2354/version1保留，新2478/version2、待审核status8。名称Carmilla | EP.02 | pt-BR，tags含Carmilla/pt-BR/Cartesia；note记录候选口音、无情绪参数、4组gap及复审重点。没有audit/comment，也没改其他31集或源项目59素材。
- 公开成片链接：https://starlitshorts.s3.amazonaws.com/aigc/uploads/mcp/review/2026-10-14_8e757a83-60cf-44dc-9410-2c006fe96497.mp4 。发布回执/读前读后历史 output/review-publication/148/Carmilla/cartesia-ep02-v2，Mac只读核验副本output/provider-v2-test；两端API回读确认新v2与原v1链一致。
- 代码分支codex/cartesia-episode-v2，业务代码0c1f360已Mac push/Windows pull，6项付费防重/指纹/跨角色/路径边界测试两端通过；共享规则要求的audit_provider_recommendations能力边界与audit_review_feedback代码/上传/最终JSON独立复核放行，母语验收待完成。后续代码审查codex review或/review。
- Windows有限任务Codex-Carmilla-Cartesia-EP02-Pilot已完成；未启动全季队列。GitHub家中直连波动时仅临时通过SSH win的本机SOCKS网络转发完成Mac git push，不搬认证或绕审批；结束关闭转发。真实素材/译文/回执/认证仍仅忽略input/output，不入Git。
- 下一步等待本v2专业Review反馈；先明确评论对应的新asset2478或历史2354，不能把旧反馈混为v2。需要原生巴葡accent元数据/控制时完善MCP，不擅自重复克隆或全剧重生成。

### 2026-10-13 MiniMax预置音色来源澄清

- 用户问直接选的音色来源及MiniMax默认可选音色。本轮重新打开官方SystemVoiceIDList与GetVoice文档，确认官方system预置葡语音色存在，例如Portuguese_SentimentalLady、Portuguese_ConfidentWoman、Portuguese_Deep-VoicedGentleman、Portuguese_AngryMan。官方TTS按voice_id使用，无需另clone；我们的网关接受voiceId，但上述系统声音通过本网关尚未实测，不声称已成功。
- 预置来源是厂商提供声音库，不从本剧演员提取，也不能推断训练来源。官方Language字段只Portuguese，不是已验证巴西母语认证；先试听确认口音。无付费调用/新增克隆/生成。
- 官方链接platform.minimax.io/docs/faq/system-voice-id、/api-reference/voice-management-get。保留第二部生产等待状态。

### 2026-10-13 当前直接生成能力核验（未生成）

- 用户问现在有无直接生成巴葡办法。Mac用已有私密认证只读initialize/tools-list核验生产MCP可连接；generateAudio目前仅Sonilo和MiniMax speech-2.8-hd，支持指定保存voiceId/text/Portuguese，uploadMiniMaxVoice仍可用，未见ElevenLabs生成接口。不因官网支持推定现有MCP已接通。
- 可通过当前MiniMax接口生成巴葡译文的候选音频；需要先找到并母语听审验证巴西音色，不能承诺现已掌握巴葡验收通过voice。ElevenLabs路径目前需接入接口/可用认证和voice，不能称已可直接调用。未调用生成/克隆或上传，未恢复第二部正式翻译/生产。

### 2026-10-13 巴葡母语音色替代原演员克隆（仅咨询核验）

- 独立audit_provider_recommendations重新打开官方原文核验放行；放行母语音色路径可行，拒绝100%口音/全句质量承诺与Portuguese标签即巴葡认定。

- 用户询问MiniMax/ElevenLabs改为找对应音色生成是否可完全巴葡。本次只读官方文档；无声音添加/克隆/合成/付费或生产恢复。
- ElevenLabs官方accent troubleshooting推荐目标语言训练的母语音色，VoiceLibrary可按language/accent筛选；voices文档列葡语Brazil/Portugal。普通TTS没有独立pt-BR参数不等于不能通过巴葡voice生成巴葡。不能保证所有台词100%无错读/地区漂移/情绪问题；不同模型行为不同，不笼统声称所有跨语模型保留英语口音。
- MiniMax同步TTS language_boost仍仅Portuguese；官方MiniMax-AI技能仓库voicecatalog只按Portuguese分类，不能将Portuguese_前缀视为已认证巴西母语音色。必须候选试听/巴西母语评审核验后选用，未实测不得与Eleven库声排成质量名次。
- 判断：自然巴葡译文+已验证巴西母语声线+支持葡语模型是可行路径；放弃克隆原英文演员可降低原口音来源风险（机制推断，不是对本剧效果实测），同时不再保留原演员音色。先每个主要角色同稿测试普通/短喊/耳语/情绪/名字及原时窗，再经母语听审决定；字幕正确与音频口音验收分开。
- 来源：elevenlabs.io/docs/help-center/troubleshooting/why-does-my-voice-change-accent-or-language、/overview/capabilities/voices；platform.minimax.io/docs/api-reference/speech-t2a-http；github.com/MiniMax-AI/skills/blob/main/skills/frontend-dev/references/minimax-voice-catalog.md。第二部翻译/clone/TTS仍关闭。

### 2026-10-12 再核验ElevenLabs正式接口与巴葡配音备选（仅文档调研）

- 用户指出正式接口无法指定巴西，要求重新核验并推荐MiniMax/ElevenLabs之外方案。本轮仅官方文档只读，无付费调用、账号开通、素材上传、后端迁移或恢复翻译/TTS。
- 更正口径：ElevenLabs普通TTS convert的language_code为ISO639-1，不能用pt-BR单独指定地区，且multilingual_v2不支持该参数；无地区参数不等于模型不能讲巴葡。legacy /v1/dubbing target_lang仅ISO639-1/3，target_accent明确Experimental且用于库声音选择/译文方言，不能当克隆声稳定口音锁定。另一路/v1/dubbing/project支持Dubbing v2 Alpha的pt-BR；自带transcript/translation为Enterprise字段。此前支持巴葡说法不得套用普通TTS/MCP或承诺已实测。
- 官方承重来源：elevenlabs.io/docs/api-reference/text-to-speech/convert、/api-reference/legacy/dubbing/create、/api-reference/dubbing/create-project、/overview/capabilities/dubbing。
- Cartesia正式AddVoiceAccents枚举brazilian-portuguese/european-portuguese，locale pt-BR/pt-PT；自有InstantVoiceClone可先原语克隆再加巴葡accent，保持voice_id。locale模型要求sonic-3.6或更高；必须读voice已支持accent否则可回退原口音。公开声音/PVC不支持原地AddAccents，需另Localize新ID。Emotion tags只支持英语，不宣称巴葡可逐句情绪参数控制或原演技迁移。
- Cartesia来源 docs.cartesia.ai/api-reference/voices/add-accents、/build-with-cartesia/capability-guides/multilingual-voices、/clone-voices、/volume-speed-emotion；仅接口候选，未实测其巴葡听感/授权套餐/费用。
- Resemble云API SSML明确pt-br/pt-pt、语速/强弱/耳语/情绪强度控制；lang切换必须声音本身支持。VoiceCloningAPI须Business或更高，不能将所有英音clone一概视为巴葡兼容。来源docs.resemble.ai/getting-started/ssml、/voice-creation/voices/clone-overview。Speech-to-speech换声不等于跨语翻译，不作为英文直转巴葡既定路径。
- Azure Speech明确pt-BR库存声线，多角色可选；CustomVoice准入受限，不等同可直接克隆原演员。来源learn.microsoft.com/en-us/azure/ai-services/speech-service/language-support?tabs=tts、/custom-neural-voice。库存声线可做巴葡发音对照，表演控制依声线/模型，未保证戏剧质量。
- 本地研究备选ResembleAI/Chatterbox-Multilingual-pt-br官方HF模型卡明确巴葡专用微调/克隆和MIT，V3资产需配套loader/decoder，不能套网页通用英文加载示例宣称可用。未下载安装/4090测速/质量验证；不宣称即插即用或无算力成本。
- 推荐为判断而非实测排名：优先Cartesia验证地区口音链路、Resemble验证表演与克隆能力，两者用同一小样母语盲听后决策；Azure作原生巴葡发音基线，本地方案后续研究。第二部正式翻译/clone/TTS仍关闭。
- 独立audit_provider_recommendations官方文档复核放行；保留普通TTS参数/Alpha与套餐/voice语言能力/Cartesia英语情绪/本地loader边界，未形成实测质量排名。

### 2026-10-12 第二部仅前置准备已完成（等待ElevenLabs MCP）

- 最新授权覆盖第二部旧暂停状态，仅恢复素材下载、字幕整理及原文翻译前准备；正式巴葡台词翻译、克隆、TTS保持关闭，等待生产MCP支持ElevenLabs。第一部成果与生产状态不改动。
- 第二部确认为《Lady Chatterley’s Lover》，30集，四类素材共120文件（无字幕有BGM视频、纯BGM、纯音效、原SRT）。Windows下载完成，逐文件大小/SHA256读回通过；30集视频/BGM/SFX完整解码及分析音频提取完成，无时长差/相同轨道告警。这不等于原声听审或起点同步批准，视频原声含BGM，不是已验证纯净对白。
- Windows input/drama-02/保存原素材；output/drama-02/保存准备输出。30集602条源字幕，1/3/7/14/20/21/22/23集按原时码排序规范化，原编号/正文/时码保留。normalized SRT、dialogue.en.json、series-source.txt和subtitle-manifest.json已保存。
- 两份Review剧本已下载并解析：项目94/asset322、版本2、平台status10（不解释为批准），48页47841字符，SHA256 d8500a4a9d587fa9ab69771b6ee05ef8a386d4a46ba2590f77df2814a721a045；项目124/asset1223、版本1/status8，14页18536字符，SHA256 d865a01f061881d0cb0ca951ac58970cf40e818d7c872a68d535be99eda31080。来源清单仅保存ID/版本/hash，不写签名链接/认证。
- 全30集字面证据均更接近asset322：27集主要对白匹配，16/28/30集部分匹配。EP01不少于4词的候选对白23/23匹配322、8/23匹配1223；此为启发式文字证据，不代表602条全部逐句核验。不得从剧本补写成片字幕缺失内容。
- context-preparation/pretranslation-context.json为源语言准备草案：6个已识别角色加unknown占位、13条术语、13条连续性说明、10条全局待核项；包括16/28/30截句、13顺序差异、24重复句、river/lake与Sir/Lord差异及未知呼救/感叹。formal_translation_enabled/clone_enabled/tts_enabled、per_cue_reviewed、speaker_audio_verified均false，不能作为render已审核上下文。
- 原文分析由Windows本机Codex读取内联实际字幕/剧本文本完成，保持-a never和read-only沙箱。此前读取工具遭策略拒绝的无证据草案已隔离至context-preparation-before-inline-source，不用于生产；新流程绑定输入/版本/正文/策略指纹并拒绝整体空证据，未降级审批或沙箱。
- Windows轻量准备包 output/drama-02/Lady_Chatterleys_Lover_pretranslation_inputs.zip：619075字节、71文件，SHA256 77289692b691b3bfc4a70a887341e2b3a8cda85972071635466ca2c5ee3ad01e，ZIP CRC通过。含规范字幕、原文语料、上下文草案、两版剧本及来源、媒体manifest；不含大体积媒体、private签名链接或认证。仅本地保存，未上传S3/Review。
- 代码已push/Windows pull至da20410；prepare_drama_assets.py项目锁/清单指纹/4MiB精确Range断点续传/SHA复用核验，prepare_drama_context.py源语言分析/指纹/证据校验。新增5项下载边界测试Mac和Windows通过，不调用付费生成。有限计划任务Codex-LadyChatterley-Preparation、Codex-LadyChatterley-SourceContext产物状态均complete；未启用持续翻译或生产队列。
- 依共享工作区规则由audit_review_feedback独立只读审计，计数、待核项与代码安全通过，放行准备工作、不放行翻译/配音/逐句审核完成的说法。独立审计范围是上下文JSON和代码；媒体120SHA/30全解码由主代理Windows读回核验。Mac只读核验副本output/drama-02-preparation/verification/，preparation-summary.json保存最终状态。
- 下一步待ElevenLabs MCP支持后再适配并验证接口；先核对字幕疑点、原声身份/情绪与逐句剧本证据，重新审核上下文，才做巴葡译稿与代表性配音小样，不能复用本准备草案作为已审核断点。代码审查入口codex review或/review。

### 2026-10-12 ElevenLabs巴葡能力已核验（未实测）

- 用户要求查ElevenLabs有无巴葡。官方当前Dubbing overview明确v2 Alpha支持target_language pt-BR/pt-PT，v1不支持地区标签；原始TTS convert的language_code是ISO639-1且multilingual_v2不支持此参数，不能把v2方言标签直接用于普通TTS。
- 官方accent FAQ说非目标语言原生声音可保留原口音或漂移；Dubbing v2克隆强度越高也可能带入原口音。支持巴葡选项不代表克隆英语原音就必然通过专业听审。
- v2 API译稿编辑/重生成目前仅Enterprise，v2网页无编辑器；保留本项目现有定稿的导入方式还须单独核验，不把所有导入一概说Enterprise。v2视频是预览，若测试生产仍下载音频回混原片。仅查官方文档，无付费调用/clone/账号操作/后端迁移。
- 官方链接：elevenlabs.io/docs/overview/capabilities/dubbing、/docs/api-reference/text-to-speech/convert、/docs/help-center/troubleshooting/why-does-my-voice-change-accent-or-language。独立audit_review_feedback复核放行，收窄导入权限和口音保证措辞。建议对既有评审发音/赶语速/强情绪三类小样盲听，尚未实测，不宣称优于MiniMax。

### 2026-10-12 专业Review反馈已完整读取并形成改进规范

- 用户问巴葡差异并要求读取专业翻译评论、分析如何优化。只读Review148当前Carmilla FINAL_CUT32和对照文档2419的评论，按pageSize100分页并保存一级/回复原数据，原记录40条唯一commentId，涉及24集，对照文档无评论。原评论均来自同一API署名，专业身份依据用户说明，不把API署名本身当资质验证。无评论集不代表通过。
- 反馈快照output/review-feedback/2026-10-12；comments-all.private.json及逐asset文件原文保存。独立audit_review_feedback只读复核40/24/分类与代码证据：发音22、节奏/语速7、情绪7、音色2、背景/混音4，为可重复多标签共42，暂无评论明确指出词义误译。API未提供音画时间戳，“第N轴”不得硬映射第N字幕；同文不同ID的13/31评论分别保留。
- repair-plan.json+repair-checklist.csv保存40条专业原文、引用短语定位候选、类别、处理方案、未听审标记。匹配候选依据最终SRT（非原编号），缺短语保持定位待确认。仅分析，未改最终译稿/SRT/成片、未调用付费克隆/TTS、未发评论/审核/上传新素材。
- 明确EP2 Quinze anos文字本身没问题，评审指出anos欧葡发音，应口音小样而非错拼改译文。EP11 Tentei transferi-la的-la指maldição，评论发音模糊；与há quinze anos连续，可先核完整意群，不能凭此说原译义错。EP29引用威胁句原窗78.2–80.566共2.366sec，候选Que tocante. Mato todos vocês esta noite.尚未采用/测时，需剧本讽刺威胁语域及母语审阅；不承诺精简天然适配。EP29 Quantos anos既有ASR疑点是额外检查，不归因本轮评审。
- EP13英语残留与31背景杂音优先分对白/BGM/SFX核听；代码仅混dub+b+s、未混source_audio，故不能断言是原音轨直接漏出，可能背景轨或生成音，成因未听审。短喊Camila/Pai/Não需明确表演强度与音画依据，auto并非验收。
- 官方MiniMax同步TTS文档核验language_boost列Portuguese无独立pt-BR枚举，支持text内IPA覆盖及停顿标签；当前网关cachedschema描述也可IPA，但未实测巴葡音素/新参数。dub_episode确实languageBoost=Portuguese/prompt=None、speed可到1.6且atempo再拟合；editorial把proposed_speech_groups=[]。这些是机制风险而非已证明所有音频错误成因。不得把音乐prompt当巴葡口音指令或凭空设置BrazilianPortuguese枚举。
- AGENTS.md新增后续巴葡译稿/评审规范：自然口语与角色语域、完整意群、等义精简、文本与声音分层、正确拼写、真实情绪依据、comment定位/去重边界、现有声音复用小样验收。无业务代码改动、不改变已付费计划指纹；本次数据分析独立审核放行，不代表成片母语验收通过。

### 2026-10-11 英文原字幕/最终巴葡译文左右对照文档已上传

- 用户要求整理左原字幕、右译文的一个文档并直接上传Review Document。本轮继续用户授权Mac直连Review，未等待/使用Windows；不调用付费生成或改成片。
- 找到Mac已有完整原字幕副本/tmp/carmilla-dialogue.en.json，32集643条，SHA256 cd58d86dad68bd64baf65c45ffb1addea160420660705213bec888ea50b99707；复制保留在忽略output/review-publication/148/Carmilla/comparison/original-subtitle-source.json。左栏使用真实源字幕，未用旧剧本替代。右栏GET32份最终SRT、SHA256匹配S3元数据，保持最终译文完整。
- 按正时间重叠建立二部对应关系：一对多拆句/多对一合句置同一行，各自完整显示时间码及编号。完整覆盖643原cue、642最终配音字幕cue，640对照行，32个按集分页的双栏表。原拼写/ASR/截断疑点保留；时间窗口不是词级对齐。所有映射/源SHA/每集字幕SHA/文档SHA落comparison-validation.json。
- python-docx输出Carmilla_EN_pt-BR_Subtitle_Comparison.docx（65942bytes），A4、等宽两列、重复表头、行不跨页、章节与页码。保存后重新读取确认32表/2列/640行/每条原文与每条译文在正确侧，ZIP CRC通过。
- 用Review预签名PUT上传该单一DOCX，再createReviewMaterial DOCUMENT/documentKind DOCUMENT至PT Transalte #148，名称Carmilla | EN ↔ pt-BR | 字幕对照（32集）.docx，assetId2419；读取返回ID/URL关联一致，公开下载SHA256及ZIP CRC核验通过。真实回执review-upload-result.json、统一receipts.private.json持久化去重。项目现共67项已核验（视频32、字幕32、文档3）。原项目59未修改，新文档未审核/发评论；不把签名URL或文件内容提交Git。

### 2026-10-11 按用户授权绕过Windows直接登记Review成果

- 用户明确本轮不通过Windows做Review上传，覆盖此前本项目Mac代码/Windows业务规则在该登记任务上的限制。Windows留公司，Mac家中VPNppp0已连接且网关172.16.11.1可Ping，10.20.1.30 Ping/SSH均超时；不因旧Windowspending自行再起producer。新剧仍暂停。
- 目标项目实际名PT Transalte、ID148（用户称Pt-translate），原项目59不修改。直接Review查询确认初始FINAL_CUT0/DOCUMENT0。用户说明200字符限制已优化；当前继续采用简明备注，实际创建接口assetId/parentAssetId要null，不把schema只返回字段设0。之前Windowscreate均失败，未声称上传成功。
- 本轮Mac用忽略output一次性register_direct.py读取公开成果页32集永久S3链接；并行HEAD核验视频SHA256元数据及文件名hash/长度，再按publish_review.register统一读前/读后/持久化回执/global process lock顺序登记。已完整32/32 FINAL_CUT读回成功，assetIds2353–2384；每个视频tags均含Carmilla及pt-BR，所有URL仍现有S3，无重新传视频/渲染/克隆/付费TTS。
- Mac真实回执output/review-publication/148/Carmilla/receipts.private.json、progress.json、final-readback.private.json；私有源数据/链接/回执不进公开Git。Windows此前失败回执另存未覆盖，不能将Mac已完成任务按旧Windows数据盲重试；任何后续续跑先查远端已登记素材。
- 按原已授权交付方案继续DOCUMENT32最终SRT、巴葡实际配音台词合订DOCX1、交付说明DOCX1。SRT用公开URL并GET核验SHA/UTF8，DOCX只用交付SRT合订，不冒称完整分镜剧本，交付说明记录旧剧本版本问题/final.html来源及听审疑点。通过Review createFilePresignedUrl+PUT仅上传两份DOCX，接口code200/data=null/msg=预签名URL，私有helper适配msg，不把签名URL放用户页面/回执公开输出。最终DOCUMENT34项读回成功（32 SRT assetIds2385–2416、台词DOCX2417、交付说明DOCX2418）；连同32视频共66/66，progress.complete及final-all-readback.private.json落盘核验。两份公开DOCX GET下载SHA256/ZIP CRC核验通过。安全复核只向148创建授权交付素材，未向59写入、未调用audit/comment、未引入付费生成。所有新素材待审核，不继承英文审批或发评论。

### 2026-10-10 Review巴葡独立项目迁移方案分析（尚未创建/上传）

- 用户要求先分析MCP并规划将本次Carmilla英文转巴葡成果建独立review项目。只读initialize/tools-list/getProjects/getProjectReviewMaterials，未执行create/update/comment/audit/upload或建项目。新剧仍暂停。
- 英文源项目59登记quantity36，但实际Review FINAL_CUT32，另DOCUMENT2、ART_DIRECTION57（character11/scene14/legacy final-video32）、子素材147。现交付32视频+32最终SRT，视频3093508762bytes。不能按登记36补假集；旧英文Review cut与网盘来源可能为不同剪辑时长，原剧本也有版本问题。
- Review10tools可createReviewMaterial/createFilePresignedUrl/updateReviewMaterialVersion/query/comment/audit，生产11tools也没有createProject。建议独立项目Carmilla – Português (Brasil)，网页建项目需核查入口/权限，或补MCP创建项目；现有MCP本身不能完成建项目。
- 计划新项目FINAL_CUT32使用现有S3永久成片URL，DOCUMENT32最终SRT及巴葡配音台词合订稿/交付说明，素材notes关联来源59及语言/集号/SHA、未母语听审。角色场景参考25卡可按源URL复用/引用，旧英文final-video卡不重当巴葡输出。API create文档category未列legacy final-video；SRT预览/格式支持及required含只返回字段需先小样实测，不能假称已验证。
- 首集小样后查询readback，再批量32顺序注册、SHA+目标project+集号+类型持久化去重，歧义请求先查询不盲重试；返回新assetId不继承英文审批/评论，默认待审。原项目不写。本轮分析schema、素材快照、plan.json仅忽略output/review-upload-analysis，不进公开Git。

### 2026-10-10 成果页面增加逐集最终巴葡字幕下载

- 新剧分享用户明确先停，未下载/翻译/配音；本轮仅上一部Carmilla收尾。已核验上一部32集成片render完成、publication-state videos32，用户授权将每集字幕增加到现有S3成果页面，覆盖旧“只成片”上传限制的这部分。
- 提交bd3e023已Mac push/Windows pull；publish_dashboard从render-report.utterances实际配音文本/制作窗口导出UTF-8 SRT，绑定output_sha256，保留旧videos/history状态并增加subtitles。字幕不同视频版本不展示；已验证上传按SRT内容SHA去重，S3 HEAD核验长度、内容SHA及video-sha256，Content-Disposition attachment确保下载。未重传成片/重渲染/新增MiniMax费用。
- dashboard选择集数后出现下载巴葡字幕（SRT），切换和刷新更新链接，不把内部文件路径/认证数据放网页。SRT按最终配音单元导出，可能合并原字幕连续分句，32含拆分后的两人对白；属于制作时间窗口，未声称词级精准或母语听审完成。
- Windows针对dashboard6项测试通过，真实--once已发布全部32字幕和新版index。Windows Chrome实际选择32：按钮inline-block、下载文件名Carmilla_EP32_pt-BR.srt、S3链接正确、32按钮齐全。公开GET全部32文件SHA/UTF-8/attachment/对应成片版本核验已全部通过（32/32）；公开index含32个subtitle_url。通用代码仅发布字幕，不包含新剧任务。安全复核仅新增最终字幕公开对象，密钥不入Git，已有视频缓存不变。可用codex review复审。

### 2026-10-10 最后一集双说话人字幕已拆分并恢复

- 用户问最后一集状态。核验31集已发布，32准备失败：两条原字幕e32-5/6各含Carmilla和Laura对白，复合speaker被builder当新角色，参考不足10sec而停止。32尚无plan/paid submission，没有新增复合角色克隆。notify累计sent4/failed0。
- 仅本剧项目数据修正，通用代码不变。final.html EP32 shots21-23明确两人交替；源声ffmpeg静音检测给出15.381396–16.028125、18.359042–19.003417停顿，制作分句边界取15.7和18.65。未冒称原声听审/精确词级对齐。原28条字幕文件不变，editorial-before-dialogue-split备份完整；派生制作source把两cue拆为5a/5b、6a/6b，逐条保留original_subtitle_cue，原其余26条不变，译文内容不增减，现30句。
- screenplay-context添加本次分句依据与finalSHA，分别Carmilla/Laura，audio_verified仍false；重新审核/绑定源文及context fingerprint。Windows导出30句成功、22条需时长或来源复核。dialogue-split-review.json保留原cue、边界、静音证据；私有一次性处理脚本仅忽略output，不提交Git。恢复原唯一Codex-Carmilla-queue六并发，复用8个bank声音；下一步核验32真实合成、上传和完成状态，不能把启动称全剧完成。

### 2026-10-10 第25集音频下载失败已安全续跑（最新）

- 用户问配音为什么停止。核验已有24集render-report，queue停25；真实错误episode25/queue-render.log：e25-utterance-001 audio download failed; saved task can resume。其余19/20单元已完成，没有任何submission-pending文件，缺失句已有attempt0任务37317回执。不是选角/剧本匹配，也没有已证实的6并发服务限流。
- 原GET下载已有3次重试，失败类型被业务日志归并，不能猜具体HTTP状态/网络原因。原task私密记录是封装格式，直接取顶层taskStatus/resultAudioUrl的临时只读探测无效；不得将None/无URL当服务实际无输出，未修改记录。
- 没动业务代码/计划/声音库，Start-ScheduledTask恢复唯一Codex-Carmilla-queue。原19句通过绑定缓存复用，缺失句复用37317继续下载；实际progress已20/20，不能在未核验前称25成片上传。不存在新增paid ambiguous请求；后续TTS/合成按既有流程执行。钉钉watcher已送本次停止通知，累计sent3/failed0。
- 同轮最终核验25 render-report存在、video_payload_identical=true、20个result齐全，缺失句仍仅attempt0/task37317，没有新增合成。queue已到26 rendering/6路。下一步核验网页发布和26后的进度。不要因GET失败重新clone或新建输出目录放弃缓存；当前原因只能准确说音频下载失败，不能编造签名过期/403/限流。

### 2026-10-10 用户桌面final.html补充分镜参考（最新）

- 用户明确旧剧本不是最新版，授权以桌面final.html作为仅本剧参考，要求不用做到代码里。文件实际在Mac /Users/husw/Desktop/final.html，663681bytes；复制Windows input/drama-01/storyboard/final.html，两端SHA256相同：6efd76bfd6d0227e0d8a00dea6ca0d3e4132d87d0042e91aa39f56128ad0bb38。未改通用业务代码，未把HTML/字幕/译稿提交Git/S3；只有本接力记录提交。
- HTML const E含33条EP01–33，当前可见DOM为EP32且与内嵌EP32文字一致，原EP20明确整集跳过删除。实际32集的映射：实际1–19对应HTML1–19；实际20–30对应HTML21–31；实际31对应更新HTML32救援/逃离前半段，实际32对应其血液融合/结局后半段。原HTML33另留资料，不增加成片第33集。HTML镜头时间重叠/重置及旧标题85秒/镜头数已过时，不能替代实际字幕timecodes。
- 已核对分镜明确新对白：实际20的诅咒加速/Irina已到/三天期限由Carmilla说，之前选择得到新版证据支持；实际27两个被截断条件/七日仪式句由Carmilla说，但不添加源字幕缺失后半句；实际30 Open the door/What happen由Irina说；实际32 Your little sanctuary is falling apart由Irina说；实际21三句明确Woodsman。
- Windows仅在忽略output用一次性资料处理脚本，不新增项目通用功能。已更新尚未付费开始的EP21–32 editorial参考上下文，补final.html版本/hash、对应分镜和集号映射，修正明确角色，重新绑定translation screenplay_context_fingerprint并逐集export核验/保存读回。旧editorial移至editorial-before-final-storyboard，旧casting保留备份。已完成EP01–20 plan/音频完全保留，不改指纹/不重复付费。
- 第31全9句人工初译后经Windows Codex CLI结构化语义复审（source/reference/bible齐全），match=true且无error，独立reviewed-response及私密日志保留于output/drama-01/final-storyboard-review；原旧DOCX31不适用说明保留。第31初步source-role归属Irina/Laura/Camila（builder canonical到Carmilla）；同一房间被毁、救人、离开、old way都对应新分镜。真实源文Iet's go字母错拼不改，仅按分镜同义译Vamos。source/timecodes及锁定术语导出通过，长句时长仍待TTS。translation-progress.complete/pending空，不能称所有成片已完成。
- 分镜参考manifest在output/drama-01/final-storyboard-review/reference-manifest.json，各21–32 validation保存。原来源DOCX作旧背景资料仍记录，final.html为本次用户补充制作依据。已读回12集context fps及finalSHA；未对其他剧建立规则/默认映射。
- 第29 How many years与新版HTML30 shot12 Carmilla Her minions疑似ASR误听，未核原声，保留原字幕/译文的疑点标记，没有直接改字幕。production casting暂选已有Carmilla，source speaker仍unknown/audio_verified=false。23倒计时继续复用原Narrator_EP01，只是重绑新units fingerprint；母亲日记仍不能把作者当已识别reader。
- 核验本次新停实际21：Irina首次角色只有1.77sec，不足克隆10sec，并非未知reader。从实际26中script支持Irina的窗口收集14.733sec，原ensure_voices全局bank/统一receipt/pending保护下一次新增Irina，不复制角色/不复克隆旧声音。参考池output/drama-01/voice-reference-pool含原视频/音频SHA/actualcue/provenance，bank source_episode26记录，不伪造为21样本。现8声音，旧7个保持。
- 原6路顺序队列已恢复，实际21renderer接受六个不同任务37230–37235，22plan已准备，未启动重复queue。至少EP01–20已完成，网页publisher持续发布；notify独立watching/sent2/failed0，第二条为21停机通知，不是同一事件刷屏。下一步继续观察21后生产/29疑点原声核听；更新资料不等于原声说话人听审或母语验收。

### 2026-10-10 停止通知接入钉钉并恢复20（最新）

- 用户明确要求以后停止时向自己的钉钉通知。已读/应用dingtalk-sender技能，用户提供机器人Webhook；秘密只在Windows output/dingtalk-notify.private.json，不写Git/交接/网页。没有加签secret；如果机器人设置变化要在私密配置补secret/keyword。
- 此次实际19集成片，第20四句新增原对白的unknown source reader被计划准备拦截，并非6并发接口故障。翻译除31版本不匹配隔离外已完成（complete_with_review/pending31）。停止通知实际发出1条，钉钉API errcode0；watch-status sent1/failed0核验成功。不是仅模拟测试，也未向别的群发消息。
- 6611100/fcf5a53已push/Windows pull；69项unittest通过。notification_watch.py独立Windows监控每30秒扫描生产/翻译stopped、生产心跳超120秒、当前集等待pending译稿。按worker/episode/kind/occurrence持久化去重（原因细化不重发，兼容旧回执），网络调用前保存sending，超时不自动刷屏重发；未知/失败计数保留。通知仅集数/简明原因/页面URL，不含字幕、日志或任务请求。
- Windows计划任务Codex-Carmilla-Notify独立Running；AtLogOn用户trigger，失败最多3次间隔1分钟重启，ExecutionTimeLimit零，wrapper在忽略output/run-notification-watch.py。不依赖publisher/生产进程存活；主OS/Mac会话停止不会使它自动离线，Windows关机/无网络期间不能承诺可送达。
- queue异常保存原episode等进度，build-plan失败明确关联实际失败集及安全public_detail，不再只有CalledProcessError丢集数。
- EP20四句按Camila解释诅咒/Irina威胁的上下文选择已有Carmilla音色，原未知身份/台词/期限不变；EP21三句script明确WOODSMAN选择已有Woodsman；EP23倒计时选择原Narrator_EP01。production-casting各自完整speechunits fp绑定，没有改已存在plan、重克隆或绕过31匹配检查。此前已有19集缓存保留，已启动原6路顺序queue继续20。
- 选角制作仍是工作草稿，未知源声音不是已听审。后续26/27/29/30还有源台词/说话人疑点，如停止应由此监控告警；31继续查匹配版本，不准仅字幕放行。下一步核验20的实际付费任务进展和notify进程；用codex review复审新增监控。发送授权限本项目任务停止告警，不把Webhook用于其他群/消息。

### 2026-10-10 提升并发至6，减少顺序队列空等（最新）

- 用户要求更多并发加快。开工核验已有EP01–16真实成片，译稿已审至30；生产17因Two days left未知倒计时reader停止，翻译31主对白版本不匹配停止。没有活跃renderer需中断。
- 提交6ac8057已push/Windows pull，66项unittest通过。dub_episode/production_queue增加--tts-workers 1–6运行覆盖，不修改plan/paid signature；旧plan仍3但运行6，已完成单元缓存身份与全局bank/单集/付费pending锁保持。线程本地复用Mflix session，减少每句重新initialize，不跨线程共用HTTP session。
- 队列等待/renderer完成检查30s改5s（原来每集有最多30s空等）；当前/下一集准备仍2路，单集TTS6路，合成仍按集顺序，不启动多份付费producer。Windows忽略wrapper output/run-production-queue.py已加--tts-workers 6，原wrapper备份保留。
- EP17倒计时显式cast已有Narrator_EP01，与EP09保持制作选角一致；源speakerunknown/期限Two days不变，新增克隆0。EP18原review全部12条未知annotation已明确引用WOODSMAN，与匹配剧本逐句相符；本代理重新审核script-supported role，修正Woodsman角色，保留audio_verified=false。旧editorial在editorial-before-woodsman-role-review备份，重新生成context fingerprint及translation绑定，role-review.json留据，无已有18TTS/plan覆盖。新Woodsman为真实新增角色，后续如clone由原bank全局锁集中一次创建，不与未知旁白混淆。
- 31 mismatched_main_dialogue现在抛EditorialReviewRequired：保持隔离/pending，不生产该集，但后续32文本可继续。没有放宽cut gate或subtitle-only；当前32翻译中，pending=[31]，须再找匹配剧本/核对成片。
- 实际17renderer PID31928命令含--tts-workers6；已核验六个不同句子同时有接受task回执37106–37111。不能将并发翻倍称耗时必然减半；当前只是6路真实试跑。近期3路EP12–16单集耗时约290/144/131/103/158秒（私有report completed_at减input marker mtime，含API/合成）。下一步比较17/18完成耗时和失败率，如限流/歧义stop按回执核查，不能自动付费重试。
- MiniMax官方rate-limits文档speech-2.8-hd标60RPM，未给T2A CONN；这不是mflix网关的已测6并发保证，勿混用账号/接口限制。无新增API并发硬上限假承诺。当前至少16成片网页可播放，publisher持续发布。代码复审入口codex review；费用审查：提高workers不改TTS内容/voice/receipt、无paid自动retry。

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
