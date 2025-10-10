#!/bin/bash

# Production Gunicorn startup script for Golf Trips application
# Optimized for production deployment with no auto-reload

# Exit on error
set -e

# Color output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${GREEN}🏌️  Golf Trips - Production Mode${NC}"
echo "===================================="

# Check if .env exists
if [ -f .env ]; then
    # Load environment variables
    export $(grep -v '^#' .env | xargs)
fi


# Validate required environment variables
REQUIRED_VARS=("GOOGLE_CLIENT_ID" "GOOGLE_CLIENT_SECRET" "SECRET_KEY")
for var in "${REQUIRED_VARS[@]}"; do
    if [ -z "${!var}" ]; then
        echo -e "${RED}❌ Error: $var not set in .env${NC}"
        exit 1
    fi
done

# Configuration (can be overridden via environment variables)
HOST="${HOST:-0.0.0.0}"
PORT="${PORT:-8050}"

# Optimize for Render free tier (0.1 CPU, 512MB RAM)
# Use 1 worker with multiple threads for memory efficiency
WORKERS="${WORKERS:-1}"
THREADS="${THREADS:-2}"
TIMEOUT="${TIMEOUT:-120}"
LOG_LEVEL="${LOG_LEVEL:-info}"
# Recycle workers after fewer requests to prevent memory leaks
MAX_REQUESTS="${MAX_REQUESTS:-500}"
MAX_REQUESTS_JITTER="${MAX_REQUESTS_JITTER:-50}"
# Worker class optimized for I/O bound applications
WORKER_CLASS="${WORKER_CLASS:-gthread}"
# Preload app to save memory (shared code across workers)
PRELOAD="${PRELOAD:-true}"

echo ""
echo "Production Configuration (Optimized for Render Free Tier):"
echo "  Host: $HOST"
echo "  Port: $PORT"
echo "  Workers: $WORKERS (memory-optimized)"
echo "  Threads per worker: $THREADS"
echo "  Worker Class: $WORKER_CLASS"
echo "  Preload App: $PRELOAD"
echo "  Timeout: ${TIMEOUT}s"
echo "  Log Level: $LOG_LEVEL"
echo "  Max Requests: $MAX_REQUESTS (±$MAX_REQUESTS_JITTER jitter)"
echo ""

# Set PYTHONPATH to include the project root
export PYTHONPATH="${PWD}:${PYTHONPATH}"

# Start Gunicorn
echo -e "${GREEN}🚀 Starting Gunicorn in production mode...${NC}"
echo ""

# Build gunicorn command with conditional preload
GUNICORN_CMD="gunicorn \
    --bind $HOST:$PORT \
    --workers $WORKERS \
    --threads $THREADS \
    --worker-class $WORKER_CLASS \
    --timeout $TIMEOUT \
    --max-requests $MAX_REQUESTS \
    --max-requests-jitter $MAX_REQUESTS_JITTER \
    --log-level $LOG_LEVEL \
    --disable-redirect-access-to-syslog \
    --error-logfile - \
    --chdir ${PWD}"

# Add preload if enabled (saves memory but disables reload)
if [ "$PRELOAD" = "true" ]; then
    GUNICORN_CMD="$GUNICORN_CMD --preload"
fi

# Add temp dir if enabled
if [ "$USE_WORKER_TMP_DIR" = "true" ]; then
    GUNICORN_CMD="$GUNICORN_CMD --worker-tmp-dir /dev/shm"
fi

GUNICORN_CMD="$GUNICORN_CMD src.app:server"

echo "Starting with command:"
echo "$GUNICORN_CMD"
echo ""

exec $GUNICORN_CMD
