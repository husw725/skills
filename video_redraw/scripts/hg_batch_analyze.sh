#!/usr/bin/env bash
# 把 hg_split 切出的各集顺序喂给 pipeline(--speed 还原时码, --overlays 避开控件帧)。
# 用法: scripts/hg_batch_analyze.sh <capture_dir> <speed> <name_prefix> [--dry-run]
#   例: scripts/hg_batch_analyze.sh output/wytl_s1 1.5 wytl
# 幂等: 已有 output/<prefix>_epNNN/storyboard.json 的集跳过; pipeline 自身各阶段也存在即跳过, 中断可直接重跑。
set -euo pipefail
dir=${1:?capture_dir}; speed=${2:?speed}; prefix=${3:?name_prefix}; dry=${4:-}
export PATH=/opt/homebrew/bin:$PATH
PY=/Users/husw/anaconda3/bin/python3
cd "$(dirname "$0")/.."
n=0; skipped=0
for mp4 in "$dir"/episodes/ep_*.mp4; do
  ep=$(basename "$mp4" .mp4)                # ep_001
  name="${prefix}_${ep#ep_}"                # wytl_001
  json="${mp4%.mp4}.json"
  if [ -f "output/$name/storyboard.json" ]; then skipped=$((skipped+1)); continue; fi
  cmd=($PY scripts/pipeline.py --video "$mp4" --name "$name" --speed "$speed")
  [ -f "$json" ] && cmd+=(--overlays "$json")
  if [ "$dry" = "--dry-run" ]; then echo "${cmd[*]}"; continue; fi
  echo "=== $name ($(date +%H:%M)) ==="
  "${cmd[@]}" 2>&1 | grep -vE "^\[ WARN|^objc|Warning|from pandas" | tail -3
  n=$((n+1))
done
echo "完成 $n 集, 跳过(已有) $skipped 集"
