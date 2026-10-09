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
python translate.py examples/dialogue.json --dry-run

# 在运行进程环境中配置 MINIMAX_API_KEY 后，准备全剧角色、称呼和术语表：
python translate.py input/drama-01.json --output-dir output/drama-01 --prepare-only

# 可编辑角色表，固定巴西姓名、昵称、家族姓氏和称呼，再执行翻译：
python translate.py input/drama-01.json --bible output/drama-01/series-bible.json --output-dir output/drama-01
```

也可省略 `--prepare-only`，一次完成准备与翻译。默认人名本地化为自然的巴西姓名；
`--name-mode preserve` 保留原人名并调整称呼。已有约定用 `--overrides` 导入，格式见
`examples/name-overrides.json`；这是虚构示例，实际项目需要自己的映射。
API Key 只从进程环境变量读取，不写入项目文件或日志。国内与国际站账户分别配置；
国际站可显式使用 `--base-url https://api.minimax.io/v1`。

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
