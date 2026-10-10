# dubbing-video

本项目在 Mac 上编辑代码，通过 GitHub 同步，在 Windows 原生环境执行。

## 连接试运行

- 仓库：`https://github.com/husw725/skills.git`
- 分支：`codex/dubbing-video-win-smoke`
- Windows 独立检出目录：`E:\workspace\dubbing-video-smoke`
- 项目目录：检出目录下的 `dubbing-video`
- 连接：Mac 执行 `ssh win`

Windows 运行命令：

```powershell
Set-Location E:\workspace\dubbing-video-smoke
git pull --ff-only
Set-Location dubbing-video
python smoke_test.py
```

脚本只允许在 Windows 执行，打印主机、Python 和 Git 提交信息，并写入
`output/smoke-result.json`，随后读取核验。无第三方依赖；产物不提交。

代码传递与远程运行已验证；当前已实现内容翻译模块，语音生成与混音后续接入。

## 素材准备

`prepare_media.py` 在 Windows 校验裸片、BGM、SFX，完整解码检查并记录 SHA-256，
从裸片第一条音轨导出原采样率 PCM 和 16 kHz 单声道识别音频。
指定 `--video`、`--bgm`、`--sfx`、`--output-dir`；FFmpeg 不在 PATH 时用 `--ffmpeg` 指定完整路径。
源素材保持不变，输出包括 `media-manifest.json`、`source-audio.wav` 和 `asr-source.wav`。
这一步不调用付费 API。音轨是否纯对白、背景轨的起点是否同步仍需听审；时长相近不能证明同步。

## 巴西葡语内容翻译

整季字幕可用 `prepare_subtitles.py SOURCE_DIR --output-dir OUTPUT_DIR` 整理：
识别 `.srt` 及误写的 `.str`/`.st`，生成每集规范字幕、全剧台词 JSON 和原文件校验清单。
条目按时间排序，但保留原编号与所有时码；原文件不修改。

也可由编辑/当前助手先完成文本译稿，再用
`export_translation.py SOURCE_JSON DRAFT_JSON --bible BIBLE_JSON --screenplay-context CONTEXT_JSON --output-dir OUTPUT_DIR`
在 Windows 核验并导出。这条路径不调用 MiniMax：检查台词 ID、源文本/时码指纹和锁定人名，
生成巴葡 SRT、原译文 CSV、JSON、复核清单和供后续配音接入的 `speech-units.draft.json`。
原字幕中的分句可提出连续配音分组，分组须核听，不能当成已确认的角色对白切片。

`translate.py` 使用 MiniMax 文本模型（默认 `MiniMax-M2.7`），不依赖第三方 Python 包。
正式业务执行限定 Windows；本阶段生成译文与配音准备数据，不生成语音。

每部剧使用独立输入和输出目录。同一部剧的所有集应一起提交，用 `episode` 区分，
`id` 在全剧唯一；同一集内按对白发生顺序排列。支持多人对白重叠，不移动原始时码。

输入可为 UTF-8 SRT，或下面的 JSON（时间单位为秒）：

```json
{
  "segments": [
    {"id": "e01-001", "episode": "1", "speaker": "角色名", "start": 0.0, "end": 2.8, "text": "原台词"}
  ]
}
```

SRT 的每个字幕块作为一句处理，无法从 SRT 凭空确定角色；未知角色保留为 `unknown`。
JSON 可提供已确认的角色、场景等信息。字幕显示时间不一定是实际说话时长，
建议使用音频识别/对齐得到的对白起止时间，输入格式不能代替这一步。

Windows 使用：

```powershell
Set-Location E:\workspace\dubbing-video-smoke\dubbing-video
# 先验证输入，不调用模型、不产生翻译费用：
python translate.py examples/dialogue.json --dry-run --subtitle-only

# 在运行进程环境中配置 MINIMAX_API_KEY 后，准备全剧角色、称呼和术语表：
python translate.py input/drama-01.json --screenplay-context input/drama-01.screenplay-context.json --output-dir output/drama-01 --prepare-only

# 可编辑角色表，固定巴西姓名、昵称、家族姓氏和称呼，再执行翻译：
python translate.py input/drama-01.json --screenplay-context input/drama-01.screenplay-context.json --bible output/drama-01/series-bible.json --output-dir output/drama-01
```

也可省略 `--prepare-only`，一次完成准备与翻译。默认人名本地化为自然的巴西姓名；
`--name-mode preserve` 保留原人名并调整称呼。已有约定用 `--overrides` 导入，格式见
`examples/name-overrides.json`；这是虚构示例，实际项目需要自己的映射。
API Key 只从进程环境变量读取，不写入项目文件或日志。国内与国际站账户分别配置；
国际站可显式使用 `--base-url https://api.minimax.io/v1`。

