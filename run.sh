#!/bin/bash
set -e

# veFaaS native-python runtime entrypoint.
# Dependencies are installed by CreateDependencyInstallTask into the runtime
# (importable directly); our source (src/, app/) ships in the code zip.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

export PYTHONUNBUFFERED=1
export PYTHONPATH="${SCRIPT_DIR}/src:${PYTHONPATH}"

PORT="${_FAAS_RUNTIME_PORT:-${PORT:-8000}}"

# Preflight: surface the real import error clearly (release status truncates
# deep tracebacks otherwise).
python -c "import aiday_demo.server; print('PREFLIGHT import OK')" || {
  echo "PREFLIGHT import FAILED (see traceback above)"; exit 1;
}

# Single worker: task state lives in TOS, so scale is by instances, not workers.
exec python -m uvicorn aiday_demo.server:app \
  --host 0.0.0.0 \
  --port "${PORT}" \
  --workers 1 \
  --timeout-keep-alive 65 \
  --app-dir "${SCRIPT_DIR}/src"
