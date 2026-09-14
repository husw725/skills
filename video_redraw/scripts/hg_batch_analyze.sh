#!/usr/bin/env bash
# 把 hg_split 切出的各集顺序喂给 pipeline(--speed 还原时码, --overlays 避开控件帧)。
# 用法: scripts/hg_batch_analyze.sh <capture_dir> <speed> <name_prefix> [--dry-run]
#   例: scripts/hg_batch_analyze.sh output/wytl_s1 1.5 wytl
# 幂等: 已有 output/<prefix>_epNNN/storyboard.json 的集跳过; pipeline 自身各阶段也存在即跳过, 中断可直接重跑。
set -euo pipefail
dir=${1:?capture_dir}; speed=${2:?speed}; prefix=${3:?name_prefix}; dry=${4:-}
# Mac: Homebrew 的 ffmpeg(带 AV1) + Anaconda 的 python; 其它机器用 PATH 上的 python/ffmpeg
if [ -d /opt/homebrew/bin ]; then export PATH=/opt/homebrew/bin:$PATH; fi   # 裸 && 在 set -e 下会直接退出
PY=${PY:-/Users/husw/anaconda3/bin/python3}
[ -x "$PY" ] || PY=$(command -v python3 || command -v python)
# Windows 默认 cp936: 中文分镜表读写和 claude CLI 输出解码都会乱码
export PYTHONUTF8=1
cd "$(dirname "$0")/.."
n=0; skipped=0; failed=""
for mp4 in "$dir"/episodes/ep_*.mp4; do
  ep=$(basename "$mp4" .mp4)                # ep_001
  name="${prefix}_${ep#ep_}"                # wytl_001
  json="${mp4%.mp4}.json"
  if [ -f "output/$name/storyboard.json" ]; then skipped=$((skipped+1)); continue; fi
  cmd=($PY scripts/pipeline.py --video "$mp4" --name "$name" --speed "$speed")
  if [ -f "$json" ]; then cmd+=(--overlays "$json"); fi   # 同上: 裸 && 在 set -e 下缺 json 会整批退出
  if [ "$dry" = "--dry-run" ]; then echo "${cmd[*]}"; continue; fi
  echo "=== $name ($(date +%H:%M)) ==="
  # 73 集无人值守: 单集失败不能带走整批。重试一次, 再失败记下来继续下一集。
  # 状态必须直接取 pipeline 的退出码 —— 过 grep -v 管道的话, 输出被过滤干净时 grep 返回 1, 会把成功误判成失败。
  log=$(mktemp); ok=0
  for try in 1 2; do
    if "${cmd[@]}" >"$log" 2>&1; then ok=1; break; fi
    echo "  ! $name 第 $try 次失败"
  done
  grep -vE "^\[ WARN|^objc|Warning|from pandas" "$log" | tail -3 || true
  rm -f "$log"
  if [ "$ok" = 1 ]; then n=$((n+1)); else failed="$failed $name"; fi
done
echo "完成 $n 集, 跳过(已有) $skipped 集"
[ -n "$failed" ] && echo "失败:$failed" || true
