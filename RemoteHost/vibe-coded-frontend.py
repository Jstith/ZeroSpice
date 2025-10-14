import customtkinter as ctk
import requests
import json
import threading
import time
from datetime import datetime
from pathlib import Path


class LoginDialog(ctk.CTkToplevel):
    """TOTP login dialog"""

    def __init__(self, parent, proxy_url, on_success):
        super().__init__(parent)

        self.proxy_url = proxy_url
        self.on_success = on_success

        self.title("Zero-Spice Login")
        self.geometry("400x350")  # Taller to fit error messages
        self.resizable(False, False)

        # Make modal
        self.transient(parent)

        # Wait for window to be visible before grabbing
        self.after(100, self._grab_focus)

        # Title
        ctk.CTkLabel(
            self,
            text="Authentication Required",
            font=ctk.CTkFont(size=18, weight="bold"),
        ).pack(pady=20)

        # Username
        ctk.CTkLabel(self, text="Username:").pack(pady=(10, 5))
        self.username_entry = ctk.CTkEntry(self, width=300)
        self.username_entry.pack(pady=(0, 10))

        # TOTP Code
        ctk.CTkLabel(self, text="Authenticator Code:").pack(pady=(10, 5))
        self.totp_entry = ctk.CTkEntry(
            self, width=300, placeholder_text="6-digit code from app"
        )
        self.totp_entry.pack(pady=(0, 15))

        # Submit on Enter
        self.totp_entry.bind("<Return>", lambda e: self.do_login())

        # Login button
        self.login_btn = ctk.CTkButton(
            self, text="Login", command=self.do_login, width=200, height=35
        )
        self.login_btn.pack(pady=15)

        # Status label with more space
        self.status_label = ctk.CTkLabel(
            self,
            text="",
            text_color="gray",
            wraplength=350,  # Wrap long messages
            height=40,  # Reserve space for 2 lines
        )
        self.status_label.pack(pady=10, padx=20)

    def _grab_focus(self):
        """Grab focus after window is visible"""
        try:
            self.grab_set()
            self.username_entry.focus()
        except:
            # If still not ready, try again
            self.after(50, self._grab_focus)

    def do_login(self):
        """Attempt login"""
        username = self.username_entry.get().strip()
        totp_code = self.totp_entry.get().strip()

        if not username:
            self.status_label.configure(text="Please enter username", text_color="red")
            return

        if not totp_code or len(totp_code) != 6:
            self.status_label.configure(
                text="Please enter 6-digit code", text_color="red"
            )
            return

        self.status_label.configure(text="Authenticating...", text_color="orange")
        self.login_btn.configure(state="disabled")

        try:
            response = requests.post(
                f"{self.proxy_url}/login",
                json={"username": username, "totp_code": totp_code},
                timeout=5,
            )

            if response.status_code == 200:
                data = response.json()
                self.on_success(data["token"], data["user"])
                self.destroy()
            else:
                error = response.json().get("error", "Authentication failed")
                self.status_label.configure(text=error, text_color="red")
                self.login_btn.configure(state="normal")
                self.totp_entry.delete(0, "end")
                self.totp_entry.focus()

        except requests.exceptions.ConnectionError:
            self.status_label.configure(
                text="Cannot connect to proxy server", text_color="red"
            )
            self.login_btn.configure(state="normal")
        except Exception as e:
            self.status_label.configure(text=f"Error: {str(e)}", text_color="red")
            self.login_btn.configure(state="normal")


class SpiceProxyApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("Zero-Spice Remote Access")
        self.geometry("600x600")

        # Auth state
        self.token = None
        self.username = None
        self.running = False
        self.refresh_thread = None

        top_frame = ctk.CTkFrame(self)
        top_frame.pack(pady=20, padx=20, fill="x")

        # Build top half of UI
        top_frame.grid_columnconfigure(0, weight=1)
        top_frame.grid_columnconfigure(1, weight=1)
        top_frame.grid_columnconfigure(2, weight=1)

        ctk.CTkLabel(top_frame, text="Proxy Server URL:").grid(
            row=1, column=0, padx=10, pady=10, sticky="e"
        )

        self.proxy_entry = ctk.CTkEntry(
            top_frame, placeholder_text="http://10.10.10.10:8000", width=200
        )
        self.proxy_entry.grid(row=1, column=1, padx=10, pady=10, sticky="w")

        self.config = load_config()
        saved_url = self.config.get("proxy_url", "")
        if saved_url:
            self.proxy_entry.insert(0, saved_url)

        self.get_vm_button = ctk.CTkButton(
            top_frame, text="Login & Get VMs", command=self.check_server
        )
        self.get_vm_button.grid(row=1, column=2, padx=10, pady=10)

        # Middle panel
        middle_frame = ctk.CTkFrame(self)
        middle_frame.pack(pady=10, padx=20, fill="both", expand=True)

        ctk.CTkLabel(middle_frame, text="Available VMs:").pack(pady=5)
        self.vm_list = ctk.CTkScrollableFrame(middle_frame, height=50)
        self.vm_list.pack(fill="both", expand=True, padx=10, pady=5)

        # Console output
        console_frame = ctk.CTkFrame(self)
        console_frame.pack(pady=10, padx=20, fill="x")
        console_label = ctk.CTkLabel(
            console_frame, text="Console > ", font=ctk.CTkFont(size=12, weight="bold")
        )
        console_label.pack(anchor="w", padx=5)

        self.console_output = ctk.CTkTextbox(
            console_frame, height=100, state="disabled"
        )
        self.console_output.pack(fill="x", padx=5, pady=5)

    def console_print(self, message):
        """Print to console"""
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.console_output.configure(state="normal")
        self.console_output.delete("0.0", "end")
        self.console_output.insert("end", f"[{timestamp}] {message}")
        self.console_output.see("end")
        self.console_output.configure(state="disabled")

    def check_server(self):
        """Check server health and show login"""
        proxy_url = self.proxy_entry.get().strip()

        if not proxy_url:
            self.console_print("❌ Error: No proxy URL entered")
            return

        # Health check first
        try:
            response = requests.get(f"{proxy_url}/health", timeout=5)
            if response.status_code == 200:
                self.console_print("✓ Server health check passed")
            else:
                self.console_print(f"⚠️ Server returned status {response.status_code}")
                return
        except Exception as e:
            self.console_print(f"❌ Cannot connect to server: {e}")
            return

        # Save working URL
        self.config["proxy_url"] = proxy_url
        save_config(self.config)

        # Show login dialog
        LoginDialog(self, proxy_url, self.on_login_success)

    def on_login_success(self, token, username):
        """Called after successful login"""
        self.token = token
        self.username = username
        self.running = True

        self.console_print(f"✓ Authenticated as {username}")

        # Start auto-refresh thread
        self.refresh_thread = threading.Thread(target=self.auto_refresh, daemon=True)
        self.refresh_thread.start()

        # Auto-fetch VMs
        self.get_vms()

    def auto_refresh(self):
        """Refresh token every 10 minutes"""
        while self.running:
            time.sleep(600)  # 10 minutes

            if not self.token:
                break

            try:
                proxy_url = self.proxy_entry.get().strip()
                response = requests.post(
                    f"{proxy_url}/refresh",
                    headers={"Authorization": f"Bearer {self.token}"},
                    timeout=5,
                )

                if response.ok:
                    self.token = response.json()["token"]
                    self.console_print("🔄 Token refreshed")
                else:
                    self.console_print("⚠️ Token refresh failed - please log in again")
                    self.token = None
                    break
            except Exception as e:
                self.console_print(f"❌ Refresh error: {e}")
                break

    def get_vms(self):
        """Fetch VMs with authentication"""
        proxy_url = self.proxy_entry.get().strip()

        if not self.token:
            self.console_print("❌ Please log in first")
            return

        try:
            response = requests.get(
                f"{proxy_url}/offer",
                headers={"Authorization": f"Bearer {self.token}"},
                timeout=5,
            )

            if response.status_code == 401:
                self.console_print("❌ Authentication expired - please log in again")
                self.check_server()
                return

            response.raise_for_status()
            self.populate_vms(response.text)

        except Exception as e:
            self.console_print(f"❌ Failed to get VMs: {e}")

    def populate_vms(self, vms_json):
        """Populate VM list"""
        for widget in self.vm_list.winfo_children():
            widget.destroy()

        try:
            vms = json.loads(vms_json)

            if not vms:
                self.console_print("No VMs found")
                return

            for vm in vms:
                vm_name = vm.get("name", f"vm-{vm.get('vmid', 'unknown')}")
                vmid = vm.get("vmid")
                node = vm.get("node")

                btn = ctk.CTkButton(
                    self.vm_list,
                    text=f"{vm_name} (ID: {vmid})",
                    command=lambda n=node, v=vmid: self.on_vm_click(n, v),
                    height=35,
                )
                btn.pack(fill="x", pady=3, padx=5)

            self.console_print(f"✓ Found {len(vms)} VMs")

        except json.JSONDecodeError as e:
            self.console_print(f"❌ Error parsing VM list: {e}")

    def on_vm_click(self, node, vmid):
        """Connect to VM with authentication"""
        if not self.token:
            self.console_print("❌ Please log in first")
            return

        self.console_print(f"🚀 Connecting to VM {vmid}...")

        try:
            proxy_url = self.proxy_entry.get().strip()
            response = requests.get(
                f"{proxy_url}/spice/{node}/{vmid}",
                headers={"Authorization": f"Bearer {self.token}"},
                timeout=10,
            )

            if response.status_code == 401:
                self.console_print("❌ Authentication expired - please log in again")
                self.check_server()
                return

            response.raise_for_status()

            # Launch viewer
            vv_content = response.text
            self.launch_viewer(vv_content)
            self.console_print(f"✓ Launched viewer for VM {vmid}")

        except Exception as e:
            self.console_print(f"❌ Connection failed: {e}")

    def launch_viewer(self, vv_content):
        """Launch remote-viewer"""
        import tempfile
        import subprocess
        import os

        with tempfile.NamedTemporaryFile(mode="w", suffix=".vv", delete=False) as f:
            f.write(vv_content)
            vv_file = f.name

        try:
            subprocess.Popen(["remote-viewer", vv_file])
        except FileNotFoundError:
            self.console_print(
                "❌ remote-viewer not found. Install: sudo apt install virt-viewer"
            )

        # Cleanup after delay
        self.after(
            5000, lambda: os.unlink(vv_file) if os.path.exists(vv_file) else None
        )

    def destroy(self):
        """Stop refresh thread when closing"""
        self.running = False
        super().destroy()


# Config management
BASE_DIR = Path(__file__).resolve().parent
CONFIG_PATH = BASE_DIR / "config.json"


def load_config():
    if CONFIG_PATH.exists():
        try:
            with open(CONFIG_PATH, "r") as f:
                return json.load(f)
        except json.JSONDecodeError:
            print("Warning: config.json is invalid. Using defaults.")
    return {}


def save_config(data):
    with open(CONFIG_PATH, "w") as f:
        json.dump(data, f, indent=4)


def main():
    ctk.set_appearance_mode("dark")
    app = SpiceProxyApp()
    app.mainloop()


if __name__ == "__main__":
    main()
