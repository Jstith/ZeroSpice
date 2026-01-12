#!/usr/bin/env python3
import json
import threading
import time
from datetime import datetime
from pathlib import Path

import customtkinter as ctk
import qrcode
import requests
from PIL import Image, ImageTk


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


class EnrollmentDialog(ctk.CTkToplevel):
    """Enrollment dialog for new user registration"""

    def __init__(self, parent, proxy_url):
        super().__init__(parent)

        self.proxy_url = proxy_url
        self.title("Enroll New Account")
        self.geometry("500x700")
        self.resizable(False, False)

        # Make modal
        self.transient(parent)
        self.after(100, self._grab_focus)

        # State
        self.current_step = 1
        self.enrollment_token = None
        self.username = None
        self.secret = None
        self.provisioning_uri = None

        # Main container
        self.main_frame = ctk.CTkFrame(self)
        self.main_frame.pack(fill="both", expand=True, padx=20, pady=20)

        # Title
        self.title_label = ctk.CTkLabel(
            self.main_frame,
            text="Step 1: Enter Enrollment Token",
            font=ctk.CTkFont(size=18, weight="bold"),
        )
        self.title_label.pack(pady=15)

        # Content frame (changes per step)
        self.content_frame = ctk.CTkFrame(self.main_frame)
        self.content_frame.pack(fill="both", expand=True, pady=10)

        # Status label
        self.status_label = ctk.CTkLabel(
            self.main_frame, text="", text_color="gray", wraplength=450, height=40
        )
        self.status_label.pack(pady=10)

        # Show initial step
        self.show_step_1()

    def _grab_focus(self):
        """Grab focus after window is visible"""
        try:
            self.grab_set()
        except:
            self.after(50, self._grab_focus)

    def clear_content(self):
        """Clear content frame"""
        for widget in self.content_frame.winfo_children():
            widget.destroy()

    def show_step_1(self):
        """Step 1: Token input"""
        self.clear_content()
        self.title_label.configure(text="Step 1: Enter Enrollment Token")

        ctk.CTkLabel(
            self.content_frame,
            text="Paste the enrollment token provided by your administrator:",
            wraplength=400,
        ).pack(pady=15)

        self.token_entry = ctk.CTkEntry(self.content_frame, width=400, height=35)
        self.token_entry.pack(pady=10)
        self.token_entry.focus()

        ctk.CTkButton(
            self.content_frame,
            text="Validate Token",
            command=self.validate_token,
            width=200,
            height=35,
        ).pack(pady=15)

    def validate_token(self):
        """Validate enrollment token"""
        token = self.token_entry.get().strip()

        if not token:
            self.status_label.configure(text="Please enter a token", text_color="red")
            return

        self.status_label.configure(text="Validating token...", text_color="orange")

        try:
            response = requests.get(
                f"{self.proxy_url}/enroll", params={"token": token}, timeout=5
            )

            if response.status_code == 200:
                self.enrollment_token = token
                self.status_label.configure(text="Token is valid", text_color="green")
                self.after(500, self.show_step_2)
            else:
                error = response.json().get("error", "Invalid token")
                self.status_label.configure(text=f"Error: {error}", text_color="red")

        except Exception as e:
            self.status_label.configure(text=f"Error: {str(e)}", text_color="red")

    def show_step_2(self):
        """Step 2: Username input"""
        self.clear_content()
        self.current_step = 2
        self.title_label.configure(text="Step 2: Choose Username")

        ctk.CTkLabel(
            self.content_frame,
            text="Choose your username (3-32 alphanumeric characters):",
            wraplength=400,
        ).pack(pady=15)

        self.username_entry = ctk.CTkEntry(self.content_frame, width=300, height=35)
        self.username_entry.pack(pady=10)
        self.username_entry.focus()
        self.username_entry.bind("<Return>", lambda e: self.request_totp_secret())

        ctk.CTkButton(
            self.content_frame,
            text="Next",
            command=self.request_totp_secret,
            width=200,
            height=35,
        ).pack(pady=15)

    def request_totp_secret(self):
        """Request TOTP secret from server"""
        username = self.username_entry.get().strip().lower()

        if not username or len(username) < 3:
            self.status_label.configure(
                text="Username must be at least 3 characters", text_color="red"
            )
            return

        self.status_label.configure(
            text="Generating TOTP secret...", text_color="orange"
        )

        try:
            response = requests.post(
                f"{self.proxy_url}/enroll",
                json={"token": self.enrollment_token, "username": username},
                timeout=5,
            )

            if response.status_code == 200:
                data = response.json()
                self.username = username
                self.secret = data["secret"]
                self.provisioning_uri = data["provisioning_uri"]
                self.status_label.configure(
                    text="TOTP secret generated", text_color="green"
                )
                self.after(500, self.show_step_3)
            else:
                error = response.json().get("error", "Failed to generate secret")
                self.status_label.configure(text=f"Error: {error}", text_color="red")

        except Exception as e:
            self.status_label.configure(text=f"Error: {str(e)}", text_color="red")

    def show_step_3(self):
        """Step 3: Display QR code"""
        self.clear_content()
        self.current_step = 3
        self.title_label.configure(text="Step 3: Scan QR Code")

        ctk.CTkLabel(
            self.content_frame,
            text="Scan this QR code with your authenticator app\n(Google Authenticator, Authy, 1Password, etc.)",
            wraplength=400,
        ).pack(pady=10)

        # Generate QR code
        qr = qrcode.QRCode(version=1, box_size=8, border=2)
        qr.add_data(self.provisioning_uri)
        qr.make(fit=True)
        qr_img = qr.make_image(fill_color="black", back_color="white")

        # Convert to PhotoImage
        qr_photo = ImageTk.PhotoImage(qr_img)

        # Display QR
        qr_label = ctk.CTkLabel(self.content_frame, image=qr_photo, text="")
        qr_label.image = qr_photo  # Keep reference
        qr_label.pack(pady=10)

        # Manual entry option
        manual_frame = ctk.CTkFrame(self.content_frame)
        manual_frame.pack(pady=15, fill="x", padx=20)

        ctk.CTkLabel(
            manual_frame,
            text="Or manually enter in your app:",
            font=ctk.CTkFont(size=11, weight="bold"),
        ).pack(pady=5)

        secret_entry = ctk.CTkEntry(manual_frame, width=300)
        secret_entry.insert(0, self.secret)
        secret_entry.configure(state="readonly")
        secret_entry.pack(pady=5)

        ctk.CTkButton(
            self.content_frame,
            text="Next: Confirm with TOTP Code",
            command=self.show_step_4,
            width=250,
            height=35,
        ).pack(pady=15)

    def show_step_4(self):
        """Step 4: TOTP confirmation"""
        self.clear_content()
        self.current_step = 4
        self.title_label.configure(text="Step 4: Confirm TOTP Code")

        ctk.CTkLabel(
            self.content_frame,
            text="Enter the 6-digit code from your authenticator app\nto confirm enrollment:",
            wraplength=400,
        ).pack(pady=15)

        self.totp_entry = ctk.CTkEntry(
            self.content_frame, width=200, height=35, placeholder_text="123456"
        )
        self.totp_entry.pack(pady=10)
        self.totp_entry.focus()
        self.totp_entry.bind("<Return>", lambda e: self.confirm_enrollment())

        ctk.CTkButton(
            self.content_frame,
            text="Confirm & Activate Account",
            command=self.confirm_enrollment,
            width=250,
            height=35,
        ).pack(pady=15)

    def confirm_enrollment(self):
        """Confirm enrollment with TOTP code"""
        totp_code = self.totp_entry.get().strip()

        if len(totp_code) != 6 or not totp_code.isdigit():
            self.status_label.configure(
                text="Please enter 6-digit code", text_color="red"
            )
            return

        self.status_label.configure(
            text="Confirming enrollment...", text_color="orange"
        )

        try:
            response = requests.post(
                f"{self.proxy_url}/enroll",
                json={
                    "token": self.enrollment_token,
                    "username": self.username,
                    "totp_code": totp_code,
                },
                timeout=5,
            )

            if response.status_code == 201:
                self.show_success()
            else:
                error = response.json().get("error", "Confirmation failed")
                self.status_label.configure(text=f"Error: {error}", text_color="red")
                self.totp_entry.delete(0, "end")

        except Exception as e:
            self.status_label.configure(text=f"Error: {str(e)}", text_color="red")

    def show_success(self):
        """Show success message"""
        self.clear_content()
        self.title_label.configure(text="Enrollment Complete")

        ctk.CTkLabel(
            self.content_frame,
            text=f"Account '{self.username}' has been activated!\n\nYou can now login with your username and authenticator code.",
            wraplength=400,
            font=ctk.CTkFont(size=14),
        ).pack(pady=30)

        ctk.CTkButton(
            self.content_frame,
            text="Close",
            command=self.destroy,
            width=200,
            height=35,
        ).pack(pady=15)

        self.status_label.configure(text="", text_color="gray")


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
        top_frame.grid_columnconfigure(2, weight=0)
        top_frame.grid_columnconfigure(3, weight=0)

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
        self.get_vm_button.grid(row=1, column=2, padx=5, pady=10)

        self.enroll_button = ctk.CTkButton(
            top_frame,
            text="Enroll Account",
            command=self.show_enrollment,
            fg_color="#555",
            hover_color="#666",
        )
        self.enroll_button.grid(row=1, column=3, padx=5, pady=10)

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

    def show_enrollment(self):
        """Show enrollment dialog"""
        proxy_url = self.proxy_entry.get().strip()

        if not proxy_url:
            self.console_print("Error: No proxy URL entered")
            return

        # Health check first
        try:
            response = requests.get(f"{proxy_url}/health", timeout=5)
            if response.status_code == 200:
                self.console_print("Server health check passed")
            else:
                self.console_print(f"Server returned status {response.status_code}")
                return
        except Exception as e:
            self.console_print(f"Cannot connect to server: {e}")
            return

        # Save working URL
        self.config["proxy_url"] = proxy_url
        save_config(self.config)

        # Show enrollment dialog
        EnrollmentDialog(self, proxy_url)

    def check_server(self):
        """Check server health and show login"""
        proxy_url = self.proxy_entry.get().strip()

        if not proxy_url:
            self.console_print("Error: No proxy URL entered")
            return

        # Health check first
        try:
            response = requests.get(f"{proxy_url}/health", timeout=5)
            if response.status_code == 200:
                self.console_print("Server health check passed")
            else:
                self.console_print(f"Server returned status {response.status_code}")
                return
        except Exception as e:
            self.console_print(f"Cannot connect to server: {e}")
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

        self.console_print(f"Authenticated as {username}")

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
                    self.console_print("Token refreshed")
                else:
                    self.console_print("Token refresh failed - please log in again")
                    self.token = None
                    break
            except Exception as e:
                self.console_print(f"Refresh error: {e}")
                break

    def get_vms(self):
        """Fetch VMs with authentication"""
        proxy_url = self.proxy_entry.get().strip()

        if not self.token:
            self.console_print("Please log in first")
            return

        try:
            response = requests.get(
                f"{proxy_url}/offer",
                headers={"Authorization": f"Bearer {self.token}"},
                timeout=5,
            )

            if response.status_code == 401:
                self.console_print("Authentication expired - please log in again")
                self.check_server()
                return

            response.raise_for_status()
            self.populate_vms(response.text)

        except Exception as e:
            self.console_print(f"Failed to get VMs: {e}")

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

            self.console_print(f"Found {len(vms)} VMs")

        except json.JSONDecodeError as e:
            self.console_print(f"Error parsing VM list: {e}")

    def on_vm_click(self, node, vmid):
        """Connect to VM with authentication"""
        if not self.token:
            self.console_print("Please log in first")
            return

        self.console_print(f"Connecting to VM {vmid}...")

        try:
            proxy_url = self.proxy_entry.get().strip()
            response = requests.get(
                f"{proxy_url}/spice/{node}/{vmid}",
                headers={"Authorization": f"Bearer {self.token}"},
                timeout=10,
            )

            if response.status_code == 401:
                self.console_print("Authentication expired - please log in again")
                self.check_server()
                return

            response.raise_for_status()

            # Launch viewer
            vv_content = response.text
            self.launch_viewer(vv_content)
            self.console_print(f"Launched viewer for VM {vmid}")

        except Exception as e:
            self.console_print(f"Connection failed: {e}")

    def launch_viewer(self, vv_content):
        """Launch remote-viewer"""
        import os
        import subprocess
        import tempfile

        with tempfile.NamedTemporaryFile(mode="w", suffix=".vv", delete=False) as f:
            f.write(vv_content)
            vv_file = f.name

        try:
            subprocess.Popen(["remote-viewer", vv_file])
        except FileNotFoundError:
            self.console_print(
                "remote-viewer not found. Install: sudo apt install virt-viewer"
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
