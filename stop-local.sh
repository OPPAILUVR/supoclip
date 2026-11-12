#!/usr/bin/env bash

# SupoClip Local Stop Script

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$DIR"

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo -e "${YELLOW}Stopping SupoClip processes...${NC}"

if [ -f "$DIR/.local_pids" ]; then
    while IFS= read -r pid; do
        if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
            kill "$pid" 2>/dev/null || true
        fi
    done < "$DIR/.local_pids"
    rm -f "$DIR/.local_pids"
fi

# Also kill any orphaned uvicorn or next on the specific ports if needed
pkill -f "uvicorn src.main:app.*8000" 2>/dev/null || true
pkill -f "next-server.*3107" 2>/dev/null || true
pkill -f "node .next/standalone/server.js" 2>/dev/null || true
pkill -f "src.workers.run_workers" 2>/dev/null || true
pkill -f "src.workers.tasks" 2>/dev/null || true
pkill -f "src.workers.cron_worker" 2>/dev/null || true
pkill -f "src.workers.ai_worker" 2>/dev/null || true
pkill -f "src.workers.live_stream_worker" 2>/dev/null || true
lsof -ti :3107 | xargs kill -9 2>/dev/null || true
lsof -ti :8000 | xargs kill -9 2>/dev/null || true

echo -e "${GREEN}✓ All SupoClip local services stopped.${NC}"
