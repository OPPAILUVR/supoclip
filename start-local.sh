#!/usr/bin/env bash

# SupoClip Native macOS Local Runner
# Starts PostgreSQL, Redis, FastAPI Backend, Background Worker, AI Worker, and Next.js Frontend.

set -e

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$DIR"

# Colors
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

echo -e "${BLUE}==============================================${NC}"
echo -e "${BLUE}        SupoClip Native macOS Runner          ${NC}"
echo -e "${BLUE}==============================================${NC}"

# Check Homebrew services
echo -e "${YELLOW}--> Checking PostgreSQL and Redis services...${NC}"
if ! /opt/homebrew/opt/postgresql@15/bin/pg_isready -q; then
    echo "Starting PostgreSQL 15..."
    brew services start postgresql@15
    sleep 2
fi

if ! /opt/homebrew/opt/redis/bin/redis-cli ping > /dev/null 2>&1; then
    echo "Starting Redis..."
    brew services start redis
    sleep 1
fi
echo -e "${GREEN}✓ Database & Redis are running.${NC}"

# Ensure data directories exist
mkdir -p "$DIR/backend/uploads" "$DIR/backend/clips" "$DIR/backend/outputs" "$DIR/backend/temp" "$DIR/logs"

# Ensure frontend static standalone assets exist
if [ ! -d "$DIR/frontend/.next/standalone/public" ] && [ -d "$DIR/frontend/public" ]; then
    cp -R "$DIR/frontend/public" "$DIR/frontend/.next/standalone/"
fi
if [ ! -d "$DIR/frontend/.next/standalone/.next/static" ] && [ -d "$DIR/frontend/.next/static" ]; then
    mkdir -p "$DIR/frontend/.next/standalone/.next"
    cp -R "$DIR/frontend/.next/static" "$DIR/frontend/.next/standalone/.next/"
fi

# Load root .env
if [ -f "$DIR/.env" ]; then
    set -a
    source "$DIR/.env"
    set +a
fi

# Set default local variables if not present
export DATABASE_URL="${DATABASE_URL:-postgresql+asyncpg://supoclip:supoclip_password@localhost:5432/supoclip}"
export REDIS_HOST="${REDIS_HOST:-localhost}"
export REDIS_PORT="${REDIS_PORT:-6379}"
export TEMP_DIR="${TEMP_DIR:-$DIR/backend/uploads}"
export OUTPUT_DIR="${OUTPUT_DIR:-$DIR/backend/outputs}"
export PYTHONPATH="$DIR/backend"
export PATH="$DIR/backend/.venv/bin:$PATH"
export MAX_VIDEO_DURATION="${MAX_VIDEO_DURATION:-86400}"
export PRO_YOUTUBE_MAX_VIDEO_DURATION="${PRO_YOUTUBE_MAX_VIDEO_DURATION:-86400}"
export SCALE_YOUTUBE_MAX_VIDEO_DURATION="${SCALE_YOUTUBE_MAX_VIDEO_DURATION:-86400}"
export MAX_VIDEO_UPLOAD_BYTES="${MAX_VIDEO_UPLOAD_BYTES:-50000000000}"
export YOUTUBE_DOWNLOAD_MAX_BYTES="${YOUTUBE_DOWNLOAD_MAX_BYTES:-50000000000}"
export PROCESSING_TASK_TIMEOUT_SECONDS="${PROCESSING_TASK_TIMEOUT_SECONDS:-86400}"
export VIDEO_JOB_TIMEOUT="${VIDEO_JOB_TIMEOUT:-86400}"

# Clear old volume ID in Redis to avoid volume-id mismatch
/opt/homebrew/opt/redis/bin/redis-cli del supoclip:media-volume:api > /dev/null 2>&1 || true

DAEMON_MODE=0
DEV_MODE=0
for arg in "$@"; do
    case "$arg" in
        -d|--daemon)
            DAEMON_MODE=1
            ;;
        --dev)
            DEV_MODE=1
            ;;
        -h|--help)
            echo "Usage: ./start-local.sh [options]"
            echo "Options:"
            echo "  -d, --daemon   Run all services in the background"
            echo "  --dev          Run frontend in development mode (pnpm dev) instead of production standalone"
            exit 0
            ;;
    esac
done

# Ensure previous instances on these ports are stopped
pkill -f "uvicorn src.main:app.*8000" 2>/dev/null || true
pkill -f "node .next/standalone/server.js" 2>/dev/null || true
pkill -f "next-server.*3107" 2>/dev/null || true
pkill -f "next dev.*3107" 2>/dev/null || true
pkill -f "src.workers.run_workers" 2>/dev/null || true
pkill -f "src.workers.tasks" 2>/dev/null || true
pkill -f "src.workers.cron_worker" 2>/dev/null || true
pkill -f "src.workers.ai_worker" 2>/dev/null || true
lsof -ti :3107 | xargs kill -9 2>/dev/null || true
lsof -ti :8000 | xargs kill -9 2>/dev/null || true
sleep 1

