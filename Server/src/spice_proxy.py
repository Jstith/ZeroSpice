#!/usr/bin/env python3
"""
ZeroSpice - Authenticated SPICE Proxy Server
Combines REST API and ephemeral port forwarding in a single service.
"""

import json
import logging
import os
import secrets
import signal
import socket
import sys
import threading
import time
from datetime import datetime, timedelta, timezone
from functools import wraps

import jwt
import pyotp
import requests
import urllib3
from dotenv import load_dotenv
from flask import Flask, Response, jsonify, request

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Configure logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# Load configuration
load_dotenv()

CONFIG = {
    "PVE_IP": os.getenv("PROXMOX_IP"),
    "PVE_TOKEN": os.getenv("PROXMOX_API_TOKEN"),
    "PROXY_IP": os.getenv("PROXY_IP", "0.0.0.0"),
    "PROXY_HTTP_PORT": int(os.getenv("PROXY_HTTP_PORT", 80)),
    "PROXY_SPICE_PORT_MIN": int(os.getenv("PROXY_SPICE_PORT_MIN", 40000)),
    "PROXY_SPICE_PORT_MAX": int(os.getenv("PROXY_SPICE_PORT_MAX", 41000)),
    "PVE_SPICE_PORT": 3128,  # Proxmox default
    "JWT_SECRET": os.getenv("JWT_SECRET"),
    "SESSION_TIMEOUT": 300,  # 5 minutes (SPICE tickets expire in ~30s, buffer for multi-channel)
}

# Load TOTP secrets
USER_SECRETS = {}
for key, value in os.environ.items():
    if key.startswith("TOTP_SECRET_"):
        username = key.replace("TOTP_SECRET_", "").lower()
        USER_SECRETS[username] = value

CONFIG["USER_SECRETS"] = USER_SECRETS

# Validate configuration
if not CONFIG["JWT_SECRET"]:
    logger.error("JWT_SECRET not set in .env")
    sys.exit(1)

if not all([CONFIG["PVE_IP"], CONFIG["PVE_TOKEN"]]):
    logger.error("Missing required Proxmox configuration")
    sys.exit(1)

if not USER_SECRETS:
    logger.warning("No TOTP users configured")

logger.info(f"Loaded TOTP for users: {list(USER_SECRETS.keys())}")

# Flask app
app = Flask(__name__)

# Session manager for ephemeral forwarders
active_sessions = {}
session_lock = threading.Lock()

# Enrollment token manager
enrollment_tokens = {}
enrollment_lock = threading.Lock()
ENROLLMENT_TOKENS_FILE = ".enrollment_tokens.json"

# Pending enrollments (token -> {username, secret})
pending_enrollments = {}
pending_lock = threading.Lock()


def load_enrollment_tokens():
    """Load persistent enrollment tokens from file"""
    global enrollment_tokens

    if os.path.exists(ENROLLMENT_TOKENS_FILE):
        try:
            with open(ENROLLMENT_TOKENS_FILE, "r") as f:
                data = json.load(f)

            # Convert ISO strings back to datetime objects
            for token, info in data.items():
                enrollment_tokens[token] = {
                    "created_at": datetime.fromisoformat(info["created_at"]),
                    "expires_at": datetime.fromisoformat(info["expires_at"]),
                    "created_by": info.get("created_by", "admin"),
                    "max_uses": info.get("max_uses", 1),
                    "uses": info.get("uses", 0),
                    "enrolled_users": info.get("enrolled_users", []),
                }

            logger.info(f"Loaded {len(enrollment_tokens)} enrollment tokens from file")

            # Clean up expired tokens immediately
            cleanup_expired_tokens_once()

        except Exception as e:
            logger.error(f"Failed to load enrollment tokens: {e}")


