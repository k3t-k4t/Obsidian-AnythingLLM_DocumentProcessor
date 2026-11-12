import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import json
import subprocess
import threading
import queue
import os
import sys
from pathlib import Path

CONFIG_FILE = Path(__file__).parent / "config.json"

class PipelineApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Obsidian AI Pipeline")
        self.root.geometry("800x750")
        self.root.configure(padx=20, pady=20)

        self.processes = []
        self.log_queue = queue.Queue()
        
        # Load Config Data into memory
        if CONFIG_FILE.exists():
            with open(CONFIG_FILE, "r") as f:
                self.config_data = json.load(f)
                
            # --- MIGRATION: Upgrade old flat config to new profile format ---
            if "profiles" not in self.config_data:
                old_data = self.config_data.copy()
                self.config_data = {
                    "active_profile": "Default",
                    "profiles": {
                        "Default": old_data
                    }
                }
                # Save the newly migrated format immediately
                with open(CONFIG_FILE, "w") as f:
                    json.dump(self.config_data, f, indent=4)
            # ---------------------------------------------------------------
        else:
            # Create default structure if none exists
            self.config_data = {"active_profile": "Default", "profiles": {"Default": {}}}

        self.create_widgets()
        self.load_active_profile_to_ui()
        self.poll_logs()

    def create_widgets(self):
        # --- Profile Selection Frame ---
        profile_frame = ttk.LabelFrame(self.root, text="Vault Profile", padding=10)
        profile_frame.pack(fill="x", pady=(0, 10))

        ttk.Label(profile_frame, text="Select Profile:").pack(side="left", padx=5)
        self.profile_var = tk.StringVar()
        self.profile_dropdown = ttk.Combobox(profile_frame, textvariable=self.profile_var, state="readonly", width=30)
        self.profile_dropdown.pack(side="left", padx=5)
        self.profile_dropdown.bind("<<ComboboxSelected>>", self.on_profile_change)

        ttk.Button(profile_frame, text="New Profile", command=self.new_profile).pack(side="left", padx=5)
        ttk.Button(profile_frame, text="Delete Profile", command=self.delete_profile).pack(side="left", padx=5)

        # --- Settings Frame ---
        frame = ttk.LabelFrame(self.root, text="Configuration", padding=10)
        frame.pack(fill="x", pady=(0, 10))

        # Vault Path
        ttk.Label(frame, text="Obsidian Vault Path:").grid(row=0, column=0, sticky="w", pady=2)
        self.vault_path = ttk.Entry(frame, width=60)
        self.vault_path.grid(row=0, column=1, padx=5)
        ttk.Button(frame, text="Browse", command=lambda: self.browse_dir(self.vault_path)).grid(row=0, column=2)

        # AnythingLLM Docs Folder
        ttk.Label(frame, text="AnythingLLM Storage Path:").grid(row=1, column=0, sticky="w", pady=2)
        self.docs_folder = ttk.Entry(frame, width=60)
        self.docs_folder.grid(row=1, column=1, padx=5)
        ttk.Button(frame, text="Browse", command=lambda: self.browse_dir(self.docs_folder)).grid(row=1, column=2)

        # API URL
        ttk.Label(frame, text="AnythingLLM URL:").grid(row=2, column=0, sticky="w", pady=2)
        self.api_url = ttk.Entry(frame, width=60)
        self.api_url.grid(row=2, column=1, padx=5)

        # API Key
        ttk.Label(frame, text="API Key:").grid(row=3, column=0, sticky="w", pady=2)
        self.api_key = ttk.Entry(frame, width=60, show="*")
        self.api_key.grid(row=3, column=1, padx=5)

        # Workspace Slug
        ttk.Label(frame, text="Workspace Slug:").grid(row=4, column=0, sticky="w", pady=2)
        self.workspace_slug = ttk.Entry(frame, width=60)
        self.workspace_slug.grid(row=4, column=1, padx=5)

        # --- Lists Frame (Tags and Examples) ---
        lists_frame = ttk.Frame(self.root)
        lists_frame.pack(fill="x", pady=(0, 10))
        
        # Tags
        tag_frame = ttk.LabelFrame(lists_frame, text="Approved Tags (One per line)", padding=5)
        tag_frame.pack(side="left", fill="both", expand=True, padx=(0, 5))
        self.tags_text = tk.Text(tag_frame, height=8, width=30, font=("Consolas", 9))
        self.tags_text.pack(fill="both", expand=True)

        # Examples
        ex_frame = ttk.LabelFrame(lists_frame, text="Example Note Paths (One per line, relative to vault)", padding=5)
        ex_frame.pack(side="left", fill="both", expand=True, padx=(5, 0))
        self.examples_text = tk.Text(ex_frame, height=8, width=40, font=("Consolas", 9))
        self.examples_text.pack(fill="both", expand=True)

        # --- Controls Frame ---
        control_frame = ttk.Frame(self.root)
        control_frame.pack(fill="x", pady=10)

        self.btn_save = ttk.Button(control_frame, text="Save Config", command=self.save_config)
        self.btn_save.pack(side="left", padx=5)

        self.btn_start = ttk.Button(control_frame, text="Start Pipeline", command=self.start_pipeline)
        self.btn_start.pack(side="left", padx=5)

        self.btn_stop = ttk.Button(control_frame, text="Stop Pipeline", command=self.stop_pipeline, state="disabled")
        self.btn_stop.pack(side="left", padx=5)

        self.status_var = tk.StringVar(value="Status: Stopped")
        ttk.Label(control_frame, textvariable=self.status_var, font=("Segoe UI", 10, "bold")).pack(side="right", padx=10)

        # --- Logs Frame ---
        log_frame = ttk.LabelFrame(self.root, text="Live Logs", padding=10)
        log_frame.pack(fill="both", expand=True)

        self.log_text = tk.Text(log_frame, height=12, state="disabled", bg="#1e1e1e", fg="#d4d4d4", font=("Consolas", 9))
        self.log_text.pack(fill="both", expand=True, side="left")
        
        scrollbar = ttk.Scrollbar(log_frame, command=self.log_text.yview)
        scrollbar.pack(side="right", fill="y")
        self.log_text.config(yscrollcommand=scrollbar.set)

    def refresh_profile_dropdown(self):
        profiles = list(self.config_data.get("profiles", {}).keys())
        self.profile_dropdown['values'] = profiles
        self.profile_var.set(self.config_data.get("active_profile", "Default"))

    def on_profile_change(self, event=None):
        # Save current UI data to the old profile before switching
        self.save_ui_to_memory() 
        # Update active profile
        self.config_data["active_profile"] = self.profile_var.get()
        # Load new profile into UI
        self.load_active_profile_to_ui()

    def load_active_profile_to_ui(self):
        self.refresh_profile_dropdown()
        active = self.config_data.get("active_profile")
        profile = self.config_data.get("profiles", {}).get(active, {})

        # Clear existing entries
        self.vault_path.delete(0, tk.END)
        self.docs_folder.delete(0, tk.END)
        self.api_url.delete(0, tk.END)
        self.api_key.delete(0, tk.END)
        self.workspace_slug.delete(0, tk.END)
        self.tags_text.delete("1.0", tk.END)
        self.examples_text.delete("1.0", tk.END)

        # Populate entries
        self.vault_path.insert(0, profile.get("vault_path", ""))
        self.docs_folder.insert(0, profile.get("docs_folder", ""))
        self.api_url.insert(0, profile.get("anythingllm_url", "http://localhost:3001"))
        self.api_key.insert(0, profile.get("api_key", ""))
        self.workspace_slug.insert(0, profile.get("workspace_slug", ""))
        
        # Populate tags
        tags_str = "\n".join(profile.get("tags", []))
        self.tags_text.insert("1.0", tags_str)
        
        # Populate examples
        examples_str = "\n".join(profile.get("examples", []))
        self.examples_text.insert("1.0", examples_str)

    def save_ui_to_memory(self):
        active = self.config_data.get("active_profile", "Default")
        
        # Parse multiline text back to lists
        tags_list = [t.strip() for t in self.tags_text.get("1.0", tk.END).splitlines() if t.strip()]
        examples_list = [e.strip() for e in self.examples_text.get("1.0", tk.END).splitlines() if e.strip()]

        self.config_data["profiles"][active] = {
            "vault_path": self.vault_path.get(),
            "docs_folder": self.docs_folder.get(),
            "anythingllm_url": self.api_url.get(),
            "api_key": self.api_key.get(),
            "workspace_slug": self.workspace_slug.get(),
            "tags": tags_list,
            "examples": examples_list
        }

    def save_config(self):
        self.save_ui_to_memory()
        with open(CONFIG_FILE, "w") as f:
            json.dump(self.config_data, f, indent=4)
        messagebox.showinfo("Success", f"Configuration saved for profile: {self.config_data['active_profile']}")
        self.log(f"Configuration saved for profile: {self.config_data['active_profile']}")

    def new_profile(self):
        from tkinter import simpledialog
        name = simpledialog.askstring("New Profile", "Enter a name for the new Vault Profile:")
        if name and name not in self.config_data["profiles"]:
            self.save_ui_to_memory() # Save current work
            self.config_data["profiles"][name] = {}
            self.config_data["active_profile"] = name
            self.load_active_profile_to_ui()
            self.save_config()

    def delete_profile(self):
        active = self.config_data.get("active_profile")
        if active == "Default" or len(self.config_data["profiles"]) <= 1:
            messagebox.showerror("Error", "Cannot delete the Default or only remaining profile.")
            return
            
        confirm = messagebox.askyesno("Confirm", f"Delete profile '{active}'?")
        if confirm:
            del self.config_data["profiles"][active]
            self.config_data["active_profile"] = list(self.config_data["profiles"].keys())[0]
            self.load_active_profile_to_ui()
            self.save_config()

    def browse_dir(self, entry_widget):
        path = filedialog.askdirectory()
        if path:
            entry_widget.delete(0, tk.END)
            entry_widget.insert(0, path)

    def start_pipeline(self):
        self.save_config() # Auto-save before starting
        
        self.btn_start.config(state="disabled")
        self.btn_stop.config(state="normal")
        self.status_var.set(f"Status: Running ({self.config_data['active_profile']})")
        self.log(f"Starting pipeline scripts for profile: {self.config_data['active_profile']}...")

        self.start_script("watch_anythingllm.py")
        self.start_script("intake_bot.py")

    def start_script(self, script_name):
        script_path = Path(__file__).parent / script_name
        if not script_path.exists():
            self.log(f"ERROR: {script_name} not found.")
            return

        process = subprocess.Popen(
            [sys.executable, "-u", str(script_path)],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
        )
        self.processes.append(process)

        def read_output():
            for line in iter(process.stdout.readline, ''):
                self.log_queue.put(f"[{script_name}] {line.strip()}")
            process.stdout.close()

        threading.Thread(target=read_output, daemon=True).start()

    def stop_pipeline(self):
        self.log("Stopping pipeline...")
        for p in self.processes:
            p.terminate()
        self.processes.clear()
        
        self.btn_start.config(state="normal")
        self.btn_stop.config(state="disabled")
        self.status_var.set("Status: Stopped")
        self.log("Pipeline stopped.")

    def log(self, message):
        self.log_text.config(state="normal")
        self.log_text.insert(tk.END, message + "\n")
        self.log_text.see(tk.END)
        self.log_text.config(state="disabled")

    def poll_logs(self):
        while not self.log_queue.empty():
            msg = self.log_queue.get()
            self.log(msg)
        self.root.after(100, self.poll_logs)

if __name__ == "__main__":
    root = tk.Tk()
    app = PipelineApp(root)
    root.mainloop()