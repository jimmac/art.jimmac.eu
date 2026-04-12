#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

# Check dependencies
command -v python3 >/dev/null 2>&1 || { echo "python3 is required"; exit 1; }
command -v zola >/dev/null 2>&1 || { echo "zola is required"; exit 1; }
python3 -c "from PIL import Image" 2>/dev/null || { echo "Pillow is required: pip install Pillow"; exit 1; }

# Run prebuild
echo "Running prebuild..."
python3 prebuild.py

# Build site
echo "Building site with Zola..."
zola build

echo "Build complete! Output in public/"
