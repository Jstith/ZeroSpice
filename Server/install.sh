#!/bin/bash
set -e

echo "ZeroSpice Server Installer"
echo ""

if [ "$EUID" -ne 0 ]; then
    echo "[ERROR] Must run as root (use sudo)"
    exit 1
fi

# Check if whiptail is available
if command -v whiptail &> /dev/null; then
    USE_WHIPTAIL=true
else
    USE_WHIPTAIL=false
    echo "[INFO] Whiptail not found, using basic prompts"
fi

# Detect if running from curl pipe
if [ -t 0 ]; then
    INTERACTIVE=true
else
    INTERACTIVE=false
    USE_WHIPTAIL=false
fi

# Check Docker
if ! command -v docker &> /dev/null; then
    echo "[ERROR] Docker not found. Install: https://docs.docker.com/engine/install/"
    exit 1
fi

if ! command -v docker compose &> /dev/null; then
    echo "[ERROR] Docker Compose not found. Install Docker Compose plugin"
    exit 1
fi

# Get script directory or download location
if [ "$INTERACTIVE" = true ] && [ -f "docker-compose.yml" ]; then
    INSTALL_DIR=$(pwd)
    echo "[INFO] Installing from: $INSTALL_DIR"
else
    INSTALL_DIR="/opt/zerospice"
    echo "[INFO] Installing to: $INSTALL_DIR"
    mkdir -p "$INSTALL_DIR"
    cd "$INSTALL_DIR"

    # Download files
    BASE_URL="https://raw.githubusercontent.com/Jstith/zerospice/main/Server"

    echo "[INFO] Downloading configuration files..."
    curl -fsSL "$BASE_URL/docker-compose.yml" -o docker-compose.yml
    curl -fsSL "$BASE_URL/Dockerfile" -o Dockerfile
    curl -fsSL "$BASE_URL/requirements.txt" -o requirements.txt
    curl -fsSL "$BASE_URL/.dockerignore" -o .dockerignore
    curl -fsSL "$BASE_URL/.env.example" -o .env.example

    mkdir -p src
    curl -fsSL "$BASE_URL/src/spice_proxy.py" -o src/spice_proxy.py
    curl -fsSL "$BASE_URL/src/admin.py" -o src/admin.py
fi

# Helper function for whiptail input
get_input() {
    local title="$1"
    local prompt="$2"
    local default="$3"
    local result

    result=$(whiptail --title "$title" --inputbox "$prompt" 10 60 "$default" 3>&1 1>&2 2>&3)

    if [ $? -ne 0 ]; then
        exit 1
    fi

    echo "$result"
}

