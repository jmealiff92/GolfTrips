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
if [ ! -f .env ]; then
    echo -e "${RED}❌ Error: .env file not found!${NC}"
    exit 1
fi

# Load environment variables
export $(grep -v '^#' .env | xargs)

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
WORKERS="${WORKERS:-$(( $(nproc) * 2 + 1 ))}"  # Auto-calculate: (2 x CPU cores) + 1
THREADS="${THREADS:-4}"
TIMEOUT="${TIMEOUT:-300}"
LOG_LEVEL="${LOG_LEVEL:-warning}"
MAX_REQUESTS="${MAX_REQUESTS:-1000}"
MAX_REQUESTS_JITTER="${MAX_REQUESTS_JITTER:-50}"

echo ""
echo "Production Configuration:"
echo "  Host: $HOST"
echo "  Port: $PORT"
echo "  Workers: $WORKERS"
echo "  Threads per worker: $THREADS"
echo "  Timeout: ${TIMEOUT}s"
echo "  Log Level: $LOG_LEVEL"
echo "  Max Requests: $MAX_REQUESTS (±$MAX_REQUESTS_JITTER jitter)"
echo ""

# Create logs directory
mkdir -p logs

# Create PID directory
mkdir -p run

# Set PYTHONPATH to include the project root
export PYTHONPATH="${PWD}:${PYTHONPATH}"

# Start Gunicorn
echo -e "${GREEN}🚀 Starting Gunicorn in production mode...${NC}"
echo ""

exec gunicorn \
    --bind $HOST:$PORT \
    --workers $WORKERS \
    --threads $THREADS \
    --worker-class gthread \
    --timeout $TIMEOUT \
    --max-requests $MAX_REQUESTS \
    --max-requests-jitter $MAX_REQUESTS_JITTER \
    --access-logfile logs/access.log \
    --error-logfile logs/error.log \
    --log-level $LOG_LEVEL \
    --capture-output \
    --enable-stdio-inheritance \
    --pid run/gunicorn.pid \
    --chdir "${PWD}" \
    --daemon \
    "src.app:server"

echo -e "${GREEN}✅ Gunicorn started successfully!${NC}"
echo ""
echo "Process ID saved to: run/gunicorn.pid"
echo "Access logs: logs/access.log"
echo "Error logs: logs/error.log"
echo ""
echo "To stop the server:"
echo "  kill \$(cat run/gunicorn.pid)"
echo ""
echo "To view logs:"
echo "  tail -f logs/error.log"
echo "  tail -f logs/access.log"