def save_enrollment_tokens():
    """Save enrollment tokens to persistent file"""
    try:
        # Convert datetime objects to ISO strings for JSON serialization
        data = {}
        for token, info in enrollment_tokens.items():
            data[token] = {
                "created_at": info["created_at"].isoformat(),
                "expires_at": info["expires_at"].isoformat(),
                "created_by": info["created_by"],
                "max_uses": info["max_uses"],
                "uses": info["uses"],
                "enrolled_users": info["enrolled_users"],
            }

        with open(ENROLLMENT_TOKENS_FILE, "w") as f:
            json.dump(data, f, indent=2)

    except Exception as e:
        logger.error(f"Failed to save enrollment tokens: {e}")


# Load tokens on startup
load_enrollment_tokens()


# ============================================================================
# EPHEMERAL PORT FORWARDER
# ============================================================================


class EphemeralForwarder:
    """
    Single-session port forwarder that accepts multiple connections.
    Auto-terminates after timeout or when all connections close.

    SPICE protocol uses multiple TCP connections per session:
    - Main channel (session establishment)
    - Display channel (video data)
    - Inputs channel (keyboard/mouse)
    - Cursor channel (cursor position)
    - Playback/Record channels (audio)
    """

    def __init__(
        self, local_host, local_port, remote_host, remote_port, session_id, timeout=300
    ):
        self.local_host = local_host
        self.local_port = local_port
        self.remote_host = remote_host
        self.remote_port = remote_port
        self.session_id = session_id
        self.timeout = timeout
        self.server = None
        self.running = False
        self.start_time = time.time()
        self.active_connections = 0
        self.connection_lock = threading.Lock()

    def start(self):
        """Start the forwarder in a background thread"""
        self.running = True

        # Bind to the ephemeral port
        self.server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.server.bind((self.local_host, self.local_port))
        self.server.listen(10)
        self.server.settimeout(1.0)  # Allow periodic timeout checks

        logger.info(
            f"Session {self.session_id}: Forwarder started on "
            f"{self.local_host}:{self.local_port} -> "
            f"{self.remote_host}:{self.remote_port}"
        )

        # Accept loop in background thread
        accept_thread = threading.Thread(target=self._accept_loop, daemon=True)
        accept_thread.start()

    def _accept_loop(self):
        """Accept connections until timeout or stopped"""
        while self.running:
            # Check if we've exceeded timeout
            if time.time() - self.start_time > self.timeout:
                logger.info(f"Session {self.session_id}: Timeout after {self.timeout}s")
                self.stop()
                break

            try:
                client, addr = self.server.accept()
                logger.info(f"Session {self.session_id}: Connection from {addr}")

                with self.connection_lock:
                    self.active_connections += 1

                # Handle connection in separate thread
                conn_thread = threading.Thread(
                    target=self._forward_connection, args=(client, addr), daemon=True
                )
                conn_thread.start()

            except socket.timeout:
                # Normal timeout for periodic checks
                continue
            except Exception as e:
                if self.running:
                    logger.error(f"Session {self.session_id}: Accept error: {e}")
                break

        # Cleanup when accept loop exits
        self._cleanup()

    def _forward_connection(self, client_sock, client_addr):
        """Forward a single connection bidirectionally"""
        remote_sock = None
        try:
            # Connect to Proxmox SPICE port
            remote_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            remote_sock.connect((self.remote_host, self.remote_port))

            logger.debug(
                f"Session {self.session_id}: Forwarding {client_addr} -> "
                f"{self.remote_host}:{self.remote_port}"
            )

            # Bidirectional forwarding
            def forward(src, dst, direction):
                try:
                    while self.running:
                        data = src.recv(8192)
                        if not data:
                            break
                        dst.sendall(data)
                except Exception as e:
                    logger.debug(f"Session {self.session_id}: {direction} error: {e}")
                finally:
                    try:
                        src.close()
                    except:
                        pass
                    try:
                        dst.close()
                    except:
                        pass

            # Start bidirectional forwarding threads
            t1 = threading.Thread(
                target=forward,
                args=(client_sock, remote_sock, "client->remote"),
                daemon=True,
            )
            t2 = threading.Thread(
                target=forward,
                args=(remote_sock, client_sock, "remote->client"),
                daemon=True,
            )

            t1.start()
            t2.start()
            t1.join()
            t2.join()

        except Exception as e:
            logger.error(f"Session {self.session_id}: Forward error: {e}")
        finally:
            if remote_sock:
                try:
                    remote_sock.close()
                except:
                    pass
            try:
                client_sock.close()
            except:
                pass

            with self.connection_lock:
                self.active_connections -= 1

            logger.debug(
                f"Session {self.session_id}: Connection closed, "
                f"active: {self.active_connections}"
            )

    def stop(self):
        """Stop accepting new connections"""
        self.running = False
        if self.server:
            try:
                self.server.close()
            except:
                pass

    def _cleanup(self):
        """Cleanup and remove from session manager"""
        logger.info(
            f"Session {self.session_id}: Cleanup (duration: "
            f"{int(time.time() - self.start_time)}s)"
        )

        with session_lock:
            if self.session_id in active_sessions:
                del active_sessions[self.session_id]


