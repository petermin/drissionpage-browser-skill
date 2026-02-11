#!/usr/bin/env bash
set -euo pipefail

SKILL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DATA_DIR="$HOME/.openclaw/browser/drissionpage"
VENV_DIR="$DATA_DIR/venv"
PID_FILE="$DATA_DIR/server.pid"
LOG_FILE="$DATA_DIR/server.log"
PORT=18850
# Proxy for browser traffic (e.g. socks5://127.0.0.1:18870 for residential IP)
BROWSER_PROXY="${BROWSER_PROXY:-}"

mkdir -p "$DATA_DIR"

is_running() {
    if [[ -f "$PID_FILE" ]]; then
        local pid
        pid=$(cat "$PID_FILE")
        if kill -0 "$pid" 2>/dev/null; then
            return 0
        fi
        rm -f "$PID_FILE"
    fi
    return 1
}

cmd_start() {
    if is_running; then
        echo "Server already running (PID $(cat "$PID_FILE"))"
        return 0
    fi

    # Create venv if missing
    if [[ ! -d "$VENV_DIR" ]]; then
        echo "Creating virtual environment..."
        python3 -m venv "$VENV_DIR"
    fi

    # Install/update dependencies
    echo "Installing dependencies..."
    "$VENV_DIR/bin/pip" install --quiet --upgrade pip
    "$VENV_DIR/bin/pip" install --quiet -r <(python3 -c "
import tomllib, pathlib
p = tomllib.loads(pathlib.Path('$SKILL_DIR/pyproject.toml').read_text())
for dep in p['project']['dependencies']:
    print(dep)
")

    # Ensure user-data dir exists
    mkdir -p "$DATA_DIR/user-data"

    # Launch server with Xvfb display
    if [[ -n "$BROWSER_PROXY" ]]; then
        echo "Using proxy: $BROWSER_PROXY"
    fi
    echo "Starting server on port $PORT..."
    DISPLAY=:99 BROWSER_PROXY="$BROWSER_PROXY" "$VENV_DIR/bin/uvicorn" \
        server:app \
        --host 127.0.0.1 \
        --port "$PORT" \
        --app-dir "$SKILL_DIR/scripts" \
        --log-level info \
        >> "$LOG_FILE" 2>&1 &

    local pid=$!
    echo "$pid" > "$PID_FILE"
    echo "Server starting (PID $pid)..."

    # Wait for server to be ready (up to 30s)
    for i in $(seq 1 30); do
        if curl -sf "http://127.0.0.1:$PORT/status" > /dev/null 2>&1; then
            echo "Server ready on port $PORT"
            return 0
        fi
        if ! kill -0 "$pid" 2>/dev/null; then
            echo "Server process died. Check logs: $LOG_FILE"
            rm -f "$PID_FILE"
            return 1
        fi
        sleep 1
    done

    echo "Server started but not yet responding. Check logs: $LOG_FILE"
}

cmd_stop() {
    if ! is_running; then
        echo "Server not running"
        return 0
    fi

    local pid
    pid=$(cat "$PID_FILE")
    echo "Stopping server (PID $pid)..."
    kill "$pid" 2>/dev/null || true

    # Wait for graceful shutdown
    for i in $(seq 1 10); do
        if ! kill -0 "$pid" 2>/dev/null; then
            echo "Server stopped"
            rm -f "$PID_FILE"
            return 0
        fi
        sleep 1
    done

    # Force kill
    kill -9 "$pid" 2>/dev/null || true
    rm -f "$PID_FILE"
    echo "Server force-stopped"
}

cmd_restart() {
    cmd_stop
    cmd_start
}

cmd_status() {
    if is_running; then
        local pid
        pid=$(cat "$PID_FILE")
        echo "Server running (PID $pid)"
        curl -sf "http://127.0.0.1:$PORT/status" 2>/dev/null && echo "" || echo "Server not responding to health check"
    else
        echo "Server not running"
    fi
}

cmd_logs() {
    if [[ -f "$LOG_FILE" ]]; then
        tail -f "$LOG_FILE"
    else
        echo "No log file found at $LOG_FILE"
    fi
}

case "${1:-help}" in
    start)   cmd_start ;;
    stop)    cmd_stop ;;
    restart) cmd_restart ;;
    status)  cmd_status ;;
    logs)    cmd_logs ;;
    *)
        echo "Usage: $0 {start|stop|restart|status|logs}"
        exit 1
        ;;
esac
