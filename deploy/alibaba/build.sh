#!/bin/bash
# Vendors Linux-compatible wheels into vendor/ for the Custom Runtime deploy.
# Run from the repo root before `s deploy`.
set -e
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/.."
cd "$HERE"
rm -rf vendor
python3 -m pip install \
  --platform manylinux2014_x86_64 \
  --python-version 3.10 \
  --implementation cp \
  --only-binary=:all: \
  --target vendor \
  -r requirements.txt
echo "vendored: $(du -sh vendor | cut -f1)"
