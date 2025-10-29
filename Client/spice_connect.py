import sys
import subprocess
import tempfile
import os
import requests
import argparse
import getpass


def login(proxy_url, username, totp_code):
    url = f"{proxy_url}/login"
    try:
        response = requests.post(
            url, json={"username": username, "totp_code": totp_code}, timeout=10
        )
        response.raise_for_status()
        data = response.json()
        return data["token"]
    except requests.RequestException as e:
        print(f"Error: Authentication failed: {e}")
        if hasattr(e, "response") and e.response is not None:
            try:
                print(f"Response body: {e.response.text}")
            except:
                pass
        sys.exit(1)


def get_spice_file(proxy_url, node, vmid, token):
    url = f"{proxy_url}/spice/{node}/{vmid}"
    headers = {"Authorization": f"Bearer {token}"}
    try:
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        return response.text
    except requests.RequestException as e:
        print(f"Error: Failed to get SPICE file: {e}")
        sys.exit(1)


def launch_viewer(vv_content):
    # Debug
    print(vv_content)

    # Write to temp file
    with tempfile.NamedTemporaryFile(mode="w", suffix=".vv", delete=False) as f:
        f.write(vv_content)
        vv_file = f.name

    try:
        print("Launching SPICE viewer...")
        subprocess.run(["remote-viewer", vv_file])
    except FileNotFoundError:
        print("Error: remote-viewer not found. Install it with:")
        print("  sudo apt install virt-viewer")
        sys.exit(1)
    except KeyboardInterrupt:
        print("\nViewer closed by user")
    finally:
        try:
            os.unlink(vv_file)
        except:
            pass


def main():
    parser = argparse.ArgumentParser(
        description="Connect to a VM via Zero-Spice",
        epilog="Example: zero-spice-connect http://10.10.10.10:5000 Gormadoc pve 100",
    )
    parser.add_argument("proxy_url", help="Proxy URL (e.g. http://10.10.10.10:5000")
    parser.add_argument("username", help="Username for authentication")
    parser.add_argument("node", help="Proxmox node name (e.g., pve)")
    parser.add_argument("vmid", type=int, help="VM ID number")

    args = parser.parse_args()
    proxy_url = args.proxy_url.rstrip("/")

    try:
        totp_code = getpass.getpass(f"Enter authenticator code for {args.username}: ")
        if not len(totp_code) == 6 or not totp_code.isdigit():
            print("Error: TOTP code must be 6 digits")
            sys.exit(1)

        print("Authenticating...")
        token = login(proxy_url, args.username, totp_code)
        print("Authentication successful.")

        # Get SPICE file from proxy
        vv_content = get_spice_file(proxy_url, args.node, args.vmid, token)

        # Launch viewer
        launch_viewer(vv_content)
        print("Done")

    except KeyboardInterrupt:
        print("\n\nInterrupted by user")


if __name__ == "__main__":
    main()