echo -e "${YELLOW}--> Starting Backend API on http://localhost:8000 ...${NC}"
cd "$DIR/backend"
nohup .venv/bin/uvicorn src.main:app --host 0.0.0.0 --port 8000 </dev/null > "$DIR/logs/backend.log" 2>&1 &
BACKEND_PID=$!
disown $BACKEND_PID 2>/dev/null || true

echo -e "${YELLOW}--> Starting Background Worker (Tasks & Cron) ...${NC}"
nohup .venv/bin/python -m src.workers.run_workers </dev/null > "$DIR/logs/worker.log" 2>&1 &
WORKER_PID=$!
disown $WORKER_PID 2>/dev/null || true

echo -e "${YELLOW}--> Starting AI Worker (Draft Editor) ...${NC}"
nohup .venv/bin/arq src.workers.ai_worker.AIWorkerSettings </dev/null > "$DIR/logs/ai-worker.log" 2>&1 &
AI_WORKER_PID=$!
disown $AI_WORKER_PID 2>/dev/null || true

echo -e "${YELLOW}--> Starting Live Stream Monitor Worker ...${NC}"
nohup .venv/bin/python -m src.workers.live_stream_worker </dev/null > "$DIR/logs/live-worker.log" 2>&1 &
LIVE_WORKER_PID=$!
disown $LIVE_WORKER_PID 2>/dev/null || true

echo -e "${YELLOW}--> Starting Frontend on http://localhost:3107 ...${NC}"
cd "$DIR/frontend"
if [ "$DEV_MODE" -eq 1 ]; then
    nohup pnpm dev </dev/null > "$DIR/logs/frontend.log" 2>&1 &
    FRONTEND_PID=$!
    disown $FRONTEND_PID 2>/dev/null || true
else
    python3 -c "
import os, sys, subprocess
if os.fork() > 0:
    sys.exit(0)
os.setsid()
if os.fork() > 0:
    sys.exit(0)
os.chdir('$DIR/frontend')
env = os.environ.copy()
with open('$DIR/frontend/.env.local') as f:
    for line in f:
        line = line.strip()
        if line and not line.startswith('#') and '=' in line:
            k, v = line.split('=', 1)
            env[k.strip()] = v.strip()
with open('$DIR/logs/frontend.log', 'a') as out:
    proc = subprocess.Popen(['node', '.next/standalone/server.js'], env=env, stdout=out, stderr=out)
    with open('$DIR/.frontend_pid', 'w') as pf:
        pf.write(str(proc.pid))
"
    sleep 1
    FRONTEND_PID=$(cat "$DIR/.frontend_pid" 2>/dev/null || echo "")
fi

cd "$DIR"
echo "$BACKEND_PID" > "$DIR/.local_pids"
echo "$WORKER_PID" >> "$DIR/.local_pids"
echo "$AI_WORKER_PID" >> "$DIR/.local_pids"
echo "$LIVE_WORKER_PID" >> "$DIR/.local_pids"
echo "$FRONTEND_PID" >> "$DIR/.local_pids"

# Wait 3 seconds to verify processes started
sleep 3

echo -e "\n${GREEN}==============================================${NC}"
echo -e "${GREEN}   ✓ SupoClip is running locally!             ${NC}"
echo -e "${GREEN}==============================================${NC}"
echo -e "   Web Application : ${BLUE}http://localhost:3107${NC}"
echo -e "   Backend API     : ${BLUE}http://localhost:8000${NC}"
echo -e "   API Docs        : ${BLUE}http://localhost:8000/docs${NC}"
echo -e "   Logs Directory  : ${BLUE}$DIR/logs/${NC}"
echo -e "==============================================\n"

cleanup() {
    echo -e "\n${YELLOW}Stopping SupoClip processes...${NC}"
    kill $BACKEND_PID $WORKER_PID $AI_WORKER_PID $FRONTEND_PID 2>/dev/null || true
    rm -f "$DIR/.local_pids"
    echo -e "${GREEN}Stopped.${NC}"
    exit 0
}

if [ "$DAEMON_MODE" -eq 1 ]; then
    echo "Running in background (daemon mode)."
    echo "To stop SupoClip, run: ./stop-local.sh"
    echo "To check status, run: ./status-local.sh"
    exit 0
else
    echo "Running in foreground. Press [Ctrl+C] to stop all services."
    echo "Streaming backend log (tail -f logs/backend.log):"
    trap cleanup SIGINT SIGTERM
    tail -f "$DIR/logs/backend.log" &
    TAIL_PID=$!
    wait $FRONTEND_PID 2>/dev/null || true
    cleanup
fi
