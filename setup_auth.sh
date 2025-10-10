#!/bin/bash

# Setup script for Google OAuth authentication

echo "🏌️ Golf Trips - Google OAuth Setup"
echo "=================================="
echo ""

# Check if .env exists
if [ -f .env ]; then
    echo "⚠️  .env file already exists!"
    read -p "Do you want to overwrite it? (y/N): " overwrite
    if [ "$overwrite" != "y" ] && [ "$overwrite" != "Y" ]; then
        echo "Keeping existing .env file"
        exit 0
    fi
fi

# Copy .env.example to .env
echo "📝 Creating .env file from template..."
cp .env.example .env

# Generate secret key
echo "🔑 Generating SECRET_KEY..."
SECRET_KEY=$(python3 -c "import os; print(os.urandom(24).hex())")
if [ -z "$SECRET_KEY" ]; then
    echo "❌ Failed to generate SECRET_KEY. Please set it manually in .env"
else
    # Update SECRET_KEY in .env
    if [[ "$OSTYPE" == "darwin"* ]]; then
        # macOS
        sed -i '' "s/SECRET_KEY=your-secret-key-here/SECRET_KEY=$SECRET_KEY/" .env
    else
        # Linux
        sed -i "s/SECRET_KEY=your-secret-key-here/SECRET_KEY=$SECRET_KEY/" .env
    fi
    echo "✅ SECRET_KEY generated and added to .env"
fi

echo ""
echo "📋 Next steps:"
echo ""
echo "1. Get Google OAuth credentials:"
echo "   - Visit: https://console.cloud.google.com/apis/credentials"
echo "   - Follow the guide in OAUTH_SETUP.md"
echo ""
echo "2. Edit .env file and add:"
echo "   - GOOGLE_CLIENT_ID"
echo "   - GOOGLE_CLIENT_SECRET"
echo "   - ADMIN_EMAILS (comma-separated list)"
echo ""
echo "3. Install dependencies:"
echo "   pip install -r requirements.txt"
echo ""
echo "4. Run the app:"
echo "   python src/app.py"
echo ""
echo "✨ Setup complete! Edit .env to configure OAuth credentials."
