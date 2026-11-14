#!/bin/sh
set -eu
cd "$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
if [ ! -x .venv/bin/python ]; then
  echo 'Create the environment first: python3 -m venv .venv'
  echo 'Then install: .venv/bin/python -m pip install -r requirements.lock'
  exit 1
fi
exec .venv/bin/python -m uvicorn server.app:app --host 127.0.0.1 --port 8000 --workers 1 --limit-concurrency 32 --backlog 64 --timeout-keep-alive 5 --no-access-log