# ============================================================================
# SESSION MANAGER
# ============================================================================


def allocate_ephemeral_port():
    """Allocate a random port from the ephemeral range"""
    for _ in range(100):  # Try 100 times
        port = (
            secrets.randbelow(
                CONFIG["PROXY_SPICE_PORT_MAX"] - CONFIG["PROXY_SPICE_PORT_MIN"]
            )
            + CONFIG["PROXY_SPICE_PORT_MIN"]
        )

        # Check if port is available
        if port not in [s["forwarder"].local_port for s in active_sessions.values()]:
            return port

    raise RuntimeError("No available ephemeral ports")


def create_session(node, vmid, username):
    """Create a new ephemeral forwarding session"""
    session_id = secrets.token_urlsafe(16)

    with session_lock:
        # Allocate ephemeral port
        ephemeral_port = allocate_ephemeral_port()

        # Create forwarder
        forwarder = EphemeralForwarder(
            local_host=CONFIG["PROXY_IP"],
            local_port=ephemeral_port,
            remote_host=CONFIG["PVE_IP"],
            remote_port=CONFIG["PVE_SPICE_PORT"],
            session_id=session_id,
            timeout=CONFIG["SESSION_TIMEOUT"],
        )

        # Start forwarder
        forwarder.start()

        # Track session
        active_sessions[session_id] = {
            "forwarder": forwarder,
            "node": node,
            "vmid": vmid,
            "username": username,
            "created_at": datetime.now(timezone.utc),
            "ephemeral_port": ephemeral_port,
        }

        logger.info(
            f"Session {session_id}: Created for user {username} -> "
            f"{node}/VM{vmid} on port {ephemeral_port}"
        )

        return session_id, ephemeral_port


def cleanup_expired_sessions():
    """Background task to cleanup expired sessions"""
    while True:
        time.sleep(60)  # Check every minute

        with session_lock:
            expired = []
            for session_id, session_info in active_sessions.items():
                age = (
                    datetime.now(timezone.utc) - session_info["created_at"]
                ).total_seconds()
                if age > CONFIG["SESSION_TIMEOUT"]:
                    expired.append(session_id)

            for session_id in expired:
                logger.info(f"Session {session_id}: Expired, cleaning up")
                session_info = active_sessions[session_id]
                session_info["forwarder"].stop()
                del active_sessions[session_id]


# Start cleanup thread
cleanup_thread = threading.Thread(target=cleanup_expired_sessions, daemon=True)
cleanup_thread.start()


# ============================================================================
# ENROLLMENT TOKEN SYSTEM
# ============================================================================


