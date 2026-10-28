#!/usr/bin/env bash
# Re-encode a licensed reference video to HEVC for the iOS app's mock glasses feed.
# MockDeviceKit only plays h265 files (developers.meta.com, Mock Device Kit docs).
# The mp4 is gitignored; re-run this after cloning. glasses_feed.json names the source video and task.
#
# Usage: scripts/make_mock_feed.sh [video_id]   (default: 07_u01_r02_c_01, IndEgo drill bit, CC BY 4.0)
set -euo pipefail
cd "$(dirname "$0")/.."

id="${1:-07_u01_r02_c_01}"
src=$(awk -F, -v id="$id" '$1 == id { gsub(/\r/, "", $NF); print $NF }' data/manifest.csv)
task=$(awk -F, -v id="$id" '$1 == id { print $2 }' data/manifest.csv)
[[ -n "$src" && -f "$src" ]] || { echo "no local file for $id in data/manifest.csv" >&2; exit 1; }

out=ios/ProcedureReplay/Resources/glasses_feed.mp4
mkdir -p "$(dirname "$out")"
# Portrait 540x960 at 30 fps, like the SDK sample's feed: a square 480x480 10 fps file streamed nothing
# (session and stream started, zero frames). The square frame is letterboxed, not cropped.
ffmpeg -y -loglevel error -i "$src" -an \
  -vf "scale=540:540:force_original_aspect_ratio=decrease,pad=540:960:(ow-iw)/2:(oh-ih)/2,fps=30" \
  -c:v libx265 -tag:v hvc1 -preset fast -crf 26 "$out"
# The app sends this id with each recording, so the upload inherits the feed video's license (server.store_upload).
printf '{"video_id": "%s", "task": "%s"}\n' "$id" "$task" > "${out%.mp4}.json"
echo "wrote $out and ${out%.mp4}.json from $id ($task)"
