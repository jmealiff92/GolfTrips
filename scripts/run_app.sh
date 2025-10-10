#!/bin/bash
# Quick launcher for the Golf Match Tracking app

cd "$(dirname "$0")"

echo "🏌️  Starting Golf Match Tracking System..."
echo ""

# Check if virtual environment exists
if [ ! -d ".venv" ]; then
    echo "❌ Virtual environment not found!"
    echo "Please create one first: python3 -m venv .venv"
    exit 1
fi

# Activate virtual environment
source .venv/bin/activate

# Check if database exists
if [ ! -f "golf_trips.db" ]; then
    echo "⚠️  Database not found. Running migration..."
    python migrate_data.py
    echo ""
fi

# Start the app
echo "🚀 Starting application..."
echo "📊 Open your browser to: http://127.0.0.1:8050"
echo ""
echo "Press Ctrl+C to stop the server"
echo ""

python dash_app_new.py
