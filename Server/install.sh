#!/bin/bash
set -e

echo "========================================="
echo "ZeroSpice Server Installation Script"
echo "========================================="
echo ""

# Check if running as root
if [ "$EUID" -ne 0 ]; then
    echo "Error: This script must be run as root (use sudo)"
    exit 1
fi

# Get the project root directory (where install.sh is located)
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$PROJECT_ROOT"

echo "Project directory: $PROJECT_ROOT"
echo ""

# Check for ZeroTier installation
echo "========================================="
echo "ZeroTier Check"
echo "========================================="
echo ""

if ! command -v zerotier-cli &> /dev/null; then
    echo "⚠️  ZeroTier is not installed!"
    echo ""
    echo "ZeroSpice requires ZeroTier to be installed and configured."
    echo ""
    echo "To install ZeroTier:"
    echo "  curl -s https://install.zerotier.com | sudo bash"
    echo ""
    echo "After installation:"
    echo "  1. Join your ZeroTier network: sudo zerotier-cli join <network-id>"
    echo "  2. Authorize the device in your ZeroTier Central dashboard"
    echo "  3. Re-run this installation script"
    echo ""
    read -p "Do you want to install ZeroTier now? (y/N): " install_zt

    if [[ "$install_zt" =~ ^[Yy]$ ]]; then
        echo ""
        echo "Installing ZeroTier..."
        curl -s https://install.zerotier.com | bash

        echo ""
        echo "ZeroTier installed successfully!"
        echo ""
        read -p "Enter your ZeroTier network ID to join: " zt_network_id

        if [ -n "$zt_network_id" ]; then
            zerotier-cli join "$zt_network_id"
            echo ""
            echo "✓ Joined ZeroTier network: $zt_network_id"
            echo ""
            echo "⚠️  IMPORTANT: Authorize this device in your ZeroTier Central dashboard"
            echo "   Visit: https://my.zerotier.com/network/$zt_network_id"
            echo ""
            read -p "Press Enter once you've authorized the device to continue..."
        fi
    else
        echo ""
        echo "Installation cancelled. Please install and configure ZeroTier first."
        exit 1
    fi
else
    echo "✓ ZeroTier is installed"

    # Check if connected to any networks
    zt_status=$(zerotier-cli listnetworks 2>/dev/null | tail -n +2)
    if [ -z "$zt_status" ]; then
        echo "⚠️  Warning: Not connected to any ZeroTier networks"
        echo ""
        read -p "Enter your ZeroTier network ID to join (or press Enter to skip): " zt_network_id
        if [ -n "$zt_network_id" ]; then
            zerotier-cli join "$zt_network_id"
            echo "✓ Joined network: $zt_network_id"
            echo "⚠️  Remember to authorize this device in ZeroTier Central"
        fi
    else
        echo "✓ Connected to ZeroTier network(s)"
        echo "$zt_status"
    fi
fi

echo ""

# Function to prompt for input with default value
prompt_with_default() {
    local prompt="$1"
    local default="$2"
    local value

    if [ -n "$default" ]; then
        read -p "$prompt [$default]: " value
        echo "${value:-$default}"
    else
        read -p "$prompt: " value
        echo "$value"
    fi
}

# Configure .env file
echo "========================================="
echo "Configuration"
echo "========================================="
echo ""

if [ -f ".env" ]; then
    echo ".env file already exists."
    read -p "Do you want to reconfigure it? (y/N): " reconfigure
    if [[ ! "$reconfigure" =~ ^[Yy]$ ]]; then
        echo "Keeping existing .env file..."
        SKIP_ENV=true
    fi
fi

