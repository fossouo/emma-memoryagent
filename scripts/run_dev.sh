#!/bin/bash
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$HERE"
export QWEN_CLOUD_API_KEY="$(cat /Users/marbofinance/Documents/GitHub/env)"
exec .venv/bin/uvicorn src.main:app --host 127.0.0.1 --port 8000
