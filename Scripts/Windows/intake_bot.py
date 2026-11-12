import json
import logging
import re
import shutil
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

import requests
import yaml
from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

# Load config
CONFIG_PATH = Path(__file__).parent / "config.json"
try:
    with open(CONFIG_PATH, "r") as f:
        CONFIG = json.load(f)
except FileNotFoundError:
    print("ERROR: config.json not found. Please run app.py to set up your configuration.")
    exit(1)

VAULT_PATH        = Path(CONFIG.get("vault_path", ""))
INTAKE_FOLDER     = VAULT_PATH / "00-intake"
PROCESSED_FOLDER  = VAULT_PATH / "02-processed"
FAILED_FOLDER     = VAULT_PATH / "03-failed"
NOTES_FOLDER      = VAULT_PATH / "01-notes"
REVIEW_FOLDER     = VAULT_PATH / "04-review"  

ANYTHINGLLM_URL   = CONFIG.get("anythingllm_url", "http://localhost:3001")
API_KEY           = CONFIG.get("api_key", "")
WORKSPACE_SLUG    = CONFIG.get("workspace_slug", "")

SUPPORTED_EXTS    = {".md", ".txt"}
VALID_STATUS      = {"inbox", "draft", "active", "done", "archived"}

MAX_RETRIES       = 2
MAX_DOC_CHARS     = 60_000
DELETE_UPLOAD_AFTER_SUCCESS = True

AVAILABLE_TAGS = [
    "People", "Admin", "Research", "Overview", "Stub",
    "Cardiology", "InformationArchitecture", "InformationProduct", "Investigation",
    "DiseasePathway", "GraphNavigation", "System", "CardiacImaging", 
    "Representation", "Electrocardiography", "Echocardiography", "GraphSupporting",
    "Haemodynamics", "InterventionPathway", "Presentation", "ArchitecturePrinciple",
    "ClinicalAssessment", "CardiacDevices", "ClinicalDecision", "ClinicalManagement",
    "ClinicalProcedure", "ExercisePhysiology", "Genetics", "Geometry",
    "ImplantsAndDevices", "InvasiveAssessment", "LaboratoryMedicine",
    "LongitudinalAssessment", "MyocardialFunction", "NHS", "NuclearMedicine",
    "PulmonaryHypertension", "ValvularHeartDisease", "VentricularFunction"
]

EXAMPLES = [
    "01-notes/Cardiac CT.md",
    "01-notes/Coronary Artery Disease.md",
    "01-notes/Catheter Ablation.md"
]

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("intake")

def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")

def build_prompt(document_text: str) -> str:
    examples_text = ""
    for rel_path in EXAMPLES:
        p = VAULT_PATH / rel_path
        if p.exists():
            examples_text += f"--- EXAMPLE ---\n{p.read_text(encoding='utf-8')}\n\n"
        else:
            log.warning("Example missing: %s", p)

    if len(document_text) > MAX_DOC_CHARS:
        document_text = document_text[:MAX_DOC_CHARS] + "\n[... truncated ...]"

    tag_menu = ", ".join(AVAILABLE_TAGS)

    return f"""You are an Obsidian vault editor for a knowledge base. 
Read the new document below and produce a new note.

CRITICAL RULE FOR CONTENT (ANTI-HALLUCINATION):
You are an EDITOR, not a researcher. Do NOT invent facts, relationships, or contexts.
1. Do NOT invent wikilinks. Only include a wikilink if the NEW DOCUMENT explicitly mentions that entity.
2. Do NOT copy the section headings from the examples unless the new document contains the relevant information.

CRITICAL RULES FOR TAGS & TITLES:
1. Tags MUST be PascalCase.
2. Select 1 to 3 tags from the APPROVED TAG MENU below.
3. The `aliases` array MUST contain at least one descriptive title for the note based on its content.

APPROVED TAG MENU:
[{tag_menu}]

The note MUST begin with EXACTLY this YAML frontmatter structure:

---
aliases: [Title of the note]
tags: [Tag1, Tag2] 
status: <one of: inbox, draft, active, done, archived>
---

After the frontmatter, write the FULL note body using Markdown formatting (headings, lists, tables) based on the new document. Do not just output the title; you MUST output the complete clinical content.

Here are examples of existing notes to show you the formatting style:

{examples_text}

Now read this new document and produce the note.

--- NEW DOCUMENT ---
{document_text.strip()}

Return ONLY the note (frontmatter + body). Do not include any conversational text.
"""

