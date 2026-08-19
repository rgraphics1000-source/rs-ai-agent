#!/bin/bash
# ==============================================================================
# RS AI Agent - 1-Click Free VPS Automated Deployment Script
# Tested on Ubuntu 22.04 / 24.04 LTS (Oracle Cloud Always Free / AWS / DigitalOcean)
# ==============================================================================

set -e

echo "============================================================"
echo "🚀 Starting RS AI VPS Automated Setup..."
echo "============================================================"

# 1. Update system packages
echo "📦 Updating system packages..."
sudo apt-get update -y && sudo apt-get upgrade -y

# 2. Install essential tools & Docker
echo "🐳 Installing Docker & Docker Compose..."
sudo apt-get install -y apt-transport-https ca-certificates curl gnupg lsb-release git ufw

if ! command -v docker &> /dev/null; then
    curl -fsSL https://get.docker.com | sh
    sudo usermod -aG docker $USER
fi

sudo apt-get install -y docker-compose-plugin docker-compose

# 3. Configure Linux Firewall
echo "🛡️ Configuring Firewall ports (80, 443, 8000)..."
sudo ufw allow 22/tcp || true
sudo ufw allow 80/tcp || true
sudo ufw allow 443/tcp || true
sudo ufw allow 8000/tcp || true
sudo ufw --force enable || true

# 4. Open Oracle Cloud iptables rules if applicable
if command -v iptables &> /dev/null; then
    sudo iptables -I INPUT 6 -m state --state NEW -p tcp --dport 80 -j ACCEPT || true
    sudo iptables -I INPUT 6 -m state --state NEW -p tcp --dport 443 -j ACCEPT || true
    sudo iptables -I INPUT 6 -m state --state NEW -p tcp --dport 8000 -j ACCEPT || true
    sudo netfilter-persistent save || true
fi

# 5. Build and launch Docker container
echo "🏗️ Building and starting RS AI container..."
docker compose down || true
docker compose up -d --build

echo "============================================================"
echo "🎉 DEPLOYMENT COMPLETE!"
echo "📍 Your RS AI Agent is now running 24/7 on Port 8000!"
echo "🌐 Open: http://$(curl -s ifconfig.me):8000 in your browser."
echo "============================================================"