def generate_enrollment_token(created_by="admin", expires_hours=24, max_uses=1):
    """
    Generate a one-time enrollment token for user self-enrollment.

    Similar to Tailscale's auth key system - admin generates token,
    user pastes it to enroll themselves.
    """
    token = secrets.token_urlsafe(32)

    with enrollment_lock:
        enrollment_tokens[token] = {
            "created_at": datetime.now(timezone.utc),
            "expires_at": datetime.now(timezone.utc) + timedelta(hours=expires_hours),
            "created_by": created_by,
            "max_uses": max_uses,
            "uses": 0,
            "enrolled_users": [],
        }

    logger.info(
        f"Enrollment token generated by {created_by}, expires in {expires_hours}h"
    )
    return token


def validate_enrollment_token(token):
    """Check if enrollment token is valid and not expired/exhausted"""
    with enrollment_lock:
        if token not in enrollment_tokens:
            return False, "Invalid token"

        token_info = enrollment_tokens[token]

        # Check expiration
        if datetime.now(timezone.utc) > token_info["expires_at"]:
            return False, "Token expired"

        # Check usage limit
        if token_info["uses"] >= token_info["max_uses"]:
            return False, "Token already used"

        return True, "Valid"


def consume_enrollment_token(token, username):
    """Mark token as used for a specific username"""
    with enrollment_lock:
        if token in enrollment_tokens:
            enrollment_tokens[token]["uses"] += 1
            enrollment_tokens[token]["enrolled_users"].append(
                {
                    "username": username,
                    "enrolled_at": datetime.now(timezone.utc).isoformat(),
                }
            )

            # Remove token if exhausted
            if enrollment_tokens[token]["uses"] >= enrollment_tokens[token]["max_uses"]:
                logger.info(f"Enrollment token exhausted, removing")
                del enrollment_tokens[token]

            # Save updated tokens
            save_enrollment_tokens()


def cleanup_expired_tokens_once():
    """Clean up expired tokens once (called on startup)"""
    with enrollment_lock:
        expired = []
        for token, info in enrollment_tokens.items():
            if datetime.now(timezone.utc) > info["expires_at"]:
                expired.append(token)

        for token in expired:
            logger.info(f"Removing expired enrollment token")
            del enrollment_tokens[token]

        if expired:
            save_enrollment_tokens()


def cleanup_expired_tokens():
    """Background task to cleanup expired enrollment tokens"""
    while True:
        time.sleep(3600)  # Check every hour

        with enrollment_lock:
            expired = []
            for token, info in enrollment_tokens.items():
                if datetime.now(timezone.utc) > info["expires_at"]:
                    expired.append(token)

            for token in expired:
                logger.info(f"Removing expired enrollment token")
                del enrollment_tokens[token]

            if expired:
                save_enrollment_tokens()


# Start token cleanup thread
token_cleanup_thread = threading.Thread(target=cleanup_expired_tokens, daemon=True)
token_cleanup_thread.start()


# ============================================================================
# AUTHENTICATION
# ============================================================================


def require_auth(f):
    """Decorator to require JWT authentication"""

    @wraps(f)
    def decorated(*args, **kwargs):
        auth_header = request.headers.get("Authorization", "")

        if not auth_header.startswith("Bearer "):
            return jsonify({"error": "No token provided"}), 401

        token = auth_header.replace("Bearer ", "")
        try:
            payload = jwt.decode(token, CONFIG["JWT_SECRET"], algorithms=["HS256"])
            request.user = payload["user"]
            return f(*args, **kwargs)
        except jwt.ExpiredSignatureError:
            logger.warning("Expired token used")
            return jsonify({"error": "Token expired"}), 401
        except jwt.InvalidTokenError:
            logger.warning("Invalid token used")
            return jsonify({"error": "Invalid token"}), 401

    return decorated


