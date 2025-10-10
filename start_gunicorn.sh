#!/bin/bash

# Gunicorn startup script for Golf Trips application
# This provides better performance and production-ready features

# Exit on error
set -e

# Color output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${GREEN}🏌️  Golf Trips - Starting with Gunicorn${NC}"
echo "========================================"

# Check if .env exists
if [ ! -f .env ]; then
    echo -e "${RED}❌ Error: .env file not found!${NC}"
    echo "Please create .env file from .env.example and configure it."
    exit 1
fi

# Load environment variables
export $(grep -v '^#' .env | xargs)

# Check required environment variables
if [ -z "$GOOGLE_CLIENT_ID" ] || [ "$GOOGLE_CLIENT_ID" = "your-client-id.apps.googleusercontent.com" ]; then
    echo -e "${YELLOW}⚠️  Warning: GOOGLE_CLIENT_ID not configured in .env${NC}"
    echo "OAuth authentication may not work properly."
fi

if [ -z "$SECRET_KEY" ] || [ "$SECRET_KEY" = "your-secret-key-here" ]; then
    echo -e "${RED}❌ Error: SECRET_KEY not configured in .env${NC}"
    echo "Please set a secure SECRET_KEY in .env file."
    exit 1
fi

# Configuration
HOST="${HOST:-0.0.0.0}"
PORT="${PORT:-8050}"
WORKERS="${WORKERS:-4}"
THREADS="${THREADS:-2}"
TIMEOUT="${TIMEOUT:-120}"
LOG_LEVEL="${LOG_LEVEL:-info}"

echo ""
echo "Configuration:"
echo "  Host: $HOST"
echo "  Port: $PORT"
echo "  Workers: $WORKERS"
echo "  Threads per worker: $THREADS"
echo "  Timeout: ${TIMEOUT}s"
echo "  Log Level: $LOG_LEVEL"
echo ""

# Create logs directory if it doesn't exist
mkdir -p logs

# Set PYTHONPATH to include the project root
export PYTHONPATH="${PWD}:${PYTHONPATH}"
echo "PYTHONPATH set to: $PYTHONPATH"

# Start Gunicorn
echo -e "${GREEN}Starting Gunicorn...${NC}"
echo ""

gunicorn \
    --bind $HOST:$PORT \
    --workers $WORKERS \
    --threads $THREADS \
    --timeout $TIMEOUT \
    --access-logfile logs/access.log \
    --error-logfile logs/error.log \
    --log-level $LOG_LEVEL \
    --capture-output \
    --enable-stdio-inheritance \
    --reload \
    --chdir "${PWD}" \
    "src.app:server"

# Note: --reload is enabled for development. Remove it for production!
