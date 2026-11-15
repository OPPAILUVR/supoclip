#!/usr/bin/env bash

# SupoClip Local Status Script

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$DIR"

GREEN='\033[0;32m'
RED='\033[0;31m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo -e "${BLUE}==============================================${NC}"
echo -e "${BLUE}          SupoClip Service Status             ${NC}"
echo -e "${BLUE}==============================================${NC}"

# Check Postgres
if /opt/homebrew/opt/postgresql@15/bin/pg_isready -q; then
    echo -e "PostgreSQL (5432) : ${GREEN}RUNNING (Healthy)${NC}"
else
    echo -e "PostgreSQL (5432) : ${RED}STOPPED${NC}"
fi

# Check Redis
if /opt/homebrew/opt/redis/bin/redis-cli ping > /dev/null 2>&1; then
    echo -e "Redis (6379)      : ${GREEN}RUNNING (Healthy)${NC}"
else
    echo -e "Redis (6379)      : ${RED}STOPPED${NC}"
fi

# Check Backend
BACKEND_STATUS=$(curl -s -o /dev/null -w "%{http_code}" http://localhost:8000/health/db 2>/dev/null || echo "000")
if [ "$BACKEND_STATUS" = "200" ]; then
    echo -e "Backend API (8000): ${GREEN}RUNNING (HTTP 200 OK)${NC}"
else
    echo -e "Backend API (8000): ${RED}NOT RESPONDING (HTTP $BACKEND_STATUS)${NC}"
fi

# Check Frontend
FRONTEND_STATUS=$(curl -s -o /dev/null -w "%{http_code}" http://localhost:3107 2>/dev/null || echo "000")
if [ "$FRONTEND_STATUS" = "200" ] || [ "$FRONTEND_STATUS" = "307" ] || [ "$FRONTEND_STATUS" = "308" ]; then
    echo -e "Frontend (3107)   : ${GREEN}RUNNING (HTTP $FRONTEND_STATUS)${NC}"
else
    echo -e "Frontend (3107)   : ${RED}NOT RESPONDING (HTTP $FRONTEND_STATUS)${NC}"
fi

# Check Workers
WORKER_COUNT=$(pgrep -f "src.workers.tasks.WorkerSettings" | wc -l | tr -d ' ')
AI_WORKER_COUNT=$(pgrep -f "src.workers.ai_worker.AIWorkerSettings" | wc -l | tr -d ' ')
CRON_WORKER_COUNT=$(pgrep -f "src.workers.cron_worker.CronWorkerSettings" | wc -l | tr -d ' ')
LIVE_WORKER_COUNT=$(pgrep -f "src.workers.live_stream_worker" | wc -l | tr -d ' ')

if [ "$WORKER_COUNT" -gt 0 ]; then
    echo -e "Video Worker      : ${GREEN}RUNNING ($WORKER_COUNT process)${NC}"
else
    echo -e "Video Worker      : ${RED}STOPPED${NC}"
fi

if [ "$AI_WORKER_COUNT" -gt 0 ]; then
    echo -e "AI Worker         : ${GREEN}RUNNING ($AI_WORKER_COUNT process)${NC}"
else
    echo -e "AI Worker         : ${RED}STOPPED${NC}"
fi

if [ "$CRON_WORKER_COUNT" -gt 0 ]; then
    echo -e "Cron Worker       : ${GREEN}RUNNING ($CRON_WORKER_COUNT process)${NC}"
else
    echo -e "Cron Worker       : ${RED}STOPPED${NC}"
fi

if [ "$LIVE_WORKER_COUNT" -gt 0 ]; then
    echo -e "Live Stream Worker: ${GREEN}RUNNING ($LIVE_WORKER_COUNT process)${NC}"
else
    echo -e "Live Stream Worker: ${RED}STOPPED${NC}"
fi

echo -e "${BLUE}==============================================${NC}"