@app.route("/login", methods=["POST"])
def login():
    """Authenticate with username and TOTP code"""
    username = request.json.get("username")
    totp_code = request.json.get("totp_code")

    if not username or not totp_code:
        return jsonify({"error": "Invalid credentials"}), 401

    secret = CONFIG["USER_SECRETS"].get(username.lower())
    if not secret:
        logger.warning(f"Login attempt for unknown user: {username}")
        return jsonify({"error": "Invalid credentials"}), 401

    totp = pyotp.TOTP(secret)
    if not totp.verify(totp_code, valid_window=1):
        logger.warning(f"Invalid TOTP code for user: {username}")
        return jsonify({"error": "Invalid code"}), 401

    token = jwt.encode(
        {
            "user": username,
            "exp": datetime.now(timezone.utc) + timedelta(minutes=15),
        },
        CONFIG["JWT_SECRET"],
        algorithm="HS256",
    )

    logger.info(
        f"User {username} authenticated successfully from {request.remote_addr}"
    )
    return jsonify({"token": token, "user": username})


@app.route("/refresh", methods=["POST"])
@require_auth
def refresh():
    """Refresh JWT token"""
    new_token = jwt.encode(
        {
            "user": request.user,
            "exp": datetime.now(timezone.utc) + timedelta(minutes=15),
        },
        CONFIG["JWT_SECRET"],
        algorithm="HS256",
    )

    logger.info(f"Token refreshed for user {request.user}")
    return jsonify({"token": new_token})


# ============================================================================
# PROXMOX INTEGRATION
# ============================================================================

VV_FILE_FIELDS = [
    "release-cursor",
    "proxy",
    "secure-attention",
    "host-subject",
    "ca",
    "delete-this-file",
    "type",
    "title",
    "tls-port",
    "toggle-fullscreen",
    "host",
    "password",
]


def get_proxmox_vms():
    """Get list of VMs from Proxmox"""
    nodes_url = f"https://{CONFIG['PVE_IP']}:8006/api2/json/nodes"
    headers = {"Authorization": f"PVEAPIToken={CONFIG['PVE_TOKEN']}"}

    r = requests.get(nodes_url, headers=headers, verify=False)
    nodes = r.json()["data"]

    guests = []
    for node in nodes:
        node_name = node["node"]

        qemu_url = f"https://{CONFIG['PVE_IP']}:8006/api2/json/nodes/{node_name}/qemu"
        qemu_r = requests.get(qemu_url, headers=headers, verify=False)
        qemu_data = qemu_r.json()["data"]

        for vm in qemu_data:
            guests.append(
                {
                    "type": "qemu",
                    "node": node_name,
                    "name": vm.get("name", f"vm-{vm['vmid']}"),
                    "vmid": vm["vmid"],
                    "status": vm.get("status", "unknown"),
                }
            )

    return guests


def generate_spice_file(node, vmid, ephemeral_port):
    """Generate SPICE .vv file with ephemeral port"""
    url = (
        f"https://{CONFIG['PVE_IP']}:8006/api2/json/nodes/{node}/qemu/{vmid}/spiceproxy"
    )
    headers = {"Authorization": f"PVEAPIToken={CONFIG['PVE_TOKEN']}"}

    r = requests.post(url, headers=headers, verify=False)
    data = r.json()["data"]

    vv = ["[virt-viewer]"]
    for key in VV_FILE_FIELDS:
        if key not in data:
            continue
        val = data[key]

        # Override proxy to point to ephemeral port
        if key == "proxy":
            val = f"http://{CONFIG['PROXY_IP']}:{ephemeral_port}"

        vv.append(f"{key}={val}")

    return "\n".join(vv)


# ============================================================================
# REST API ENDPOINTS
# ============================================================================


@app.route("/health")
def health():
    """Health check endpoint"""
    return jsonify({"status": "ok", "active_sessions": len(active_sessions)})


@app.route("/offer")
@require_auth
def offer():
    """List available VMs"""
    logger.info(f"User {request.user} requested VM list")
    try:
        offers = get_proxmox_vms()
        return jsonify(offers), 200
    except Exception as e:
        logger.error(f"Failed to get VM list: {e}")
        return jsonify({"error": "Unable to retrieve VMs"}), 500


