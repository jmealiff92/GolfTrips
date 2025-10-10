#!/bin/bash

# Run the Golf Match Analysis application

echo "🏌️  Starting Golf Match Analysis..."
echo ""

# Activate virtual environment if it exists
if [ -d ".venv" ]; then
    source .venv/bin/activate
    echo "✓ Virtual environment activated"
else
    echo "⚠ Virtual environment not found. Creating one..."
    python3 -m venv .venv
    source .venv/bin/activate
    pip install -r requirements.txt
fi

echo ""
echo "Starting application..."
echo "Visit: http://localhost:8050"
echo ""

# Run the app from the src directory
python src/app.py
