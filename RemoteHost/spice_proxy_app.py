import customtkinter as ctk
import requests
import json
from datetime import datetime
from spice_connect import get_spice_file, launch_viewer
from pathlib import Path


class SpiceProxyApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("Spice Remote Access Client")
        self.geometry("600x600")

        top_frame = ctk.CTkFrame(self)
        top_frame.pack(pady=20, padx=20, fill="x")

        # Build top half of UI
        top_frame.grid_columnconfigure(0, weight=1)  # Column 0 gets weight 1
        top_frame.grid_columnconfigure(1, weight=1)  # Column 1 gets weight 1
        top_frame.grid_columnconfigure(2, weight=1)  # Column 2 gets weight 1

        ctk.CTkLabel(top_frame, text="Proxy Server URL:").grid(
            row=1, column=0, padx=10, pady=10, sticky="e"
        )

        self.proxy_entry = ctk.CTkEntry(
            top_frame, placeholder_text="http://10.10.10.10:5000", width=200
        )
        self.proxy_entry.grid(row=1, column=1, padx=10, pady=10, sticky="w")
        self.config = load_config()
        saved_url = self.config.get("proxy_url", "")
        if saved_url:
            self.proxy_entry.insert(0, saved_url)

        self.get_vm_button = ctk.CTkButton(
            top_frame, text="Check Available VMs", command=self.check_server
        ).grid(row=1, column=2, padx=10, pady=10)

        # Middle panel grabage.
        middle_frame = ctk.CTkFrame(self)
        middle_frame.pack(pady=10, padx=20, fill="both", expand=True)

        ctk.CTkLabel(middle_frame, text="Available VMs:").pack(pady=5)
        self.vm_list = ctk.CTkScrollableFrame(middle_frame, height=50)
        self.vm_list.pack(fill="both", expand=True, padx=10, pady=5)

        # Let's handle the command output.
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
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.console_output.configure(state="normal")
        self.console_output.delete("0.0", "end")
        self.console_output.insert("end", f"[{timestamp}] {message}")
        self.console_output.configure(state="disabled")

    def check_server(self):
        # Health check
        try:
            url = f"{self.proxy_entry.get()}/health"
            r = requests.get(url)
            self.console_print("Server health check...\n" + r.text)
        except Exception as e:
            self.console_print("Server health check...\n" + str(e))
            return

        # URL worked, lets save it for later
        url = f"{self.proxy_entry.get()}"
        self.config["proxy_url"] = url
        save_config(self.config)

        try:
            url = f"{self.proxy_entry.get()}/offer"
            r = requests.get(url)
            self.populate_vms(r.text)
        except Exception as e:
            self.console_print(e)

    def populate_vms(self, vms):
        for widget in self.vm_list.winfo_children():
            widget.destroy()

        vms = json.loads(vms)
        for vm in vms:
            vm_name = vm.get("name", f"vm-{vm.get('vmid', 'unknown')}")
            vmid = vm.get("vmid")

            btn = ctk.CTkButton(
                self.vm_list,
                text=vm_name,
                command=lambda vmid=vmid, node=vm["node"]: self.on_vm_click(node, vmid),
            )
            btn.pack(fill="x", pady=2, padx=5)

    def on_vm_click(self, node, vmid):
        vv_content = get_spice_file(self.proxy_entry.get(), node, vmid)
        launch_viewer(vv_content)


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