def upload_document(file_path: Path) -> list[str]:
    url = f"{ANYTHINGLLM_URL}/api/v1/document/upload"
    
    # Retry up to 3 times if the server is busy
    for attempt in range(3):
        try:
            # Ensure the file isn't locked before reading
            time.sleep(0.5) 
            
            with file_path.open("rb") as f:
                files = {"file": (file_path.name, f, "text/markdown")}
                data = {"addToWorkspaces": WORKSPACE_SLUG}
                r = requests.post(url, headers={"Authorization": f"Bearer {API_KEY}"}, files=files, data=data, timeout=120)
            
            # If it's a 500 error, wait and try again
            if r.status_code == 500:
                log.warning(f"Server returned 500 on upload. Retrying in 2s... (Attempt {attempt+1}/3)")
                time.sleep(2)
                continue
                
            r.raise_for_status()
            payload = r.json()
            if not payload.get("success"):
                raise RuntimeError(f"Upload failed: {payload.get('error')}")
                
            return [d["location"] for d in payload.get("documents", []) if "location" in d]
            
        except Exception as e:
            if attempt == 2: # Last attempt
                raise RuntimeError(f"Upload failed after retries: {e}")
            log.warning(f"Upload attempt {attempt+1} failed: {e}. Retrying...")
            time.sleep(2)

def delete_documents(locations: list[str]) -> None:
    if not locations: return
    try:
        r = requests.delete(f"{ANYTHINGLLM_URL}/api/v1/system/remove-documents", headers={"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"}, json={"names": locations}, timeout=60)
        r.raise_for_status()
    except Exception as e:
        log.warning("Could not remove upload(s): %s", e)

def chat_completion(prompt: str) -> str:
    url = f"{ANYTHINGLLM_URL}/api/v1/workspace/{WORKSPACE_SLUG}/chat"
    payload = {"message": prompt, "mode": "query", "sessionId": None}
    r = requests.post(url, headers={"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"}, json=payload, timeout=600)
    r.raise_for_status()
    data = r.json()
    if data.get("error"):
        raise RuntimeError(f"AnythingLLM error: {data['error']}")
    return data.get("textResponse", "")

def parse_response(response: str) -> str:
    # Strip <think> blocks
    text = re.sub(r'<think>.*?</think>', '', response, flags=re.DOTALL).strip()
    # Strip markdown blocks
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].startswith("```"): lines = lines[1:]
        if lines and lines[-1].strip() == "```": lines = lines[:-1]
        text = "\n".join(lines).strip()
    # Cut to first ---
    start_idx = text.find("---")
    if start_idx != -1: text = text[start_idx:]
    if not text: raise ValueError("Model returned an empty response")
    return text

FM_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)

def validate_note(note_body: str) -> dict:
    match = FM_RE.match(note_body)
    if not match: raise ValueError("Note does not start with a YAML frontmatter block")
    try:
        fm = yaml.safe_load(match.group(1)) or {}
    except yaml.YAMLError as e:
        raise ValueError(f"Invalid YAML frontmatter: {e}")

    missing = {"aliases", "tags", "status"} - set(fm.keys())
    if missing: raise ValueError(f"Missing frontmatter keys: {sorted(missing)}")
    for key in ("aliases", "tags"):
        if not isinstance(fm[key], list): raise ValueError(f"'{key}' must be a YAML list")
    if "status" in fm and isinstance(fm["status"], str):
        fm["status"] = fm["status"].lower()
    if fm["status"] not in VALID_STATUS:
        raise ValueError(f"Invalid status '{fm['status']}'")
    invalid_tags = [t for t in fm["tags"] if t not in AVAILABLE_TAGS]
    if invalid_tags:
        raise ValueError(f"You used unapproved tags: {invalid_tags}.")

    # --- NEW SAFETY CHECK ---
    # Remove the frontmatter and H1 headings to check if actual body content exists
    body_only = FM_RE.sub('', note_body)
    body_only = re.sub(r'^#+\s+.*$', '', body_only, flags=re.MULTILINE).strip()
    
    if len(body_only) < 50:
        raise ValueError("The generated note body is too short. You must output the full clinical content from the document, not just the title.")
    # ------------------------

    return fm

