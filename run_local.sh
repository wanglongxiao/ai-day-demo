#!/bin/bash
# Local dev launcher: (re)starts the FastAPI server and streams logs.
#
#   ./run_local.sh          # restart server, then tail -f the log
#   ./run_local.sh stop     # stop the server
#   ./run_local.sh logs     # just tail -f the existing log
#
# State is in TOS, so a single uvicorn worker is all we need locally.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG_FILE="${SCRIPT_DIR}/server.log"
PID_FILE="${SCRIPT_DIR}/.server.pid"
PORT="${PORT:-8000}"
PY="${SCRIPT_DIR}/.venv/bin/python"

stop_server() {
  # Kill by recorded PID, then sweep anything still bound to the port.
  if [[ -f "${PID_FILE}" ]]; then
    local pid
    pid="$(cat "${PID_FILE}" 2>/dev/null || true)"
    if [[ -n "${pid}" ]] && kill -0 "${pid}" 2>/dev/null; then
      echo "Stopping server (pid ${pid})..."
      kill "${pid}" 2>/dev/null || true
      sleep 1
    fi
    rm -f "${PID_FILE}"
  fi
  local stragglers
  stragglers="$(lsof -tiTCP:"${PORT}" -sTCP:LISTEN 2>/dev/null || true)"
  if [[ -n "${stragglers}" ]]; then
    echo "Freeing port ${PORT} (pids: ${stragglers})..."
    kill ${stragglers} 2>/dev/null || true
    sleep 1
  fi
}

start_server() {
  echo "Starting server on http://127.0.0.1:${PORT}/ ..."
  : > "${LOG_FILE}"
  PYTHONUNBUFFERED=1 PORT="${PORT}" nohup "${PY}" -m aiday_demo >>"${LOG_FILE}" 2>&1 &
  echo $! > "${PID_FILE}"
  echo "Server pid $(cat "${PID_FILE}"), logging to ${LOG_FILE}"
}

case "${1:-restart}" in
  stop)
    stop_server
    echo "Stopped."
    ;;
  logs)
    echo "Tailing ${LOG_FILE} (Ctrl-C to stop)..."
    exec tail -f "${LOG_FILE}"
    ;;
  restart|start|"")
    stop_server
    start_server
    echo "----- streaming ${LOG_FILE} (Ctrl-C stops the log, server keeps running) -----"
    exec tail -f "${LOG_FILE}"
    ;;
  *)
    echo "usage: $0 [restart|stop|logs]" >&2
    exit 1
    ;;
esac
