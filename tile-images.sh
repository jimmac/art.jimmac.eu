#!/bin/bash
#
# tile-images.sh — Center-crop two images by ~30% horizontally and tile side by side.
#
# Usage: tile-images.sh <image1> <image2> <output>

set -euo pipefail

if [[ $# -ne 3 ]]; then
  echo "Usage: $0 <image1> <image2> <output>"
  echo ""
  echo "Center-crops each image to 70% of its width (removing 15% from each side)"
  echo "and tiles them side by side into <output>."
  exit 1
fi

img1="$1"
img2="$2"
output="$3"

for f in "$img1" "$img2"; do
  if [[ ! -f "$f" ]]; then
    echo "Error: '$f' not found." >&2
    exit 1
  fi
done

magick \
  \( "$img1" -gravity center -crop 70%x100%+0+0 +repage \) \
  \( "$img2" -gravity center -crop 70%x100%+0+0 +repage \) \
  +append "$output"

echo "Created '$output' ($(identify -format '%wx%h' "$output"))"
