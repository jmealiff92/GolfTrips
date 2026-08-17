#!/bin/bash

# Production startup script for the FastHTML POC (spike branch)
#
# This branch's version of this script boots fasthtml_poc/ (the FastHTML/HTMX
# proof-of-concept) instead of the Dash app in src/app.py, so a
# `[render preview]` PR for this branch actually serves the new app for live
# comparison. See fasthtml_poc/README.md for what it covers.
#
# Known limitation: Google OAuth redirect URIs must be pre-registered in
# Google Cloud Console. A Render preview gets a dynamically-generated URL per
# branch/PR, so once this is deployed, add
# "<preview-url>/authorize" as an Authorized redirect URI for the OAuth
# client before login will work there — this can't be automated.

# Exit on error
set -e

# Color output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${GREEN}🏌️  Golf Trips - FastHTML POC - Production Mode${NC}"
echo "===================================="

# Check if .env exists (repo-root .env, shared with the Dash app)
if [ -f .env ]; then
    # Load environment variables
    export $(grep -v '^#' .env | xargs)
fi

# Validate required environment variables (same three the Dash app needs)
REQUIRED_VARS=("GOOGLE_CLIENT_ID" "GOOGLE_CLIENT_SECRET" "SECRET_KEY")
for var in "${REQUIRED_VARS[@]}"; do
    if [ -z "${!var}" ]; then
        echo -e "${RED}❌ Error: $var not set in .env${NC}"
        exit 1
    fi
done

# Configuration (can be overridden via environment variables; Render sets $PORT)
export HOST="${HOST:-0.0.0.0}"
export PORT="${PORT:-8050}"

echo ""
echo "FastHTML POC Configuration:"
echo "  Host: $HOST"
echo "  Port: $PORT"
echo ""

# fasthtml_poc/ is a deliberately isolated uv project (its own pyproject.toml
# and lockfile) so it doesn't disturb the main Dash app's dependencies/venv.
echo -e "${GREEN}📦 Installing fasthtml_poc dependencies...${NC}"
(cd fasthtml_poc && uv sync)

echo ""
echo -e "${GREEN}🚀 Starting FastHTML POC in production mode...${NC}"
echo ""

# Disable the dev auto-reloader (file watching) for production.
export FASTHTML_RELOAD="false"

cd fasthtml_poc
exec uv run python main.py
