# ZeroSpice Installation Guide

ZeroSpice enables secure remote access to Proxmox VMs via SPICE protocol over a VPN network (Tailscale, WireGuard, etc.). This guide walks you through setting up both the server and client components.

## Architecture Overview
```
   Proxmox VE            ZeroSpice Server       ZeroSpice Client
┌───────────────┐       ┌───────────────┐       ┌───────────────┐
│ LAN Interface │       │ LAN Interface │       │               │
│  (Rest API)   │<------│(HTTP Request) │       │               │
│               │       │               │       │               │
│ (SPICE port)  │<----->│ VPN Interface │<----->│ VPN Interface │
│               │       │ (Docker)      │       │ (GUI Client)  │
└───────────────┘       └───────────────┘       └───────────────┘
              (LAN Traffic)            (VPN Traffic)
```

## Prerequisites

- **Client Requirements**:
  - Python 3.10+
  - virt-viewer application
  - VPN connection (Tailscale recommended, or WireGuard/OpenVPN)

- **Server Requirements**:
  - Linux (Ubuntu 20.04+ recommended)
  - Docker & Docker Compose
  - Network access to Proxmox (typically same LAN)
  - VPN connection (Tailscale recommended)

- **Proxmox Requirements**:
  - Proxmox VE 7.0+
  - API access credentials
  - VMs configured with SPICE display

---

## Installation Steps

### Step 1: Enable SPICE on Proxmox VMs

**Option A: Via Proxmox Web UI**

1. Select your VM in the Proxmox web interface
2. Go to **Hardware** tab
3. Double-click on **Display**
4. Change display type to **SPICE**
5. Click **OK** to save

**Option B: Via Command Line**
```bash
qm set <vmid> --vga qxl
```

---

### Step 2: Create Proxmox API User and Token

#### 2.1 Create a User

1. Log into Proxmox web interface
2. Navigate to **Datacenter** → **Permissions** → **Users**
3. Click **Add** to create a new user:
   - **User name**: `zerospice`
   - **Realm**: `pve` (default)
4. Click **Add**

#### 2.2 Create an API Token

1. Navigate to **Datacenter** → **Permissions** → **API Tokens**
2. Click **Add**
3. Configure the token:
   - **User**: `zerospice@pve`
   - **Token ID**: `zerospice-token`
   - **Privilege Separation**: Uncheck
4. Click **Add**
5. Copy the displayed token value

Token format: `zerospice@pve!zerospice-token=xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx`

#### 2.3 Set Permissions

**Via Proxmox Web UI:**

1. Navigate to **Datacenter** → **Permissions**
2. Add permission:
  - Path: Select the VM(s) to access
  - User: Select your API user
  - Role: `PVEVMUser`

**Via Command Line:**
```bash
pveum acl modify / -user zerospice@pve -role PVEVMUser
```

---

### Step 3: Install VPN (Tailscale Recommended)

ZeroSpice server should be accessible via VPN for security. In a later build, Tailscale will be natively integrated. For now, it must be installed manually on the server.

**Install Tailscale:**
```bash
# Install Tailscale
curl -fsSL https://tailscale.com/install.sh | sh

# Connect to Tailscale
sudo tailscale up

# Note your Tailscale IP
tailscale ip -4
```

For local use, you may skip the VPN installation and bind the server to local interface(s) during the server install script.

---

### Step 4: Install ZeroSpice Server

#### Quick Install (curl | sh):
```bash
curl -fsSL https://raw.githubusercontent.com/yourusername/zerospice/main/Server/install.sh | sudo bash
```

#### Manual Install:
```bash
git clone https://github.com/yourusername/zerospice.git
cd zerospice/Server
sudo ./install.sh
```

#### Configuration

The installer will prompt for:

| Prompt | Description | Example |
|--------|-------------|---------|
| **Network Mode** | Tailscale/local/custom | Tailscale |
| **Proxmox IP** | Proxmox host IP | `192.168.1.100` |
| **Proxmox API Token** | Full API token | `zerospice@pve!zerospice-token=xxx...` |
| **HTTP Port** | REST API port | `80` (default) |

The installer will:
- Create `.env` configuration
- Build Docker image
- Start the service

---

### Step 5: Add Users via Enrollment

ZeroSpice uses enrollment tokens for user self-registration (similar to Tailscale auth keys).

#### Generate Enrollment Token

```bash
docker compose exec zerospice python3 src/admin.py enroll-token
```

Output:
```
Enrollment URL:
  http://your-server/enroll?token=abc123...
```

#### Share Token with User

Send the enrollment URL via secure channel (Signal, in-person, etc.).

#### User Enrollment Process

1. User opens enrollment URL
2. Enters desired username
3. Scans QR code with authenticator app (Google Authenticator, Authy, etc.)
4. Enters first TOTP code to confirm
5. Account activated immediately

---

### Step 6: Verify Server

```bash
# Check status
docker compose ps

# View logs
docker compose logs -f

# Test health endpoint
curl http://localhost/health
```

---

### Step 7: Install Client Application

#### Install Dependencies

```bash
git clone https://github.com/yourusername/zerospice.git
cd zerospice/Client
pip install -r requirements.txt
```

#### Install virt-viewer

**Ubuntu/Debian:**
```bash
sudo apt install virt-viewer
```

**macOS:**
```bash
brew install virt-viewer
```

#### Connect to VPN

Ensure client can reach the server (recommended to use Tailscale or local network access).

---

### Step 8: Connect to VM

#### Launch Client

```bash
python3 ZeroSpice.py
```

#### Connect

1. Enter server URL (VPN IP): `http://10.x.x.x`
2. Click "Enroll Account" (first time only)
   - Paste enrollment token
   - Choose username
   - Scan QR code
   - Confirm with TOTP
3. Click "Login & Get VMs"
   - Enter username
   - Enter TOTP code from authenticator app
4. Select VM from list
5. Click to connect

---

## Troubleshooting

### Server Won't Start
```bash
docker compose logs -f
```

### Cannot Connect to Server
```bash
# Test VPN connectivity
ping <server-vpn-ip>

# Test server port
curl http://<server-vpn-ip>/health
```

### TOTP Authentication Fails

- Verify time synchronization (TOTP requires accurate time)
- Try next TOTP code (they change every 30 seconds)
- Ensure username is correct

### VM Connection Issues

- Verify SPICE is enabled on the VM
- Check Proxmox API token permissions
- Ensure VM is running

---

## Management Commands

```bash
# Server status
docker compose ps

# View logs
docker compose logs -f

# Restart server
docker compose restart

# Stop server
docker compose down

# Rebuild (after code changes)
docker compose down && docker compose up -d --build

# Generate enrollment token
docker compose exec zerospice python3 src/admin.py enroll-token

# View active sessions
curl -H "Authorization: Bearer <token>" http://localhost/sessions
```

---

## Security Notes

- Enrollment tokens expire after 24 hours by default and are single-use
- TOTP provides time-based authentication
- JWT tokens expire after 15 minutes
- Each SPICE session gets unique ephemeral port (40000-41000)
- Sessions auto-cleanup after 5 minutes
