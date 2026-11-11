import json
import re
import time
from pathlib import Path
import requests
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

# --- CONFIGURATION ---
ANYTHINGLLM_DOCS_FOLDER = Path(r"C:\Users\isaac\AppData\Roaming\anythingllm-desktop\storage\documents\custom-documents") # UPDATE THIS
INTAKE_FOLDER = Path(r"D:\Obsidian\Vaults\Test Vault\01-Intake")

ANYTHINGLLM_URL = "http://localhost:3001"
API_KEY = "23F80MY-FT3M6ZJ-N3XR6BQ-71V64W5" # UPDATE THIS
WORKSPACE_SLUG = "my-workspace" # UPDATE THIS


def delete_from_anythingllm(document_location: str):
    """Removes the document from the workspace and then deletes the file."""
    headers = {
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json",
    }

    # Step 1: Remove the document's embeddings from the workspace
    try:
        workspace_url = f"{ANYTHINGLLM_URL}/api/v1/workspace/{WORKSPACE_SLUG}/update-embeddings"
        payload = {"deletes": [document_location]}
        r = requests.post(workspace_url, headers=headers, json=payload, timeout=30)
        if r.status_code == 200:
            print(f"Removed embeddings for: {document_location}")
    except Exception as e:
        print(f"Failed to remove embeddings (continuing): {e}")

    # Step 2: Delete the actual document file from the system
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
        # Keeps track of files we've already processed to prevent duplicates
        self.processed_files = set()

    def on_created(self, event):
        if event.is_directory or not event.src_path.endswith(".json"):
            return

        json_path = Path(event.src_path)
        
        # 1. Ignore if we've already processed this exact file
        if json_path.name in self.processed_files:
            return
        self.processed_files.add(json_path.name)

        # Debounce: wait a moment for the file to finish writing
        time.sleep(1.0)

        try:
            with open(json_path, 'r', encoding='utf-8') as f:
                data = json.load(f)

            text_content = data.get('pageContent') or data.get('content', '')
            if not text_content:
                return

            # 2. Robust filename extraction
            # Example: 'Testy-Doc.docx-1373f4c9-c2f8...' 
            # rsplit('-', 5) splits off the 5 parts of the UUID
            name_parts = json_path.stem.rsplit('-', 5)
            original_name = name_parts[0] 
            
            # Strip the original extension (e.g., '.docx', '.md') 
            base_name = Path(original_name).stem
            
            # Clean up special characters
            safe_name = re.sub(r'[^\w\s-]', '', base_name).strip().replace(' ', '_')
            output_path = INTAKE_FOLDER / f"{safe_name}.md"
            
            # 3. Append if file exists (handles AnythingLLM's chunked documents)
            mode = 'a' if output_path.exists() else 'w'
            
            with open(output_path, mode, encoding='utf-8') as out_f:
                if mode == 'a':
                    out_f.write("\n\n---\n\n") # Spacer for appended chunks
                out_f.write(text_content.strip())
                
            print(f"Extracted: {json_path.name} -> {output_path.name}")

            # 4. Delete from AnythingLLM
            doc_location = f"custom-documents/{json_path.name}"
            time.sleep(2) # Give the system a moment to breathe
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