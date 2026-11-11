#!/usr/bin/env python3
"""
Obsidian intake → AnythingLLM → Tag-based formatted note writer.

Drop a .md (or .txt) file into 01-Intake/. The script will:
  1. Upload it to AnythingLLM.
  2. Ask the model to format it as a new note, assigning tags from your
     strict AVAILABLE_TAGS whitelist.
  3. Validate the frontmatter (aliases, tags, status) and ensure no 
     hallucinated tags were used.
  4. Write the note into your single 01-Notes folder.
  5. Archive the original to 02-Processed/ (or 03-Failed/ on error).

Install:  pip install requests watchdog pyyaml
Run:      python intake_bot.py
"""

from __future__ import annotations

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

# ===========================================================================
# Configuration  — EDIT THESE
# ===========================================================================

VAULT_PATH = Path(r"D:\Obsidian\Vaults\Test Vault")
INTAKE_FOLDER     = VAULT_PATH / "01-intake"
PROCESSED_FOLDER  = VAULT_PATH / "02-processed"
FAILED_FOLDER     = VAULT_PATH / "03-failed"
NOTES_FOLDER      = VAULT_PATH / "01-notes"      # Where all new notes will go

ANYTHINGLLM_URL   = "http://localhost:3001"
API_KEY           = "23F80MY-FT3M6ZJ-N3XR6BQ-71V64W5"
WORKSPACE_SLUG    ="my-workspace"                   # from the workspace URL

SUPPORTED_EXTS    = {".md", ".txt"}
VALID_STATUS      = {"inbox", "draft", "active", "done", "archived"}

MAX_RETRIES       = 2                            # Extra attempts after validation fails
MAX_DOC_CHARS     = 60_000                       # Truncate very large inputs

# Remove the raw upload from AnythingLLM after the note is written.
# Leave True when AnythingLLM Sync will (re)embed the generated note.
DELETE_UPLOAD_AFTER_SUCCESS = True



# --- Tag Taxonomy ---
# The LLM will ONLY be allowed to use tags from this list.
AVAILABLE_TAGS = [
    "Cardiology",
    "InformationArchitecture",
    "InformationProduct",
    "Investigation",
    "DiseasePathway",
    "GraphNavigation",
    "System",
    "CardiacImaging",
    "Overview",
    "Representation",
    "Electrocardiography",
    "Echocardiography",
    "GraphSupporting",
    "Haemodynamics",
    "InterventionPathway",
    "Presentation",
    "ArchitecturePrinciple",
    "ClinicalAssessment",
    "CardiacDevices",
    "ClinicalDecision",
    "ClinicalManagement",
    "ClinicalProcedure",
    "ExercisePhysiology",
    "Genetics",
    "Geometry",
    "ImplantsAndDevices",
    "InvasiveAssessment",
    "LaboratoryMedicine",
    "LongitudinalAssessment",
    "MyocardialFunction",
    "NHS",
    "NuclearMedicine",
    "PulmonaryHypertension",
    "ValvularHeartDisease",
    "VentricularFunction"
]

# Few-shot examples. Paths are RELATIVE to VAULT_PATH.
# Pick 3-4 diverse notes that show how you combine tags.
EXAMPLES = [
    "01-notes/Cardiac CT.md",
    "01-notes/Coronary Artery Disease.md",
    "01-notes/Catheter Ablation.md"
]

# ===========================================================================
# Logging
# ===========================================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("intake")

# ===========================================================================
# Helpers: prompt building
# ===========================================================================

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
        log.warning("Document truncated to %d chars", MAX_DOC_CHARS)
        document_text = document_text[:MAX_DOC_CHARS] + "\n[... truncated ...]"

    tag_menu = ", ".join(AVAILABLE_TAGS)

    return f"""You are an Obsidian vault editor for a medical and architectural knowledge base. 
Read the new document below and produce a new note.

CRITICAL RULES FOR TAGS:
1. Tags MUST be PascalCase (e.g., CardiacImaging, not cardiac imaging or cardiac_imaging).
2. You MUST select 2 to 4 tags from the APPROVED TAG MENU below. Do not invent new tags.
3. Always include the broad domain tag (e.g., Cardiology or InformationArchitecture) if applicable.

APPROVED TAG MENU:
[{tag_menu}]

The note MUST begin with EXACTLY this YAML frontmatter structure:

---
aliases: [alternative names]
tags: [Tag1, Tag2, Tag3] 
status: <one of: inbox, draft, active, done, archived>
---

After the frontmatter, write the note body using the same heading structure, formatting, and writing style as the examples.

Here are examples of existing notes:

{examples_text}

Now read this new document and produce the note.

--- NEW DOCUMENT ---
{document_text.strip()}

Return ONLY the note (frontmatter + body). Do not include any conversational text.
"""