@app.route("/spice/<node>/<int:vmid>")
@require_auth
def spice_file(node, vmid):
    """Generate SPICE .vv file with ephemeral port forwarder"""
    logger.info(f"User {request.user} requested SPICE for {node}/VM{vmid}")

    try:
        # Create ephemeral session
        session_id, ephemeral_port = create_session(node, vmid, request.user)

        # Generate SPICE file pointing to ephemeral port
        vv_file = generate_spice_file(node, vmid, ephemeral_port)

        logger.info(
            f"SPICE file generated for {node}/VM{vmid} by {request.user} "
            f"(session: {session_id}, port: {ephemeral_port})"
        )

        return Response(
            vv_file,
            mimetype="application/x-virt-viewer",
            headers={"Content-Disposition": f"attachment; filename=spice-{vmid}.vv"},
        ), 200

    except Exception as e:
        logger.error(f"Error generating SPICE file: {e}")
        return jsonify({"error": "Error generating SPICE file"}), 500


@app.route("/sessions")
@require_auth
def list_sessions():
    """List active sessions (admin endpoint)"""
    sessions = []
    with session_lock:
        for session_id, info in active_sessions.items():
            sessions.append(
                {
                    "session_id": session_id,
                    "username": info["username"],
                    "node": info["node"],
                    "vmid": info["vmid"],
                    "ephemeral_port": info["ephemeral_port"],
                    "created_at": info["created_at"].isoformat(),
                    "active_connections": info["forwarder"].active_connections,
                }
            )

    return jsonify(sessions), 200


@app.route("/admin/generate-token", methods=["POST"])
def admin_generate_token():
    """
    Admin endpoint to generate enrollment tokens.
    No auth required - only accessible from localhost (Docker exec).
    """
    # Only allow from localhost for security
    if request.remote_addr not in ["127.0.0.1", "::1", "localhost"]:
        return jsonify({"error": "Forbidden"}), 403

    data = request.json or {}
    expires_hours = data.get("expires_hours", 24)
    max_uses = data.get("max_uses", 1)

    token = generate_enrollment_token(
        created_by="admin", expires_hours=expires_hours, max_uses=max_uses
    )

    token_info = enrollment_tokens[token]

    return jsonify(
        {
            "token": token,
            "expires_at": token_info["expires_at"].isoformat(),
            "max_uses": token_info["max_uses"],
        }
    ), 201


# ============================================================================
# ENROLLMENT ENDPOINTS
# ============================================================================


@app.route("/enroll", methods=["GET"])
def enroll_check():
    """Check if enrollment token is valid (before showing form)"""
    token = request.args.get("token", "")

    if not token:
        return jsonify({"error": "No token provided"}), 400

    valid, message = validate_enrollment_token(token)

    if not valid:
        return jsonify({"error": message, "valid": False}), 400

    return jsonify(
        {"valid": True, "message": "Token is valid. Proceed with enrollment."}
    ), 200


