# ZeroSpice Server

Authenticated SPICE proxy for Proxmox VMs with TOTP authentication and ephemeral port forwarding.

## Quick Install

```bash
curl -fsSL https://raw.githubusercontent.com/Jstith/zerospice/main/Server/install.sh | sudo bash
```

Or manual:

```bash
git clone https://github.com/Jstith/zerospice.git
cd zerospice/Server
sudo ./install.sh
```

## Configuration

Set environment variables or edit `.env`:

```bash
PROXMOX_IP=192.168.1.100
PROXMOX_API_TOKEN=user@pam!tokenid=uuid
PROXY_IP=0.0.0.0
PROXY_HTTP_PORT=80
JWT_SECRET=<generated>
```

## User Management

Generate enrollment token:

```bash
docker compose exec zerospice python3 src/admin.py enroll-token
```

Share URL with user. They will:
1. Enter username
2. Scan QR code with authenticator app
3. Confirm with TOTP code
4. Account activated

## API Endpoints

- `GET /health` - Health check
- `POST /login` - Authenticate (username + TOTP code)
- `GET /offer` - List VMs (authenticated)
- `GET /spice/<node>/<vmid>` - Get SPICE connection file (authenticated)
- `GET /enroll?token=XXX` - User enrollment

## Architecture

- **Ephemeral port forwarding**: Each SPICE session gets unique port (40000-41000)
- **Multi-channel support**: SPICE uses multiple TCP connections per session
- **Auto-cleanup**: Sessions expire after 5 minutes
- **TOTP authentication**: Time-based one-time passwords via authenticator apps

## Docker Commands

```bash
# Start
docker compose up -d

# Logs
docker compose logs -f

# Stop
docker compose down

# Rebuild
docker compose down && docker compose up -d --build
```

## Requirements

- Docker & Docker Compose
- Proxmox VE with API token
- Network connectivity to Proxmox (VPN recommended: Tailscale, WireGuard)
