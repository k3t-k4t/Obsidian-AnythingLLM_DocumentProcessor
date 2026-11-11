import json
import re
import time
from pathlib import Path
import requests
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

# Load config
CONFIG_PATH = Path(__file__).parent / "config.json"
try:
    with open(CONFIG_PATH, "r") as f:
        CONFIG = json.load(f)
except FileNotFoundError:
    print("ERROR: config.json not found. Please run app.py to set up your configuration.")
    exit(1)

ANYTHINGLLM_DOCS_FOLDER = Path(CONFIG.get("docs_folder", ""))
INTAKE_FOLDER           = Path(CONFIG.get("vault_path", "")) / "01-intake"

ANYTHINGLLM_URL         = CONFIG.get("anythingllm_url", "http://localhost:3001")
API_KEY                 = CONFIG.get("api_key", "")
WORKSPACE_SLUG          = CONFIG.get("workspace_slug", "")

def delete_from_anythingllm(document_location: str):
    """Removes the document from the workspace and then deletes the file."""
    headers = {
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json",
    }

    try:
        workspace_url = f"{ANYTHINGLLM_URL}/api/v1/workspace/{WORKSPACE_SLUG}/update-embeddings"
        payload = {"deletes": [document_location]}
        r = requests.post(workspace_url, headers=headers, json=payload, timeout=30)
        if r.status_code == 200:
            print(f"Removed embeddings for: {document_location}")
    except Exception as e:
        print(f"Failed to remove embeddings (continuing): {e}")

    try:
        delete_url = f"{ANYTHINGLLM_URL}/api/v1/system/remove-documents"
        payload = {"names": [document_location]}
        r = requests.delete(delete_url, headers=headers, json=payload, timeout=30)
        if r.status_code == 200:
            print(f"Deleted document file: {document_location}")
    except Exception as e:
        print(f"Failed to delete document file: {e}")

class AnythingLLMHandler(FileSystemEventHandler):
    def __init__(self):
        super().__init__()
        self.processed_files = set()

    def on_created(self, event):
        if event.is_directory or not event.src_path.endswith(".json"):
            return

        json_path = Path(event.src_path)
        
        if json_path.name in self.processed_files:
            return
        self.processed_files.add(json_path.name)

        time.sleep(1.0)

        try:
            with open(json_path, 'r', encoding='utf-8') as f:
                data = json.load(f)

            text_content = data.get('pageContent') or data.get('content', '')
            if not text_content:
                return

            # Use regex to strip the standard UUID format safely
            stem = json_path.stem
            match = re.search(r'-[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$', stem)
            if match:
                original_filename = stem[:match.start()]
            else:
                original_filename = stem # Fallback

            # --- LOOP PREVENTION ---
            # Ignore Markdown files, as they are uploaded by our own scripts/Sync plugin
            if original_filename.lower().endswith('.md'):
                print(f"Ignoring Markdown upload (loop prevention): {json_path.name}")
                return

            base_name = Path(original_filename).stem
            safe_name = re.sub(r'[^\w\s-]', '', base_name).strip().replace(' ', '_')
            output_path = INTAKE_FOLDER / f"{safe_name}.md"
            
            mode = 'a' if output_path.exists() else 'w'
            with open(output_path, mode, encoding='utf-8') as out_f:
                if mode == 'a':
                    out_f.write("\n\n---\n\n") 
                out_f.write(text_content.strip())
                
            print(f"Extracted: {json_path.name} -> {output_path.name}")

            doc_location = f"custom-documents/{json_path.name}"
            time.sleep(2) 
            delete_from_anythingllm(doc_location)

        except Exception as e:
            print(f"Error processing {json_path.name}: {e}")

if __name__ == "__main__":
    INTAKE_FOLDER.mkdir(parents=True, exist_ok=True)
    
    if not ANYTHINGLLM_DOCS_FOLDER.exists():
        print(f"ERROR: The folder does not exist: {ANYTHINGLLM_DOCS_FOLDER}")
        exit(1)

    print(f"Watching AnythingLLM storage: {ANYTHINGLLM_DOCS_FOLDER}")
    print(f"Outputting Markdown to: {INTAKE_FOLDER}")

    observer = Observer()
    observer.schedule(AnythingLLMHandler(), str(ANYTHINGLLM_DOCS_FOLDER), recursive=False)
    observer.start()

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        observer.stop()
    observer.join()