if [ "$SKIP_ENV" != true ]; then
    echo ""
    echo "Please provide the following configuration values:"
    echo ""

    # Prompt for values
    PROXMOX_IP=$(prompt_with_default "Proxmox IP address" "")
    PROXMOX_API_TOKEN=$(prompt_with_default "Proxmox API Token (format: user@realm!tokenid=uuid)" "")
    PROXY_IP=$(prompt_with_default "Proxy server IP (ZeroTier IP)" "")
    PROXY_HTTP_PORT=$(prompt_with_default "Proxy HTTP port" "8000")
    PROXY_SPICE_PORT=$(prompt_with_default "Proxy SPICE port" "3128")

    # Generate JWT secret
    echo ""
    echo "Generating JWT secret..."
    JWT_SECRET=$(openssl rand -hex 32)

    # Create .env file
    echo ""
    echo "Creating .env file..."
    cat > .env << EOF
# Proxmox Configuration
PROXMOX_IP=$PROXMOX_IP
PROXMOX_API_TOKEN=$PROXMOX_API_TOKEN

# Proxy Server Configuration
PROXY_IP=$PROXY_IP
PROXY_HTTP_PORT=$PROXY_HTTP_PORT
PROXY_SPICE_PORT=$PROXY_SPICE_PORT

# JWT Secret (auto-generated)
JWT_SECRET=$JWT_SECRET

# TOTP Secrets (add your users here)
# Generate secrets with: python3 src/setup_totp.py <username>
# TOTP_SECRET_ALICE=JBSWY3DPEHPK3PXP
# TOTP_SECRET_BOB=ANOTHER_SECRET_HERE
EOF

    echo "✓ .env file created successfully!"
    echo ""
    echo "IMPORTANT: You still need to add TOTP secrets for users."
    echo "Run: ./venv/bin/python3 src/setup_totp.py <username>"
    echo ""
fi

# Install system dependencies
echo "========================================="
echo "Installing Dependencies"
echo "========================================="
echo ""
echo "Step 1: Installing system dependencies..."
apt-get update
apt-get install -y python3 python3-pip python3-venv openssl

# Create virtual environment if it doesn't exist
if [ ! -d "venv" ]; then
    echo ""
    echo "Step 2: Creating Python virtual environment..."
    python3 -m venv venv
else
    echo ""
    echo "Step 2: Virtual environment already exists, skipping..."
fi

# Activate venv and install dependencies
echo ""
echo "Step 3: Installing Python dependencies..."
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
deactivate

# Install systemd service
echo ""
echo "========================================="
echo "Installing Systemd Service"
echo "========================================="
echo ""

# Create systemd service file directly
echo "Creating systemd service file..."
cat > /etc/systemd/system/zerospice.service << EOF
[Unit]
Description=ZeroSpice Server
After=network.target zerotier-one.service
Wants=zerotier-one.service

[Service]
Type=simple
User=root
WorkingDirectory=$PROJECT_ROOT
ExecStart=$PROJECT_ROOT/venv/bin/python3 src/run.py
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal

# Load environment variables from .env file
EnvironmentFile=$PROJECT_ROOT/.env

[Install]
WantedBy=multi-user.target
EOF

# Reload systemd
echo "Reloading systemd daemon..."
systemctl daemon-reload

echo ""
echo "========================================="
echo "Installation Complete!"
echo "========================================="
echo ""
echo "Configuration summary:"
echo "  Proxmox IP:    $PROXMOX_IP"
echo "  Proxy IP:      $PROXY_IP"
echo "  HTTP Port:     $PROXY_HTTP_PORT"
echo "  SPICE Port:    $PROXY_SPICE_PORT"
echo ""
echo "Next steps:"
echo "  1. Add TOTP users:     ./venv/bin/python3 src/setup_totp.py <username>"
echo "  2. Enable service:     sudo systemctl enable zerospice"
echo "  3. Start service:      sudo systemctl start zerospice"
echo "  4. Check status:       sudo systemctl status zerospice"
echo "  5. View logs:          sudo journalctl -u zerospice -f"
echo ""
echo "To reconfigure, run: sudo ./install.sh"
echo ""
