---
name: video-redraw-preprocess
description: 视频重绘项目的素材前置处理 agent。输入原片(YouTube 链接或本地视频)，自动完成：下载、镜头切片、关键帧抽取、台词转写、镜头视觉分析(景别/运镜/场景/人物/动作/情绪)，产出原片分镜表和反向剧本。用户说"处理原片/切片/反推剧本/反向剧本/生成分镜表/原片分析/yt下载素材"时使用。
---

# 素材前置处理 (video_redraw)

把一部原片变成可用于重绘生产的结构化素材：切片 + 分镜表 + 反向剧本。

## 前置条件

1. 依赖：`pip install -r requirements.txt`（yt-dlp、scenedetect、google-genai）；ffmpeg 需已安装。
2. 镜头视觉分析走本机 `claude` CLI（订阅额度，不花 API 钱），两段式：haiku 并行逐镜识别（默认 4 并发，`VIDEO_REDRAW_PARALLEL` 可调）→ sonnet 一次全局归并人物代号与场景写法（模型可用 `VIDEO_REDRAW_RECOG_MODEL`/`VIDEO_REDRAW_MERGE_MODEL` 覆盖）。台词优先用 yt 字幕（`--url` 模式自动抓，注意自动字幕无说话人标注）；没字幕才用 Gemini 转写音频（Claude 不支持音频输入）。`GEMINI_API_KEY` 设环境变量或放本 skill 目录 `.env`；有字幕或 `--skip-transcript` 时不需要。

## 流程

### 第一步：跑 pipeline（2.1 下载 + 2.2 切片 + 2.4 分镜表）

```bash
python scripts/pipeline.py --url <YouTube链接>        # 或 --video 本地文件
# 可选: --name 项目名  --output-dir 输出目录  --skip-transcript
#       --force 全部重跑;  --force-from scenes|transcript|analyze 只重跑某阶段及下游
```

产物在 `output/<项目名>/`：

| 文件 | 内容 |
|---|---|
| `clips/` | 每镜头一个物理切片 mp4 |
| `frames/` | 每镜头 2 张关键帧 |
| `transcript.json` | 带时间戳台词 |
| `storyboard.json` / `storyboard.md` | 原片分镜表（镜号/时间码/时长/景别/运镜/场景/人物/动作/情绪/台词） |

各阶段产物存在即跳过，Gemini 调用逐块落盘（`*.partial.jsonl`），中断后直接重跑同一命令即可从断点续跑。同一项目目录绑定一个源 URL，换片必须换 `--name`。

### 第二步：生成反向剧本（2.3）

pipeline 跑完后，读取 `output/<项目名>/storyboard.json`，由你（Claude）直接写出反向剧本，保存为 `output/<项目名>/script.md`：

- 先建**人物对照表**放在 script.md 开头：台词里的 speaker 代号（男A/女B）↔ 画面外貌代号（黑衣男）。依据是"某镜头 characters 只有一人且 dialogue 有台词"的行；对不上的标"待确认"，不要硬猜。之后全文只用外貌代号。
- 把场景(scene)相同且时间连续的镜头合并为一个"场次"。
- 每场次格式：`第N场  场景  日/夜` + 出场人物 + 动作描述（综合该场各镜头 action/mood）+ 对白（来自 dialogue，保留 speaker 代号）。
- 人物代号沿用分镜表里的外貌代号，全片一致；片头片尾/纯转场镜头可并入相邻场次或标注省略。
- 剧本使用中文，可用性优先：结构完整、对白齐全即可，不追求文学性。

### 交付

向用户报告：镜头数、场次数、总时长、产物路径清单。分镜表若要给团队精修，可提醒用 s3-upload 分享。

## 红果短剧（App 独占内容）采集

红果没有可抓的公开流（分享页只给 30 秒预告，yt-dlp 无提取器，App 缓存在私有沙盒且加密），可行路径是 **adb 驱动 App 播放 + scrcpy 录屏**（物理采集，不碰版权保护）。版权提醒：他人商业内容用于重绘/改编前先确认授权路径。

前置（一次性）：手机 USB 调试已授权；红果全屏播放器停在目标剧任意一集；播放倍速设为 1.5x；`brew install scrcpy tesseract`（含 chi_sim）。

```bash
export PATH=$PATH:/opt/homebrew/bin
# 1) 无人采集: 先开录再跳到第1集, 自动连播, 看门狗每60s无损读状态(暂停就点回去), 到第N+1集开始时停录
python3 scripts/hg_capture.py --goto 1 --episodes 81 --interval 60 --chunk 1200 --out output/wytl_s1
# 2) 按集切分(起点=t-cur/speed 取中位数, 坏读数过滤+链式兜底+跳过短集补齐), 产出 ep_NNN.mp4 + 入镜窗口 json
#    单集裁掉 2400x1080 左右黑边并用 x264 slow crf23 压(约 2 Mbps, 比原始录屏小 80%); 切完抽查无误后原始 chunk_*.mp4 可删
python3 scripts/hg_split.py --dir output/wytl_s1 --speed 1.5
# 3) 逐集喂 pipeline: --speed 把时码还原为真实值, --overlays 让抽帧避开控件入镜窗口(每60s约5s)
python3 scripts/pipeline.py --video output/wytl_s1/episodes/ep_001.mp4 --name wytl_ep01 --speed 1.5 \
  --overlays output/wytl_s1/episodes/ep_001.json
```

实测出的交互规则都写在 `hg_capture.py` 顶部 docstring（两段式播放、单点读状态需距上次点击 ≥5s、抽屉不自动关、亮背景帧 OCR 要高阈值二值化、停录必须给进程组发 SIGINT 否则 mp4 无 moov）。改坐标/阈值前先跑 `hg_capture.py --self-test`（真实帧）和 `hg_split.py --self-test`。

## 注意

- 本机 Anaconda 的 ffmpeg 缺 AV1 解码器。跑法：`PATH=/opt/homebrew/bin:$PATH /Users/husw/anaconda3/bin/python3 scripts/pipeline.py ...`（Homebrew 的 ffmpeg + Anaconda 的 python，直接 export PATH 会把 python3 也换掉）。

- 2.1 中"何时能拿到官方原片素材"是业务沟通问题，agent 只覆盖 yt 下载分支。
- 长片(>30min)转写和分析会产生较多 Gemini 调用，先用 `--skip-transcript` 快速预览分镜效果再全量跑。
- 镜头检测用 AdaptiveDetector + 1.2s 最小镜头时长（ep101 实测比 ContentDetector 默认少 11% 碎片、亚秒镜头归零）。仍嫌碎可调大 `pipeline.py` 的 `MIN_SHOT_SEC`，然后 `--force-from scenes` 重跑（不会重新下载和转写）。
