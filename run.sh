#!/bin/bash

# Run the Golf Match Analysis application

echo "🏌️  Starting Golf Match Analysis..."
echo ""

# Ensure dependencies are installed and .venv is up to date
uv sync
source .venv/bin/activate
echo "✓ Virtual environment ready"

echo ""
echo "Starting application..."
echo "Visit: http://localhost:8050"
echo ""

# Run the app from the src directory
python src/app.py