# ===========================================================================
# Helpers: AnythingLLM API
# ===========================================================================

def upload_document(file_path: Path) -> list[str]:
    url = f"{ANYTHINGLLM_URL}/api/v1/document/upload"
    with file_path.open("rb") as f:
        files = {"file": (file_path.name, f, "text/markdown")}
        data = {"addToWorkspaces": WORKSPACE_SLUG}
        r = requests.post(
            url,
            headers={"Authorization": f"Bearer {API_KEY}"},
            files=files,
            data=data,
            timeout=120,
        )
    r.raise_for_status()
    payload = r.json()
    if not payload.get("success"):
        raise RuntimeError(f"Upload failed: {payload.get('error')}")
    return [d["location"] for d in payload.get("documents", []) if "location" in d]

def delete_documents(locations: list[str]) -> None:
    if not locations:
        return
    try:
        r = requests.delete(
            f"{ANYTHINGLLM_URL}/api/v1/system/remove-documents",
            headers={
                "Authorization": f"Bearer {API_KEY}",
                "Content-Type": "application/json",
            },
            json={"names": locations},
            timeout=60,
        )
        r.raise_for_status()
        log.info("Removed upload(s) from AnythingLLM: %s", locations)
    except Exception as e:
        log.warning("Could not remove upload(s): %s", e)

def chat_completion(prompt: str) -> str:
    url = f"{ANYTHINGLLM_URL}/api/v1/workspace/{WORKSPACE_SLUG}/chat"
    payload = {"message": prompt, "mode": "query", "sessionId": None}
    r = requests.post(
        url,
        headers={
            "Authorization": f"Bearer {API_KEY}",
            "Content-Type": "application/json",
        },
        json=payload,
        timeout=600,
    )
    r.raise_for_status()
    data = r.json()
    if data.get("error"):
        raise RuntimeError(f"AnythingLLM error: {data['error']}")
    return data.get("textResponse", "")

# ===========================================================================
# Helpers: response parsing & validation
# ===========================================================================

def strip_outer_fence(text: str) -> str:
    text = text.strip()
    if not text.startswith("```"):
        return text
    lines = text.splitlines()
    if lines and lines[0].startswith("```"):
        lines = lines[1:]
    if lines and lines[-1].strip() == "```":
        lines = lines[:-1]
    return "\n".join(lines).strip()

def parse_response(response: str) -> str:
    # 1. Remove <think>...</think> blocks if present
    text = re.sub(r'<think>.*?</think>', '', response, flags=re.DOTALL).strip()
    
    # 2. Strip surrounding markdown code blocks
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines).strip()
        
    # 3. Find the first '---' and cut everything before it
    start_idx = text.find("---")
    if start_idx != -1:
        text = text[start_idx:]
        
    if not text:
        raise ValueError("Model returned an empty response")
        
    return text
FM_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)

def validate_note(note_body: str) -> dict:
    match = FM_RE.match(note_body)
    if not match:
        raise ValueError("Note does not start with a YAML frontmatter block")

    try:
        fm = yaml.safe_load(match.group(1)) or {}
    except yaml.YAMLError as e:
        raise ValueError(f"Invalid YAML frontmatter: {e}")

    missing = {"aliases", "tags", "status"} - set(fm.keys())
    if missing:
        raise ValueError(f"Missing frontmatter keys: {sorted(missing)}")

    for key in ("aliases", "tags"):
        if not isinstance(fm[key], list):
            raise ValueError(f"'{key}' must be a YAML list")

    # Make status case-insensitive and force it to lowercase for consistency
    if "status" in fm and isinstance(fm["status"], str):
        fm["status"] = fm["status"].lower()

    if fm["status"] not in VALID_STATUS:
        raise ValueError(
            f"Invalid status '{fm['status']}', must be one of "
            f"{sorted(VALID_STATUS)}"
        )

    invalid_tags = [t for t in fm["tags"] if t not in AVAILABLE_TAGS]
    if invalid_tags:
        raise ValueError(
            f"You used unapproved tags: {invalid_tags}. "
            f"You MUST ONLY use tags from the APPROVED TAG MENU."
        )

    return fm

# ===========================================================================
# Helpers: writing into the vault
# ===========================================================================

def slugify(text: str, max_len: int = 60) -> str:
    text = re.sub(r"[^\w\s-]", "", text).strip().lower()
    text = re.sub(r"[\s_-]+", "-", text)
    return text[:max_len].strip("-") or "untitled"

def derive_title(fm: dict, note_body: str) -> str:
    if fm.get("aliases"):
        return str(fm["aliases"][0])
    m = re.search(r"^#\s+(.+)$", note_body, re.MULTILINE)
    if m:
        return m.group(1).strip()
    return "untitled"

