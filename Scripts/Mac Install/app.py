import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import json
import subprocess
import threading
import queue
import os
from pathlib import Path

CONFIG_FILE = Path(__file__).parent / "config.json"

class PipelineApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Obsidian AI Pipeline")
        self.root.geometry("700x600")
        self.root.configure(padx=20, pady=20)

        self.processes = []
        self.log_queue = queue.Queue()

        self.create_widgets()
        self.load_config()
        self.poll_logs()

    def create_widgets(self):
        # --- Settings Frame ---
        frame = ttk.LabelFrame(self.root, text="Configuration", padding=10)
        frame.pack(fill="x", pady=(0, 15))

        # Vault Path
        ttk.Label(frame, text="Obsidian Vault Path:").grid(row=0, column=0, sticky="w", pady=5)
        self.vault_path = ttk.Entry(frame, width=50)
        self.vault_path.grid(row=0, column=1, padx=5)
        ttk.Button(frame, text="Browse", command=lambda: self.browse_dir(self.vault_path)).grid(row=0, column=2)

        # AnythingLLM Docs Folder
        ttk.Label(frame, text="AnythingLLM Storage Path:").grid(row=1, column=0, sticky="w", pady=5)
        self.docs_folder = ttk.Entry(frame, width=50)
        self.docs_folder.grid(row=1, column=1, padx=5)
        ttk.Button(frame, text="Browse", command=lambda: self.browse_dir(self.docs_folder)).grid(row=1, column=2)

        # API URL
        ttk.Label(frame, text="AnythingLLM URL:").grid(row=2, column=0, sticky="w", pady=5)
        self.api_url = ttk.Entry(frame, width=50)
        self.api_url.grid(row=2, column=1, padx=5)

        # API Key
        ttk.Label(frame, text="API Key:").grid(row=3, column=0, sticky="w", pady=5)
        self.api_key = ttk.Entry(frame, width=50, show="*")
        self.api_key.grid(row=3, column=1, padx=5)

        # Workspace Slug
        ttk.Label(frame, text="Workspace Slug:").grid(row=4, column=0, sticky="w", pady=5)
        self.workspace_slug = ttk.Entry(frame, width=50)
        self.workspace_slug.grid(row=4, column=1, padx=5)

        # --- Controls Frame ---
        control_frame = ttk.Frame(self.root)
        control_frame.pack(fill="x", pady=10)

        self.btn_save = ttk.Button(control_frame, text="Save Config", command=self.save_config)
        self.btn_save.pack(side="left", padx=5)

        self.btn_start = ttk.Button(control_frame, text="Start Pipeline", command=self.start_pipeline, style="Accent.TButton")
        self.btn_start.pack(side="left", padx=5)

        self.btn_stop = ttk.Button(control_frame, text="Stop Pipeline", command=self.stop_pipeline, state="disabled")
        self.btn_stop.pack(side="left", padx=5)

        self.status_var = tk.StringVar(value="Status: Stopped")
        ttk.Label(control_frame, textvariable=self.status_var, font=("Segoe UI", 10, "bold")).pack(side="right", padx=10)

        # --- Logs Frame ---
        log_frame = ttk.LabelFrame(self.root, text="Live Logs", padding=10)
        log_frame.pack(fill="both", expand=True)

        self.log_text = tk.Text(log_frame, height=15, state="disabled", bg="#1e1e1e", fg="#d4d4d4", font=("Consolas", 9))
        self.log_text.pack(fill="both", expand=True, side="left")
        
        scrollbar = ttk.Scrollbar(log_frame, command=self.log_text.yview)
        scrollbar.pack(side="right", fill="y")
        self.log_text.config(yscrollcommand=scrollbar.set)

    def browse_dir(self, entry_widget):
        path = filedialog.askdirectory()
        if path:
            entry_widget.delete(0, tk.END)
            entry_widget.insert(0, path)

    def load_config(self):
        if CONFIG_FILE.exists():
            with open(CONFIG_FILE, "r") as f:
                config = json.load(f)
                self.vault_path.insert(0, config.get("vault_path", ""))
                self.docs_folder.insert(0, config.get("docs_folder", ""))
                self.api_url.insert(0, config.get("anythingllm_url", "http://localhost:3001"))
                self.api_key.insert(0, config.get("api_key", ""))
                self.workspace_slug.insert(0, config.get("workspace_slug", ""))

    def save_config(self):
        config = {
            "vault_path": self.vault_path.get(),
            "docs_folder": self.docs_folder.get(),
            "anythingllm_url": self.api_url.get(),
            "api_key": self.api_key.get(),
            "workspace_slug": self.workspace_slug.get()
        }
        with open(CONFIG_FILE, "w") as f:
            json.dump(config, f, indent=4)
        messagebox.showinfo("Success", "Configuration saved successfully!")
        self.log("Configuration saved.")

    def start_pipeline(self):
        if not CONFIG_FILE.exists():
            messagebox.showerror("Error", "Please save the configuration first.")
            return

        self.btn_start.config(state="disabled")
        self.btn_stop.config(state="normal")
        self.status_var.set("Status: Running")
        self.log("Starting pipeline scripts...")

        # Start watch_anythingllm.py
        self.start_script("watch_anythingllm.py")
        
        # Start intake_bot.py
        self.start_script("intake_bot.py")

    def start_script(self, script_name):
        script_path = Path(__file__).parent / script_name
        if not script_path.exists():
            self.log(f"ERROR: {script_name} not found.")
            return

        # Use sys.executable to ensure we use the same Python interpreter
        process = subprocess.Popen(
            ["python3", "-u", str(script_path)],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
        )
        self.processes.append(process)

        # Read output in a background thread
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