def derive_title(fm: dict, note_body: str) -> str:
    # 1. Try aliases first
    if fm.get("aliases") and len(fm["aliases"]) > 0:
        return str(fm["aliases"][0])
    
    # 2. Try any Markdown heading (H1, H2, etc.)
    m = re.search(r"^#+\s+(.+)$", note_body, re.MULTILINE)
    if m: 
        return m.group(1).strip()
        
    return "untitled"

def write_note(note_body: str, target_dir: Path, fm: dict) -> Path:
    target_dir.mkdir(parents=True, exist_ok=True)
    title = derive_title(fm, note_body)
    safe_title = re.sub(r'[<>:"/\\|?*]', '', title).strip()
    if not safe_title: safe_title = "Untitled Note"
    path = target_dir / f"{safe_title}.md"
    n = 2
    while path.exists():
        path = target_dir / f"{safe_title} {n}.md"
        n += 1
    path.write_text(note_body.rstrip() + "\n", encoding="utf-8")
    return path

def move_to(folder: Path, src: Path, reason: Optional[str] = None) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    
    # If it's already gone, it means a previous step successfully moved it.
    if not src.exists():
        return src
        
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    dst = folder / f"{stamp}-{src.name}"
    
    moved = False
    for i in range(3):
        try:
            shutil.move(str(src), str(dst))
            moved = True
            break
        except PermissionError:
            time.sleep(1)
        except Exception as e:
            log.error(f"Failed to move file: {e}")
            break

    if not moved and src.exists():
        try:
            shutil.copy2(str(src), str(dst))
            for i in range(5):
                try:
                    os.remove(str(src))
                    break
                except Exception:
                    time.sleep(1)
        except Exception as e:
            log.error(f"Fallback copy/delete failed: {e}")
            return src
            
    if reason is not None and dst.exists():
        try:
            dst.with_suffix(dst.suffix + ".error.txt").write_text(reason, encoding="utf-8")
        except Exception:
            pass
            
    return dst
    
def find_similar_notes(text_snippet: str) -> list[dict]:
    """Uses AnythingLLM's vector search to find existing notes related to the text."""
    snippet = text_snippet[:2500]
    
    url = f"{ANYTHINGLLM_URL}/api/v1/workspace/{WORKSPACE_SLUG}/vector-search"
    payload = {"query": snippet, "topN": 3} # Get top 3 matches
    
    try:
        # Vector search is instant, so a 30-second timeout is plenty
        r = requests.post(url, headers={"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"}, json=payload, timeout=30)
        r.raise_for_status()
        data = r.json()
        
        results = data.get("results", [])
        
        existing_files = []
        for result in results:
            # AnythingLLM usually stores the title in metadata.title
            title = result.get("metadata", {}).get("title", "")
            score = result.get("score", 0.0)
            
            # Only flag as a duplicate if the semantic similarity is high (e.g., > 0.75)
            if score < 0.75:
                continue
                
            if not title.endswith(".md"):
                title += ".md"
                
            file_path = NOTES_FOLDER / title
            if file_path.exists():
                existing_files.append({
                    "title": title,
                    "path": file_path,
                    "content": file_path.read_text(encoding="utf-8")
                })
        
        return existing_files
    except Exception as e:
        log.warning(f"Vector search failed: {e}")
        return []

