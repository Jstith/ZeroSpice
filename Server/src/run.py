import os
import threading
import sys
import signal
import time
from dotenv import load_dotenv
from spice_proxy import run_spice_proxy_server
from port_forwarder import PortForwarder

load_dotenv()
config = {
    "PVE_IP": os.getenv("PROXMOX_IP"),
    "PVE_TOKEN": os.getenv("PROXMOX_API_TOKEN"),
    "PROXY_IP": os.getenv("PROXY_IP"),
    "PROXY_HTTP_PORT": int(os.getenv("PROXY_HTTP_PORT")),
    "PROXY_SPICE_PORT": int(os.getenv("PROXY_SPICE_PORT")),
    "PVE_SPICE_PORT": 3128,  # Proxmox default, individual instances may vary
}

JWT_SECRET = os.getenv("JWT_SECRET")
if not JWT_SECRET:
    print("Error: JWT_SECRET not set in .env.\nExiting...")
    sys.exit(1)
config["JWT_SECRET"] = JWT_SECRET

USER_SECRETS = {}
for key, value in os.environ.items():
    if key.startswith("TOTP_SECRET_"):
        username = key.replace("TOTP_SECRET_", "").lower()
        USER_SECRETS[username] = value
if USER_SECRETS:
    config["USER_SECRETS"] = USER_SECRETS
    print(f"Loaded TOTP for users: {list(config['USER_SECRETS'].keys())}")

if not all(config.get(k) for k in config.keys()):
    print("Error: Missing required configuration in .env file.\nExiting...")
    sys.exit(1)

portForwarder = None


def start_port_forwarder():
    global portForwarder
    print(
        f"Starting SPICE forwarder: {config['PROXY_IP']}:{config['PROXY_SPICE_PORT']} -> {config['PVE_IP']}:{config['PVE_SPICE_PORT']}"
    )
    portForwarder = PortForwarder(
        config["PROXY_IP"],
        config["PROXY_SPICE_PORT"],
        config["PVE_IP"],
        config["PVE_SPICE_PORT"],
    )
    portForwarder.start()
    print("SPICE port forwarder running")


def start_web_server():
    print(f"Starting web server: {config['PROXY_IP']}:{config['PROXY_HTTP_PORT']}")
    web_thread = threading.Thread(target=run_spice_proxy_server, args=(config,))
    web_thread.daemon = True
    web_thread.start()
    print("Web server running")


def shutdown(signum=None, frameO=None):
    print("Shutting down gracefully...")
    sys.exit(0)


def main():
    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)

    print("SPICE Proxy Starting")
    try:
        start_port_forwarder()
        start_web_server()

        print("All services started")
        print("Press Ctrl+C to stop...")
        while True:
            time.sleep(3600)

    except KeyboardInterrupt:
        shutdown(None, None)
    except Exception as e:
        print(f"Error running spice proxy: {e}")
        shutdown(None, None)


if __name__ == "__main__":
    main()