@app.route("/enroll", methods=["POST"])
def enroll_user():
    """
    Self-enrollment endpoint - user provides token and desired username,
    receives TOTP secret and QR code.

    Flow:
    1. Admin generates token: docker compose exec zerospice python3 src/admin.py enroll-token
    2. Admin shares token with user (Signal, in-person, etc.)
    3. User visits: https://server/enroll?token=XXX
    4. User enters username and confirms
    5. Server generates TOTP secret, returns QR code
    6. User scans QR with authenticator app
    7. User confirms TOTP works by submitting first code
    8. Account is activated
    """
    data = request.json
    token = data.get("token", "")
    username = data.get("username", "").strip().lower()
    totp_confirmation = data.get(
        "totp_code", ""
    )  # Optional: verify user can generate codes

    # Validate input
    if not token or not username:
        return jsonify({"error": "Token and username required"}), 400

    if not username.isalnum() or len(username) < 3 or len(username) > 32:
        return jsonify({"error": "Username must be 3-32 alphanumeric characters"}), 400

    # Check if username already exists
    if username in CONFIG["USER_SECRETS"]:
        return jsonify({"error": "Username already exists"}), 409

    # Validate enrollment token
    valid, message = validate_enrollment_token(token)
    if not valid:
        return jsonify({"error": message}), 403

    # If TOTP confirmation provided, verify it works
    if totp_confirmation:
        # Look up the pending enrollment
        with pending_lock:
            pending = pending_enrollments.get(token)

        if not pending or pending["username"] != username:
            return jsonify(
                {"error": "No pending enrollment found. Please start over."}
            ), 400

        secret = pending["secret"]
        totp = pyotp.TOTP(secret)

        if not totp.verify(totp_confirmation, valid_window=1):
            return jsonify(
                {
                    "error": "Invalid TOTP code. Please try again.",
                    "step": "confirmation",
                }
            ), 400

        # TOTP confirmed, activate user
        _add_user_to_config(username, secret)
        consume_enrollment_token(token, username)

        # Clean up pending enrollment
        with pending_lock:
            if token in pending_enrollments:
                del pending_enrollments[token]

        logger.info(f"User {username} enrolled successfully via token")

        return jsonify(
            {
                "status": "enrolled",
                "username": username,
                "message": "Account activated! You can now login.",
            }
        ), 201

    # First step: Generate TOTP secret and store it
    secret = pyotp.random_base32()
    totp = pyotp.TOTP(secret)

    # Store in pending enrollments
    with pending_lock:
        pending_enrollments[token] = {
            "username": username,
            "secret": secret,
            "created_at": datetime.now(timezone.utc),
        }

    provisioning_uri = totp.provisioning_uri(name=username, issuer_name="ZeroSpice")

    return jsonify(
        {
            "status": "pending_confirmation",
            "username": username,
            "secret": secret,
            "provisioning_uri": provisioning_uri,
            "message": "Scan QR code with your authenticator app, then submit a TOTP code to confirm.",
        }
    ), 200


def _add_user_to_config(username, secret):
    """Add user to runtime config and persist to .env"""
    # Add to runtime
    CONFIG["USER_SECRETS"][username] = secret

    # Persist to .env file
    env_key = f"TOTP_SECRET_{username.upper()}"
    env_line = f"{env_key}={secret}"

    try:
        with open(".env", "a") as f:
            f.write(f"\n{env_line}\n")
        logger.info(f"Added user {username} to .env file")
    except Exception as e:
        logger.error(f"Failed to persist user to .env: {e}")
        # Rollback runtime addition
        del CONFIG["USER_SECRETS"][username]
        raise


# ============================================================================
# MAIN ENTRY POINT
# ============================================================================


def shutdown_handler(signum=None, frame=None):
    """Graceful shutdown handler"""
    logger.info("Shutting down gracefully...")

    # Stop all active forwarders
    with session_lock:
        for session_id, session_info in list(active_sessions.items()):
            logger.info(f"Stopping session {session_id}")
            session_info["forwarder"].stop()

    sys.exit(0)


if __name__ == "__main__":
    # Register signal handlers
    signal.signal(signal.SIGTERM, shutdown_handler)
    signal.signal(signal.SIGINT, shutdown_handler)

    logger.info("=" * 60)
    logger.info("ZeroSpice Server Starting")
    logger.info("=" * 60)
    logger.info(f"Bind address: {CONFIG['PROXY_IP']}")
    logger.info(f"HTTP port: {CONFIG['PROXY_HTTP_PORT']}")
    logger.info(
        f"Ephemeral port range: {CONFIG['PROXY_SPICE_PORT_MIN']}-{CONFIG['PROXY_SPICE_PORT_MAX']}"
    )
    logger.info(f"Session timeout: {CONFIG['SESSION_TIMEOUT']}s")
    logger.info(f"Configured users: {list(USER_SECRETS.keys())}")
    logger.info("=" * 60)

    # Run Flask app
    app.run(
        debug=False,
        host=CONFIG["PROXY_IP"],
        port=CONFIG["PROXY_HTTP_PORT"],
        threaded=True,
    )
