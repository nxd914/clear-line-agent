#!/bin/bash
# Quant AWS Setup Script (Ubuntu/Debian)
# Use this to prepare your EC2 instance for 24/7 autonomous trading.

set -e

echo "--- Installing System Dependencies ---"
sudo apt-get update
sudo apt-get install -y python3-pip python3-venv git docker.io docker-compose

echo "--- Setting up Docker Permissions ---"
sudo usermod -aG docker $USER

echo "--- Cloning Quant Repo (if not present) ---"
if [ ! -d "quant" ]; then
    echo "Please clone your repository first: git clone <your-repo-url> quant"
    # exit 1 
fi

echo "--- Preparing Environment ---"
echo "Creating .env template. Please fill this in!"
if [ ! -f "quant/.env" ]; then
    cat <<EOF > quant/.env
# Kalshi API Keys
KALSHI_API_KEY=
KALSHI_PRIVATE_KEY_PATH=/app/keys/kalshi_private.pem

# Sports Feed
API_FOOTBALL_KEY=

# Execution Config
EXECUTION_MODE=paper
BANKROLL_USDC=500.0

# Alert Webhooks
DISCORD_WEBHOOK_URL=
SLACK_WEBHOOK_URL=
EOF
    echo ".env template created at quant/.env"
fi

echo "--- Generating Docker Compose ---"
cat <<EOF > quant/docker-compose.yml
version: '3.8'
services:
  quant-trading:
    build: .
    volumes:
      - ./data:/app/quant/data
      - ~/.quant:/app/keys:ro
    env_file:
      - .env
    restart: unless-stopped
EOF

echo "--- DONE ---"
echo "To start trading:"
echo "1. Put your kalshi_private.pem in ~/.quant/"
echo "2. Edit quant/.env with your API keys"
echo "3. Run: cd quant && sudo docker-compose up -d --build"