def write_note(note_body: str, target_dir: Path, fm: dict) -> Path:
    target_dir.mkdir(parents=True, exist_ok=True)
    
    # We use Title Case for filenames based on the title/alias
    title = derive_title(fm, note_body)
    # Basic sanitization for Windows/Mac filenames
    safe_title = re.sub(r'[<>:"/\\|?*]', '', title).strip()
    if not safe_title:
        safe_title = "Untitled Note"
        
    path = target_dir / f"{safe_title}.md"
    
    # Handle duplicate names
    n = 2
    while path.exists():
        path = target_dir / f"{safe_title} {n}.md"
        n += 1

    path.write_text(note_body.rstrip() + "\n", encoding="utf-8")
    return path

# ===========================================================================
# Archiving
# ===========================================================================

def move_to(folder: Path, src: Path, reason: Optional[str] = None) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    dst = folder / f"{stamp}-{src.name}"
    shutil.move(str(src), str(dst))
    if reason is not None:
        dst.with_suffix(dst.suffix + ".error.txt").write_text(
            reason, encoding="utf-8"
        )
    return dst

# ===========================================================================
# Orchestration
# ===========================================================================

def process_file(path: Path) -> None:
    log.info("Processing: %s", path.name)
    locations: list[str] = []

    try:
        # --- 1. Upload to AnythingLLM ---
        try:
            locations = upload_document(path)
            log.info("Uploaded to AnythingLLM: %s", locations or "(no location)")
        except Exception as e:
            raise RuntimeError(f"Upload step failed: {e}")

        # --- 2. Prompt + chat, with correction retries ---
        document_text = read_text(path)
        prompt = build_prompt(document_text)

        response = ""
        last_err: Optional[Exception] = None
        note_body = ""
        fm: dict = {}

        for attempt in range(1, MAX_RETRIES + 2):
            if attempt > 1 and response:
                # Tell the model exactly why the previous attempt failed
                attempt_prompt = (
                    f"{response}\n\n"
                    f"Your previous output failed validation: {last_err}. "
                    f"Produce the full corrected note now."
                )
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

        # --- 3. Write the note ---
        written = write_note(note_body, NOTES_FOLDER, fm)
        log.info("Wrote note: %s", written.name)

        # --- 4. Clean up the raw upload in AnythingLLM ---
        if DELETE_UPLOAD_AFTER_SUCCESS and locations:
            delete_documents(locations)

        # --- 5. Archive the original ---
        dest = move_to(PROCESSED_FOLDER, path)
        log.info("Archived original → %s", dest.name)

    except Exception as e:
        log.error("FAILED %s: %s", path.name, e)
        if path.exists():
            move_to(FAILED_FOLDER, path, reason=str(e))

# ===========================================================================
# Watcher
# ===========================================================================

def wait_for_stable(path: Path, timeout: float = 10.0) -> bool:
    last = -1
    elapsed = 0.0
    while elapsed < timeout:
        if not path.exists():
            return False
        size = path.stat().st_size
        if size == last and size > 0:
            return True
        last = size
        time.sleep(0.5)
        elapsed += 0.5
    return path.exists()

class IntakeHandler(FileSystemEventHandler):
    def __init__(self) -> None:
        super().__init__()
        self._lock = threading.Lock()
        self._recent: dict[str, float] = {}

    def on_created(self, event) -> None:                # noqa: ANN001
        if event.is_directory:
            return
        self._maybe_process(Path(event.src_path))

    def on_moved(self, event) -> None:                  # noqa: ANN001
        if event.is_directory:
            return
        self._maybe_process(Path(event.dest_path))

    def _maybe_process(self, path: Path) -> None:
        if path.parent.resolve() != INTAKE_FOLDER.resolve():
            return
        if path.suffix.lower() not in SUPPORTED_EXTS:
            return

        with self._lock:
            now = time.time()
            if now - self._recent.get(str(path), 0) < 1.0:
                return
            self._recent[str(path)] = now

        if not wait_for_stable(path):
            log.warning("File did not stabilise, skipping: %s", path)
            return

        try:
            process_file(path)
        except Exception as e:
            log.error("Unhandled error processing %s: %s", path, e)

# ===========================================================================
# Entry point
# ===========================================================================

def initial_scan() -> None:
    """Process anything already sitting in the intake folder at startup."""
    for p in sorted(INTAKE_FOLDER.iterdir()):
        if p.is_file() and p.suffix.lower() in SUPPORTED_EXTS:
            log.info("Startup scan: %s", p.name)
            try:
                process_file(p)
            except Exception as e:
                log.error("Startup scan failed for %s: %s", p, e)

def main() -> None:
    for d in (INTAKE_FOLDER, PROCESSED_FOLDER, FAILED_FOLDER, NOTES_FOLDER):
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