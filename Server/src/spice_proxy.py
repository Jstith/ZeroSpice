import pyotp
import jwt
from datetime import datetime, timezone, timedelta
from functools import wraps
import secrets
import logging
import urllib3
import requests
import threading
from flask import Flask, Response, jsonify, request
from port_forwarder import PortForwarder

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

CONFIG = {}
ALLOWED_NODES = ["pve"]
ALLOWED_VMS = [11010]
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

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

### ----------------------
### Authentication Methods
### ----------------------


def require_auth(f):
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


### ----------------
### Helper Methods
### ----------------


def validate_requested_machine(node, vmid):
    if node in ALLOWED_NODES and vmid in ALLOWED_VMS:
        return True
    return False


def generate_spice_file(node, vmid):
    pve_ip = CONFIG["PVE_IP"]
    pve_token = CONFIG["PVE_TOKEN"]
    proxy_ip = CONFIG["PROXY_IP"]
    proxy_port = CONFIG["PROXY_SPICE_PORT"]

    url = f"https://{pve_ip}:8006/api2/json/nodes/{node}/qemu/{vmid}/spiceproxy"
    headers = {"Authorization": f"PVEAPIToken={pve_token}"}
    r = requests.post(url, headers=headers, verify=False)
    data = r.json()["data"]
    vv = ["[virt-viewer]"]
    for key in VV_FILE_FIELDS:
        if key not in data:
            continue
        val = data[key]
        if key == "proxy":
            val = f"http://{proxy_ip}:{proxy_port}"
        # elif key == "host":
        #     val = CONFIG["PROXY_IP"]
        # elif key == "tls-port":
        #     vv.append(f"port={ticket_port}")
        #     continue
        vv.append(f"{key}={val}")
    return "\n".join(vv)


def get_offer():
    pve_ip = CONFIG["PVE_IP"]
    pve_token = CONFIG["PVE_TOKEN"]

    nodes_url = f"https://{pve_ip}:8006/api2/json/nodes"
    headers = {"Authorization": f"PVEAPIToken={pve_token}"}
    r = requests.get(nodes_url, headers=headers, verify=False)
    nodes = r.json()["data"]

    guests = []
    for node in nodes:
        node_name = node["node"]

        qemu_url = f"https://{pve_ip}:8006/api2/json/nodes/{node_name}/qemu"
        qemu_r = requests.get(qemu_url, headers=headers, verify=False)
        qemu_data = qemu_r.json()["data"]

        for vm in qemu_data:
            guests.append(
                {
                    "type": "qemu",
                    "node": node_name,
                    "name": vm.get("name", f"vm-{vm['vmid']}"),
                    "vmid": vm["vmid"],
                }
            )
    return guests


### ---------------
### Flask Functions
### ---------------


@app.route("/health")
def health():
    return jsonify({"status": "ok"})


@app.route("/offer")
@require_auth
def offer():
    logger.info(f"Request received for offers")
    try:
        offers = get_offer()
        return jsonify(offers), 200
    except:
        logger.info("Failed to receive offers")
        return jsonify({"Error": "Unable to receive offers"}), 400


@app.route("/spice/<node>/<int:vmid>")
@require_auth
def spicy(node, vmid):
    logger.info(f"Request received for node {node} vmid {vmid}")

    # Validate authorized Vm requested
    if not validate_requested_machine(node, vmid):
        return jsonify(
            {"Error": "Requested node / vmid is either invalid or unauthorized"}, 400
        )

    # Generate spice file and return to sender
    try:
        vv_file = generate_spice_file(node, vmid)
        logger.info(
            f"Spice file generated for node {node} vmid {vmid} by {request.remote_addr}"
        )
        return Response(
            vv_file,
            mimetype="application/x-virt-viewer",
            headers={"Content-Disposition": f"attachment; filename=spice-{vmid}.vv"},
        ), 200
    except Exception as e:
        logger.error(f"Error generating and returning spice file: {e}")
        return jsonify({"Error": "Error while generating spice file"}), 400


def run_spice_proxy_server(config):
    global CONFIG
    CONFIG = config
    logger.info(
        f"Running spice proxy on interface {config['PROXY_IP']} and port {config['PROXY_HTTP_PORT']}"
    )
    app.run(
        debug=False,
        host=config["PROXY_IP"],
        port=config["PROXY_HTTP_PORT"],
        threaded=True,
    )