# Configuration
if [ ! -f ".env" ]; then
    echo ""
    echo "[INFO] Creating .env configuration file"

    # Load existing values if present
    LOAD_EXISTING=false
    if [ -f ".env" ] && [ "$USE_WHIPTAIL" = true ]; then
        if whiptail --title "Existing Configuration" --yesno "An existing .env file was found. Would you like to load values from it?" 10 60; then
            LOAD_EXISTING=true
            source .env
        fi
    fi

    if [ "$USE_WHIPTAIL" = true ]; then
        # Whiptail-based configuration
        whiptail --title "ZeroSpice Configuration" --msgbox "Welcome to ZeroSpice configuration.\n\nYou'll configure:\n- Network mode (Tailscale, local, or custom)\n- Proxmox connection\n- Port settings" 14 70

        # Network mode selection
        NETWORK_MODE=$(whiptail --title "Network Configuration" --menu "Choose network deployment mode:" 14 70 3 \
            "tailscale" "Tailscale VPN (recommended)" \
            "local" "Local network / All interfaces (0.0.0.0)" \
            "custom" "Custom IP address" \
            3>&1 1>&2 2>&3)

        if [ $? -ne 0 ]; then
            exit 1
        fi

        case $NETWORK_MODE in
            tailscale|local)
                PROXY_IP="0.0.0.0"
                ;;
            custom)
                PROXY_IP=$(get_input "Custom IP Address" "Enter the IP address to bind to:" "${PROXY_IP:-}")
                if [ -z "$PROXY_IP" ]; then
                    whiptail --title "Error" --msgbox "IP address is required!" 8 50
                    exit 1
                fi
                ;;
        esac

        # Proxmox configuration
        whiptail --title "Proxmox Configuration" --msgbox "Configure Proxmox connection.\n\nYou'll need:\n- Proxmox IP address\n- API token (format: user@realm!tokenid=uuid)" 12 70

        PROXMOX_IP=$(get_input "Proxmox IP Address" "Enter Proxmox server IP:" "${PROXMOX_IP:-}")

        if [ -z "$PROXMOX_IP" ]; then
            whiptail --title "Error" --msgbox "Proxmox IP is required!" 8 50
            exit 1
        fi

        PROXMOX_API_TOKEN=$(get_input "Proxmox API Token" "Enter API token:\n(format: user@realm!tokenid=uuid)" "${PROXMOX_API_TOKEN:-}")

        if [ -z "$PROXMOX_API_TOKEN" ]; then
            whiptail --title "Error" --msgbox "API token is required!" 8 50
            exit 1
        fi

        # Port configuration
        PROXY_HTTP_PORT=$(get_input "HTTP Port" "Enter HTTP port for REST API:" "${PROXY_HTTP_PORT:-80}")
        PROXY_HTTP_PORT=${PROXY_HTTP_PORT:-80}

        # JWT secret
        if [ -n "$JWT_SECRET" ] && [ "$LOAD_EXISTING" = true ]; then
            if whiptail --title "JWT Secret" --yesno "Use existing JWT secret?\n\n(Select No to generate new)" 10 60; then
                USE_EXISTING_JWT=true
            else
                USE_EXISTING_JWT=false
            fi
        else
            USE_EXISTING_JWT=false
        fi

        if [ "$USE_EXISTING_JWT" != true ]; then
            JWT_SECRET=$(openssl rand -hex 32)
        fi

        # Summary
        SUMMARY="Configuration Summary:\n\n"
        SUMMARY+="Network:     $NETWORK_MODE\n"
        SUMMARY+="Bind IP:     $PROXY_IP\n"
        SUMMARY+="HTTP Port:   $PROXY_HTTP_PORT\n"
        SUMMARY+="Proxmox IP:  $PROXMOX_IP\n"

        if ! whiptail --title "Confirm" --yesno "$SUMMARY\nProceed?" 14 60; then
            echo "[INFO] Installation cancelled"
            exit 0
        fi

    else
        # Basic prompt-based configuration
        if [ "$INTERACTIVE" = true ]; then
            read -p "Proxmox IP: " PROXMOX_IP
            read -p "Proxmox API Token: " PROXMOX_API_TOKEN
            read -p "Proxy bind address [0.0.0.0]: " PROXY_IP
            PROXY_IP=${PROXY_IP:-0.0.0.0}
            read -p "HTTP Port [80]: " PROXY_HTTP_PORT
            PROXY_HTTP_PORT=${PROXY_HTTP_PORT:-80}
        else
            # Non-interactive mode (curl pipe)
            echo "[WARN] Non-interactive mode: Using environment variables"
            PROXMOX_IP=${PROXMOX_IP:-}
            PROXMOX_API_TOKEN=${PROXMOX_API_TOKEN:-}
            PROXY_IP=${PROXY_IP:-0.0.0.0}
            PROXY_HTTP_PORT=${PROXY_HTTP_PORT:-80}

            if [ -z "$PROXMOX_IP" ] || [ -z "$PROXMOX_API_TOKEN" ]; then
                echo "[ERROR] Required: PROXMOX_IP and PROXMOX_API_TOKEN environment variables"
                echo "Usage: curl -fsSL <url> | PROXMOX_IP=x.x.x.x PROXMOX_API_TOKEN=xxx sudo -E bash"
                exit 1
            fi
        fi

        JWT_SECRET=$(openssl rand -hex 32)
    fi

    # Create .env file
    cat > .env << EOF
# Proxmox Configuration
PROXMOX_IP=$PROXMOX_IP
PROXMOX_API_TOKEN=$PROXMOX_API_TOKEN

# Proxy Server Configuration
PROXY_IP=$PROXY_IP
PROXY_HTTP_PORT=$PROXY_HTTP_PORT

# Ephemeral Port Range
PROXY_SPICE_PORT_MIN=40000
PROXY_SPICE_PORT_MAX=41000

# JWT Secret
JWT_SECRET=$JWT_SECRET

# TOTP Secrets (add via enrollment)
EOF

    echo "[OK] Configuration created: .env"
else
    echo "[INFO] Using existing .env file"
fi

# Build and start
echo ""
echo "[INFO] Building Docker image..."
docker compose build

echo "[INFO] Starting ZeroSpice server..."
docker compose up -d

echo ""
echo "============================================"
echo "ZeroSpice Server Installed"
echo "============================================"
echo ""
echo "Status: docker compose ps"
echo "Logs:   docker compose logs -f"
echo "Health: curl http://localhost/health"
echo ""
echo "Add users:"
echo "  docker compose exec zerospice python3 src/admin.py enroll-token"
echo ""