后续所有剧集都先核对剧本与成片/字幕版本，再结合剧本优化译文。
`--screenplay-context` 使用编辑核对过的 JSON，结构参考 `examples/screenplay-context.json`。
记录剧本文件名、版本和 SHA-256，以及每集匹配状态、原文摘录和每条字幕的角色/表演证据。
说话人不能确认时保留 `unknown`；剧本依据不等于原声听审。每个待译集/字幕都须覆盖，
源字幕变化、剧本版本变化会拒绝复用旧上下文或断点。人工译稿还必须携带上下文指纹。
剧本仅用于关系、指代和表演解释，不能将未出现在成片中的台词、画面文字补入配音。
缺少匹配剧本时先补齐；`--subtitle-only` 仅供明确授权的例外或虚构测试，不是生产默认。

处理规则：

- 通读全剧建立剧情记录和人名表；全剧扫描结束后统一检查姓名、昵称、姓氏与关系。
- 翻译时锁定姓名/称呼/术语，每次调用携带剧情记录、前后原文和前批译文。
  用受保护的占位符避免模型随句更换人名；缺失或篡改占位符的候选不接受。
- 每句生成自然/精简等候选，展开本地化姓名后估计时长，选择接近原时间窗口的表述。
  默认约 5 音节/秒、允许估算差 ±20%；两项可通过命令参数调整。
- 再调用模型对照原文审核否定、数字、关系、遗漏和巴葡表达；有问题时改写，默认最多两轮。
  仍不合适的句子进入待复核清单，不靠删除关键信息或编造台词凑时长。
- 每批保存断点。同一输入、角色表和参数重跑可续接；修改后必须使用新输出目录。
  同一输出目录一次只运行一个进程。

输出：`series-bible.json`、`translated.json`、`translated.review.json`、
`translated.pt-BR.srt`（多集分别导出）。SRT 是完整草稿，待复核句也包含在内；
最终交付前需要查看 JSON 待复核清单。

所有句子的 `tts_timing_verified` 均为 `false`：音节法仅用于翻译阶段筛选，不是真实配音时长。
后续必须生成 MiniMax 语音，测量实际时长，再调整措辞/语速。模型复核也不能替代巴葡人工听审。

验证命令（Windows）：

```powershell
python -m unittest discover -s tests -v
```

测试模拟 API，不调用付费模型。覆盖跨批/跨集上下文、人名锁定、时码保留、
语义修订、未解决问题标记、断点续跑与 HTTP 错误处理。真实模型质量需要样片验证。

## 逐集配音与输出

`dub_episode.py PLAN_JSON --mcp-config PRIVATE_CONFIG --ffmpeg FFMPEG_EXE` 在 Windows 执行。
配音脚本需要 Windows Python 中安装 `requests` 与 `numpy`（本机已核验存在）。
每集 plan 包含 project_id、episode、assets(video/bgm/sfx/source_audio)、voices、voice_bank、
units 和 output_dir；先核对角色/翻译，明确 production_voice、emotion 和原 start/end。
音色克隆按角色保存并复用，参考真实原声须10–300秒/20MB以内。
MCP认证 JSON 只放忽略目录；不要放入 plan 或 Git。API 返回的任务/临时 URL 仅存忽略目录。
生成任务逐条持久化，查询间隔至少10秒；提交网络中断视为状态不明，禁止自动重提导致重复扣费。
每句实际测时，必要时最多3次语速调整，再用FFmpeg保音高压缩至窗口；过快结果在报告中标记听审。
原英语对白不进入输出音轨；新对白与独立BGM/SFX混合。视频流直接复制，验证视频有效载荷哈希相同。
完成后的MP4为待听审版本，render-report.json记录实际时长、任务ID、语速调整和质量标记。
顺序生产每集；全部字幕/素材齐备不等于配音完成。

### 并发与防重复付费

`production_queue.py --start-episode 4 --ffmpeg FFMPEG_EXE --mcp-config PRIVATE_CONFIG`
在Windows后台运行：最多两路准备当前/下一集素材和已审译稿，每集三路台词TTS，
按集数顺序合成；发布器独立运行。缺少已审译稿时等待，不生成假译文。
队列锁阻止重复启动，同集生产锁阻止两进程重复配音。
全剧voice-bank由跨进程锁保护，新增角色克隆串行；克隆回执集中存放，
跨集恢复旧回执后复用voice_id。调用结果未知时停下核查，不自动再次克隆或生成。
读者身份unknown时不得自动按集新建旁白声音，须先确认可复用角色。
准备阶段不调用付费语音接口。每句仍可能因时长需要最多三次有记录的合成，
属于调整费用，与意外重复提交分别管理。不要同时启动未加锁的旧版本生产脚本。
首次生成的集计划保持不变；重启时核对译稿/参数后复用，声音库新增角色不改变计划。
缓存绑定voice_id、文本、时码与合成参数；变化时停止核查，不自动再生成。
旧缓存通过原请求回执核验后续用，缺少身份依据时停止。
渲染期间每30秒继续检查下一集译稿，最多两路准备，按集数顺序配音合成。

## S3 进度页面

`publish_dashboard.py --config PRIVATE_S3_CONFIG` 在Windows后台轮询。用户已批准目录
`aigc/drama/dubbing-video/carmilla-20261009/`。只上传已验证成片及单个index.html，
原片、音轨、字幕、剧本、任务日志和密钥不上传。页面内嵌纯进度数据，每30秒刷新，
每10分钟追加进度记录；新成片立即加入。全部32集发布后发布器自动停止。
