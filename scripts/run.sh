#!/usr/bin/env bash
# trading/run.sh — Process management for the Quant paper trading loop.
# Usage: ./trading/run.sh start|stop|restart|status

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DATA_DIR="$REPO_ROOT/data"
PID_FILE="$DATA_DIR/paper_fund.pid"
LOG_FILE="$DATA_DIR/paper_fund.log"
LOG_MAX_BYTES=10485760   # 10 MB
LOG_KEEP=5               # number of rotated logs to keep
PYTHON="${PYTHON:-python3}"

# ── helpers ────────────────────────────────────────────────────────────────

_pid_running() {
    local pid="$1"
    kill -0 "$pid" 2>/dev/null
}

_read_pid() {
    [[ -f "$PID_FILE" ]] && cat "$PID_FILE" || echo ""
}

_rotate_logs() {
    [[ ! -f "$LOG_FILE" ]] && return
    local size
    size=$(stat -f%z "$LOG_FILE" 2>/dev/null || stat -c%s "$LOG_FILE" 2>/dev/null || echo 0)
    if (( size >= LOG_MAX_BYTES )); then
        # Shift existing rotated logs down, drop oldest beyond LOG_KEEP
        for (( i=LOG_KEEP-1; i>=1; i-- )); do
            [[ -f "${LOG_FILE}.$i" ]] && mv "${LOG_FILE}.$i" "${LOG_FILE}.$((i+1))"
        done
        mv "$LOG_FILE" "${LOG_FILE}.1"
        echo "[run.sh] Rotated log → ${LOG_FILE}.1"
        # Remove any beyond LOG_KEEP
        for (( i=LOG_KEEP+1; i<=LOG_KEEP+10; i++ )); do
            [[ -f "${LOG_FILE}.$i" ]] && rm -f "${LOG_FILE}.$i"
        done
    fi
}

# ── commands ───────────────────────────────────────────────────────────────

cmd_start() {
    local pid
    pid=$(_read_pid)
    if [[ -n "$pid" ]] && _pid_running "$pid"; then
        echo "[run.sh] Already running (PID $pid). Use restart to cycle."
        exit 0
    fi

    mkdir -p "$DATA_DIR"
    _rotate_logs

    echo "[run.sh] Starting trading loop..."
    cd "$REPO_ROOT"
    PYTHONUNBUFFERED=1 nohup env PYTHONPATH="$(dirname "$REPO_ROOT"):${PYTHONPATH:-}" "$PYTHON" "$(dirname "$REPO_ROOT")/daemon.py" \
        >> "$LOG_FILE" 2>&1 &
    local new_pid=$!
    echo "$new_pid" > "$PID_FILE"
    sleep 1
    if _pid_running "$new_pid"; then
        echo "[run.sh] Started (PID $new_pid) — log: $LOG_FILE"
    else
        echo "[run.sh] Process exited immediately — check $LOG_FILE" >&2
        exit 1
    fi
}

cmd_stop() {
    local pid
    pid=$(_read_pid)
    if [[ -z "$pid" ]]; then
        echo "[run.sh] No PID file found — not running (or started outside run.sh)."
        return
    fi
    if _pid_running "$pid"; then
        echo "[run.sh] Stopping PID $pid..."
        kill "$pid"
        for i in $(seq 1 10); do
            _pid_running "$pid" || break
            sleep 0.5
        done
        if _pid_running "$pid"; then
            echo "[run.sh] Process didn't exit cleanly — sending SIGKILL."
            kill -9 "$pid"
        fi
        echo "[run.sh] Stopped."
    else
        echo "[run.sh] PID $pid not running."
    fi
    rm -f "$PID_FILE"
}

cmd_restart() {
    cmd_stop
    sleep 1
    cmd_start
}

cmd_status() {
    local pid
    pid=$(_read_pid)
    echo "══════════════════════════════════════"
    echo "  QUANT TRADING LOOP — STATUS"
    echo "══════════════════════════════════════"
    if [[ -z "$pid" ]]; then
        echo "  Process : STOPPED (no PID file)"
    elif _pid_running "$pid"; then
        local started cpu mem
        started=$(ps -o lstart= -p "$pid" 2>/dev/null | xargs || echo "unknown")
        cpu=$(ps -o %cpu= -p "$pid" 2>/dev/null | xargs || echo "?")
        mem=$(ps -o rss= -p "$pid" 2>/dev/null | awk '{printf "%.1f MB", $1/1024}' || echo "?")
        echo "  Process : RUNNING (PID $pid)"
        echo "  Started : $started"
        echo "  CPU/Mem : ${cpu}% / $mem"
    else
        echo "  Process : DEAD (stale PID $pid)"
        rm -f "$PID_FILE"
    fi
    echo ""
    if [[ -f "$LOG_FILE" ]]; then
        local log_size
        log_size=$(du -sh "$LOG_FILE" 2>/dev/null | cut -f1)
        echo "  Log     : $LOG_FILE ($log_size)"
        echo ""
        echo "── Last 10 log lines ───────────────────"
        tail -10 "$LOG_FILE"
    else
        echo "  Log     : not found"
    fi
    echo "══════════════════════════════════════"
}

# ── dispatch ───────────────────────────────────────────────────────────────

CMD="${1:-}"
case "$CMD" in
    start)   cmd_start   ;;
    stop)    cmd_stop    ;;
    restart) cmd_restart ;;
    status)  cmd_status  ;;
    *)
        echo "Usage: $0 start|stop|restart|status"
        exit 1
        ;;
esac