def process_file(path: Path) -> None:
    log.info("Processing: %s", path.name)
    locations: list[str] = []

    try:
        # 1. Upload to AnythingLLM
        locations = upload_document(path)
        document_text = read_text(path)

        # 2. Check for overlaps (Duplicate Detection)
        log.info("Checking for overlaps in existing notes...")
        similar_notes = find_similar_notes(document_text)
        
        if similar_notes:
            top_match = similar_notes[0]['title'].replace('.md', '')
            log.warning(f"Duplicate detected! Overlaps with: {top_match}")
            
            REVIEW_FOLDER.mkdir(parents=True, exist_ok=True)
            review_note_path = REVIEW_FOLDER / f"{path.stem}-REVIEW.md"
            review_content = (
                f"> [!warning] Potential Duplicate Detected\n"
                f"> This document overlaps with [[{top_match}]].\n"
                f"> Review the text below and merge any new information into the existing note.\n\n"
                f"# Raw Extracted Text\n\n{document_text}"
            )
            review_note_path.write_text(review_content, encoding="utf-8")
            log.info(f"Created review file: {review_note_path.name}")
            
            # CHANGE THIS LINE: Move the raw file to processed instead of review
            move_to(PROCESSED_FOLDER, path) 
            
            if DELETE_UPLOAD_AFTER_SUCCESS and locations:
                delete_documents(locations)
                
            return # STOP PROCESSING HERE! Do not generate a new note.

        # 3. If no overlap, generate a new note
        log.info("No significant overlap found. Generating new note...")
        
        prompt = build_prompt(document_text)
        response = ""
        last_err = None
        note_body = ""
        fm = {}

        for attempt in range(1, MAX_RETRIES + 2):
            if attempt > 1 and response:
                attempt_prompt = f"{response}\n\nYour previous output failed validation: {last_err}. Produce the full corrected note."
            else:
                attempt_prompt = prompt

            try:
                response = chat_completion(attempt_prompt)
                note_body = parse_response(response)
                fm = validate_note(note_body)
                log.info("Validation OK (attempt %d)", attempt)
                break
            except Exception as e:
                last_err = e
                log.warning("Attempt %d failed: %s", attempt, e)
                log.warning("RAW MODEL OUTPUT:\n%s\n-------------------", response)
        else:
            raise RuntimeError(f"Validation failed after retries: {last_err}")

        # 4. Inject the [!ai] banner and generated_by property
        banner = "> [!ai] AI Generated\n> This note was drafted automatically by the local LLM pipeline.\n\n"
        
        parts = note_body.split('---', 2)
        if len(parts) >= 3:
            frontmatter = parts[1].strip()
            frontmatter += "\ngenerated_by: Pipeline"
            note_body = f"---\n{frontmatter}\n---\n\n{banner}{parts[2].strip()}"

        # 5. Write the note
        written = write_note(note_body, NOTES_FOLDER, fm)
        log.info("Wrote note: %s", written.name)

        # 6. Cleanup and archive
        if DELETE_UPLOAD_AFTER_SUCCESS and locations:
            delete_documents(locations)

        dest = move_to(PROCESSED_FOLDER, path)
        log.info("Archived original → %s", dest.name)

    except Exception as e:
        log.error("FAILED %s: %s", path.name, e)
        if path.exists():
            move_to(FAILED_FOLDER, path, reason=str(e))

def wait_for_stable(path: Path, timeout: float = 10.0) -> bool:
    last = -1
    elapsed = 0.0
    while elapsed < timeout:
        if not path.exists(): return False
        size = path.stat().st_size
        if size == last and size > 0: return True
        last = size
        time.sleep(0.5)
        elapsed += 0.5
    return path.exists()

class IntakeHandler(FileSystemEventHandler):
    def __init__(self) -> None:
        super().__init__()
        self._lock = threading.Lock()
        self._recent: dict[str, float] = {}

    def on_created(self, event) -> None:
        if event.is_directory: return
        self._maybe_process(Path(event.src_path))

    def on_moved(self, event) -> None:
        if event.is_directory: return
        self._maybe_process(Path(event.dest_path))

    def _maybe_process(self, path: Path) -> None:
        if path.parent.resolve() != INTAKE_FOLDER.resolve(): return
        if path.suffix.lower() not in SUPPORTED_EXTS: return

        with self._lock:
            now = time.time()
            if now - self._recent.get(str(path), 0) < 1.0: return
            self._recent[str(path)] = now

        if not wait_for_stable(path):
            return

        try:
            process_file(path)
        except Exception as e:
            log.error("Unhandled error processing %s: %s", path, e)

def initial_scan() -> None:
    for p in sorted(INTAKE_FOLDER.iterdir()):
        if p.is_file() and p.suffix.lower() in SUPPORTED_EXTS:
            log.info("Startup scan: %s", p.name)
            try:
                process_file(p)
            except Exception as e:
                log.error("Startup scan failed for %s: %s", p, e)

def main() -> None:
    for d in (INTAKE_FOLDER, PROCESSED_FOLDER, FAILED_FOLDER, NOTES_FOLDER, REVIEW_FOLDER):
        d.mkdir(parents=True, exist_ok=True)

    log.info("Watching %s", INTAKE_FOLDER)
    initial_scan()

    observer = Observer()
    observer.schedule(IntakeHandler(), str(INTAKE_FOLDER), recursive=False)
    observer.start()
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        log.info("Shutting down")
    finally:
        observer.stop()
        observer.join()

if __name__ == "__main__":
    main()