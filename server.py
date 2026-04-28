#!/usr/bin/env python3
"""
NoteForge — Obsidian Daily Note Backend
=========================================
Flask server that receives entries from the HTML frontend,
sends them to a local Ollama LLM, and writes the expanded
Markdown note into an Obsidian vault.

Requirements:
    pip install flask flask-cors requests

Usage:
    python server.py [--port 5000] [--vault ~/obsidian-vault] [--model llama3]
"""

import os
import sys
import json
import logging
import argparse
import subprocess
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import requests
from flask import Flask, request, jsonify
from flask_cors import CORS

# ─────────────────────────────────────────────────────────
# CONFIG & LOGGING
# ─────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("noteforge.log"),
    ],
)
log = logging.getLogger("noteforge")

# ─────────────────────────────────────────────────────────
# APP
# ─────────────────────────────────────────────────────────

app = Flask(__name__)
CORS(app, resources={r"/*": {"origins": "*"}})

# ─────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────

def get_cfg(payload: dict) -> dict:
    """Merge defaults with any config sent from the frontend."""
    defaults = {
        "backend":    "http://localhost:5000",
        "ollama":     "http://localhost:11434",
        "model":      "llama3",
        "vault":      str(Path.home() / "obsidian-vault"),
        "folder":     "Daily Notes",
        "dateformat": "YYYY-MM-DD",
        "temp":       0.75,
        "tokens":     4096,
        "autoopen":   "true",
    }
    return {**defaults, **(payload.get("config") or {})}


def resolve_vault(cfg: dict) -> Path:
    """Resolve the vault path, expanding ~ and env vars."""
    raw = cfg.get("vault", "~/obsidian-vault")
    return Path(os.path.expandvars(os.path.expanduser(raw)))


def format_date(cfg: dict, dt: Optional[datetime] = None) -> str:
    """Format a date according to the configured date format."""
    if dt is None:
        dt = datetime.now()
    fmt = cfg.get("dateformat", "YYYY-MM-DD")
    mapping = {
        "YYYY": dt.strftime("%Y"),
        "MM":   dt.strftime("%m"),
        "DD":   dt.strftime("%d"),
    }
    result = fmt
    for k, v in mapping.items():
        result = result.replace(k, v)
    return result


def slugify(text: str) -> str:
    """Convert text to a safe filename slug."""
    text = re.sub(r"[^\w\s-]", "", text.lower())
    text = re.sub(r"[\s_-]+", "-", text).strip("-")
    return text[:80]


def get_streak(vault: Path, folder: str) -> int:
    """Count the consecutive day streak of daily notes."""
    notes_dir = vault / folder
    if not notes_dir.exists():
        return 0
    streak = 0
    check = datetime.now().date()
    for _ in range(365):
        found = any(str(check) in f.name for f in notes_dir.glob("*.md"))
        if found:
            streak += 1
            check -= timedelta(days=1)
        else:
            break
    return streak


# ─────────────────────────────────────────────────────────
# PROMPT BUILDER
# ─────────────────────────────────────────────────────────

def build_user_message(data: dict) -> str:
    """
    Construct the detailed user message that gets sent to Ollama.
    This is separate from the system prompt so the model sees
    structured raw input.
    """
    title    = data.get("title",    "Untitled")
    date     = data.get("date",     datetime.now().strftime("%Y-%m-%d"))
    body     = data.get("body",     "")
    mood     = data.get("mood",     "Not specified")
    energy   = data.get("energy",   "?")
    focus    = data.get("focus",    "general")
    wins     = data.get("wins",     "")
    blockers = data.get("blockers", "")
    tomorrow = data.get("tomorrow", "")
    tags     = data.get("tags",     [])
    links    = data.get("links",    "")
    tone     = data.get("tone",     "reflective")
    length   = data.get("length",   "long")
    extra    = data.get("extra",    "")
    features = data.get("features", [])

    # Map length label to word targets
    word_targets = {
        "medium": "~400–500 words",
        "long":   "~800–1000 words",
        "epic":   "1500+ words",
    }
    target = word_targets.get(length, "~800 words")

    lines = [
        "=== RAW DAILY NOTE DATA ===",
        "",
        f"DATE:      {date}",
        f"TITLE:     {title}",
        f"MOOD:      {mood}",
        f"ENERGY:    {energy}/10",
        f"FOCUS:     {focus}",
        "",
        "--- MAIN ENTRY ---",
        body,
        "",
    ]

    if wins:
        lines += ["--- WINS / ACCOMPLISHMENTS ---", wins, ""]
    if blockers:
        lines += ["--- BLOCKERS / CHALLENGES ---", blockers, ""]
    if tomorrow:
        lines += ["--- TOMORROW'S INTENTIONS ---", tomorrow, ""]
    if tags:
        tag_str = ", ".join(f"#{t}" for t in tags)
        lines += [f"--- TAGS --- {tag_str}", ""]
    if links:
        lines += [f"--- OBSIDIAN LINKS TO WEAVE IN --- {links}", ""]

    lines += [
        "=== GENERATION INSTRUCTIONS ===",
        f"Tone: {tone}",
        f"Target length: {target}",
    ]

    if features:
        lines += [
            "",
            "Required Obsidian features to include:",
            *[f"  • {f}" for f in features],
        ]

    if extra:
        lines += ["", "Additional instructions:", extra]

    lines += [
        "",
        "Please generate the complete, expanded Obsidian daily note in Markdown now.",
        "Start directly with the YAML frontmatter (---), then the note body.",
        "Do NOT include any preamble or explanation — output ONLY the Markdown.",
    ]

    return "\n".join(lines)


def build_system_prompt(data: dict) -> str:
    """Use the custom system prompt if provided, otherwise use a rich default."""
    custom = data.get("system_prompt", "").strip()
    if custom:
        return custom

    return (
        "You are a meticulous, thoughtful Obsidian daily note assistant. "
        "You write deeply reflective, detailed Markdown notes for personal knowledge management. "
        "Always include valid YAML frontmatter with date, tags, mood, energy, focus, and aliases. "
        "Use Obsidian [[wikilinks]] for concepts, people, and projects. "
        "Include callout blocks: > [!insight], > [!tip], > [!warning], > [!quote]. "
        "Generate at least one Mermaid mindmap (mindmap syntax) and one Mermaid timeline if there are events. "
        "Use h2 (##) and h3 (###) headers to structure the note. "
        "Write in a warm, introspective first-person voice. "
        "The note should be long, detailed, and genuinely useful to revisit weeks later. "
        "Do NOT wrap the output in any code fences — output raw Markdown only."
    )


# ─────────────────────────────────────────────────────────
# OLLAMA CALL
# ─────────────────────────────────────────────────────────

def call_ollama(
    system_prompt: str,
    user_message: str,
    host: str,
    model: str,
    temperature: float = 0.75,
    max_tokens: int = 4096,
) -> str:
    """
    Send a chat request to Ollama and return the generated text.
    Supports both /api/chat and falls back to /api/generate.
    """
    url = f"{host.rstrip('/')}/api/chat"

    payload = {
        "model":  model,
        "stream": False,
        "options": {
            "temperature":   temperature,
            "num_predict":   max_tokens,
            "top_p":         0.92,
            "repeat_penalty": 1.1,
        },
        "messages": [
            {"role": "system",  "content": system_prompt},
            {"role": "user",    "content": user_message},
        ],
    }

    log.info("→ Ollama %s model=%s temp=%.2f max_tokens=%d", url, model, temperature, max_tokens)

    try:
        resp = requests.post(url, json=payload, timeout=300)
        resp.raise_for_status()
        data = resp.json()

        # /api/chat response
        if "message" in data:
            return data["message"]["content"]

        # fallback for older Ollama versions using /api/generate
        if "response" in data:
            return data["response"]

        raise ValueError(f"Unexpected Ollama response shape: {list(data.keys())}")

    except requests.exceptions.ConnectionError:
        raise RuntimeError(
            f"Cannot connect to Ollama at {host}. "
            "Make sure Ollama is running: ollama serve"
        )
    except requests.exceptions.Timeout:
        raise RuntimeError("Ollama request timed out (300 s). Try a smaller model or shorter prompt.")
    except requests.exceptions.HTTPError as e:
        body = ""
        try:
            body = resp.text[:300]
        except Exception:
            pass
        raise RuntimeError(f"Ollama HTTP {resp.status_code}: {body}") from e


# ─────────────────────────────────────────────────────────
# NOTE WRITER
# ─────────────────────────────────────────────────────────

def write_note_to_vault(note_content: str, filename: str, vault: Path, folder: str) -> Path:
    """Create the Markdown file in the vault's daily notes folder."""
    notes_dir = vault / folder
    notes_dir.mkdir(parents=True, exist_ok=True)

    note_path = notes_dir / filename
    # If filename exists, append a suffix
    if note_path.exists():
        stem = note_path.stem
        counter = 1
        while note_path.exists():
            note_path = notes_dir / f"{stem}-{counter}.md"
            counter += 1

    note_path.write_text(note_content, encoding="utf-8")
    log.info("✓ Note written: %s (%d bytes)", note_path, len(note_content.encode("utf-8")))
    return note_path


def open_in_obsidian(vault: Path, note_path: Path) -> None:
    """Try to open the note in Obsidian using the obsidian:// URI scheme."""
    try:
        vault_name = vault.name
        rel = note_path.relative_to(vault)
        uri = f"obsidian://open?vault={vault_name}&file={str(rel)}"
        log.info("Opening Obsidian URI: %s", uri)

        if sys.platform == "darwin":
            subprocess.Popen(["open", uri])
        elif sys.platform == "linux":
            subprocess.Popen(["xdg-open", uri])
        elif sys.platform == "win32":
            os.startfile(uri)

    except Exception as e:
        log.warning("Could not auto-open in Obsidian: %s", e)


# ─────────────────────────────────────────────────────────
# ROUTES
# ─────────────────────────────────────────────────────────

@app.route("/health", methods=["GET"])
def health():
    """Health check — also pings Ollama to report status."""
    cfg = get_cfg({})
    ollama_ok = False
    ollama_status = "unreachable"
    model = cfg["model"]

    try:
        r = requests.get(f"{cfg['ollama']}/api/tags", timeout=4)
        if r.ok:
            tags = r.json().get("models", [])
            available = [m["name"] for m in tags]
            ollama_ok = True
            ollama_status = f"ok — {len(available)} model(s) loaded"
            log.info("Ollama healthy. Models: %s", available)
    except Exception as e:
        ollama_status = str(e)
        log.warning("Ollama ping failed: %s", e)

    return jsonify({
        "status":        "ok",
        "ollama":        ollama_ok,
        "ollama_status": ollama_status,
        "model":         model,
        "server":        "NoteForge v1.0",
    })


@app.route("/models", methods=["GET"])
def list_models():
    """Return available Ollama models."""
    cfg = get_cfg(request.args)
    try:
        r = requests.get(f"{cfg['ollama']}/api/tags", timeout=5)
        r.raise_for_status()
        models = [m["name"] for m in r.json().get("models", [])]
        return jsonify({"models": models})
    except Exception as e:
        return jsonify({"error": str(e)}), 502


@app.route("/generate", methods=["POST"])
def generate():
    """
    Main generation endpoint.
    Receives raw entry data, builds the prompt, calls Ollama,
    and returns the generated Markdown note.
    """
    data = request.get_json(force=True) or {}
    cfg  = get_cfg(data)

    log.info(
        "Generate request: date=%s title=%s model=%s",
        data.get("date"), data.get("title"), cfg["model"]
    )

    # Build date-based filename
    date_str = data.get("date") or datetime.now().strftime("%Y-%m-%d")
    title    = data.get("title", "").strip()
    if title:
        filename = f"{date_str}-{slugify(title)}.md"
    else:
        filename = f"{date_str}-daily.md"

    # Build prompts
    system_prompt = build_system_prompt(data)
    user_message  = build_user_message(data)

    log.debug("System prompt (%d chars)", len(system_prompt))
    log.debug("User message  (%d chars)", len(user_message))

    # Call Ollama
    try:
        note_content = call_ollama(
            system_prompt  = system_prompt,
            user_message   = user_message,
            host           = cfg["ollama"],
            model          = cfg["model"],
            temperature    = float(cfg.get("temp", 0.75)),
            max_tokens     = int(cfg.get("tokens", 4096)),
        )
    except RuntimeError as e:
        log.error("Ollama error: %s", e)
        return jsonify({"error": str(e)}), 502

    # Post-process: ensure it's clean Markdown
    note_content = note_content.strip()
    # Strip stray ``` fences if the model wrapped in them despite instructions
    if note_content.startswith("```"):
        lines = note_content.splitlines()
        if lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        note_content = "\n".join(lines).strip()

    word_count = len(note_content.split())
    log.info("Generated note: %d words, %d chars", word_count, len(note_content))

    return jsonify({
        "note":       note_content,
        "filename":   filename,
        "words":      word_count,
        "date":       date_str,
    })


@app.route("/send", methods=["POST"])
def send():
    """
    Write the generated note to the Obsidian vault filesystem.
    Also attempts to open in Obsidian if autoopen is enabled.
    """
    data     = request.get_json(force=True) or {}
    cfg      = get_cfg(data)
    content  = data.get("content", "")
    filename = data.get("filename", "daily.md")

    if not content:
        return jsonify({"error": "No note content provided"}), 400

    vault  = resolve_vault(cfg)
    folder = cfg.get("folder", "Daily Notes")

    log.info("Writing note to vault: %s / %s / %s", vault, folder, filename)

    try:
        note_path = write_note_to_vault(content, filename, vault, folder)
    except PermissionError as e:
        log.error("Permission denied writing note: %s", e)
        return jsonify({"error": f"Permission denied: {e}"}), 500
    except Exception as e:
        log.error("Failed to write note: %s", e)
        return jsonify({"error": str(e)}), 500

    # Auto-open
    if cfg.get("autoopen") == "true":
        open_in_obsidian(vault, note_path)

    streak = get_streak(vault, folder)

    return jsonify({
        "status":   "ok",
        "path":     str(note_path),
        "filename": note_path.name,
        "vault":    str(vault),
        "streak":   streak,
    })


@app.route("/preview", methods=["POST"])
def preview_only():
    """
    Generate a note without saving it.
    Useful for previewing before committing.
    """
    return generate()  # same logic, no write


@app.route("/history", methods=["GET"])
def get_history():
    """
    List existing notes from the vault's daily notes folder,
    newest first.
    """
    cfg    = get_cfg(request.args.to_dict())
    vault  = resolve_vault(cfg)
    folder = cfg.get("folder", "Daily Notes")
    notes_dir = vault / folder

    if not notes_dir.exists():
        return jsonify({"notes": [], "folder": str(notes_dir)})

    notes = []
    for f in sorted(notes_dir.glob("*.md"), reverse=True)[:50]:
        stat = f.stat()
        notes.append({
            "filename": f.name,
            "path":     str(f),
            "size":     stat.st_size,
            "modified": datetime.fromtimestamp(stat.st_mtime).isoformat(),
        })

    return jsonify({"notes": notes, "folder": str(notes_dir), "count": len(notes)})


@app.route("/note/<path:filename>", methods=["GET"])
def get_note(filename: str):
    """Return the raw content of a specific note."""
    cfg       = get_cfg(request.args.to_dict())
    vault     = resolve_vault(cfg)
    folder    = cfg.get("folder", "Daily Notes")
    note_path = vault / folder / filename

    if not note_path.exists():
        return jsonify({"error": "Note not found"}), 404

    content = note_path.read_text(encoding="utf-8")
    return jsonify({
        "filename": filename,
        "content":  content,
        "words":    len(content.split()),
    })


@app.route("/note/<path:filename>", methods=["DELETE"])
def delete_note(filename: str):
    """Delete a note from the vault."""
    cfg       = get_cfg(request.get_json(force=True) or {})
    vault     = resolve_vault(cfg)
    folder    = cfg.get("folder", "Daily Notes")
    note_path = vault / folder / filename

    if not note_path.exists():
        return jsonify({"error": "Note not found"}), 404

    note_path.unlink()
    log.info("Deleted note: %s", note_path)
    return jsonify({"status": "deleted", "filename": filename})


@app.route("/vault/stats", methods=["GET"])
def vault_stats():
    """Return statistics about the vault's daily notes folder."""
    cfg       = get_cfg(request.args.to_dict())
    vault     = resolve_vault(cfg)
    folder    = cfg.get("folder", "Daily Notes")
    notes_dir = vault / folder

    if not notes_dir.exists():
        return jsonify({"exists": False, "notes": 0, "streak": 0})

    all_notes = list(notes_dir.glob("*.md"))
    total_words = 0
    for f in all_notes:
        try:
            total_words += len(f.read_text(encoding="utf-8").split())
        except Exception:
            pass

    streak = get_streak(vault, folder)
    today = datetime.now().strftime("%Y-%m-%d")
    today_notes = [f for f in all_notes if today in f.name]

    return jsonify({
        "exists":       True,
        "vault":        str(vault),
        "folder":       str(notes_dir),
        "total_notes":  len(all_notes),
        "total_words":  total_words,
        "streak":       streak,
        "today_count":  len(today_notes),
    })


# ─────────────────────────────────────────────────────────
# CLI DASHBOARD
# ─────────────────────────────────────────────────────────

CLI_BANNER = r"""
  _   _       _       _____                    
 | \ | |     | |     |  ___|__  _ __ __ _  ___ 
 |  \| | ___ | |_ ___| |_ / _ \| '__/ _` |/ _ \
 | |\  |/ _ \| __/ _ \  _| (_) | | | (_| |  __/
 |_| \_|\___/ \__\___/_|  \___/|_|  \__, |\___|
                                     |___/      
  Obsidian Daily Note Forge  ·  v1.0
"""

def cli_dashboard(vault_path: str, model: str, host: str, folder: str):
    """
    Interactive CLI mode: compose a daily note entirely from the terminal.
    """
    print(CLI_BANNER)

    def ask(prompt: str, default: str = "") -> str:
        val = input(f"  {prompt}" + (f" [{default}]" if default else "") + ": ").strip()
        return val or default

    def ask_multiline(prompt: str) -> str:
        print(f"  {prompt} (blank line to finish):")
        lines = []
        while True:
            line = input("    > ")
            if line == "":
                break
            lines.append(line)
        return "\n".join(lines)

    print("─" * 55)
    print("  New Daily Note")
    print("─" * 55)

    today = datetime.now().strftime("%Y-%m-%d")
    date  = ask("Date", today)
    title = ask("Title / headline", "")
    mood  = ask("Mood", "Neutral")
    energy = ask("Energy (1–10)", "7")
    focus  = ask("Focus area", "general")

    print()
    body     = ask_multiline("What happened today?")
    wins     = ask_multiline("Wins / accomplishments")
    blockers = ask_multiline("Blockers / challenges")
    tomorrow = ask_multiline("Tomorrow's intentions")
    tags_raw = ask("Tags (comma-separated)", "")
    tags     = [t.strip() for t in tags_raw.split(",") if t.strip()]
    links    = ask("Obsidian links to weave in", "")

    print()
    preset_choice = ask("Prompt preset [journal/dev/executive/stoic/creative/minimal]", "journal")

    presets = {
        "journal": "You are a wise journaling companion. Expand raw notes into a rich, reflective first-person journal in Markdown. Minimum 800 words. Include YAML frontmatter, Mermaid mindmap, callout blocks, wikilinks, gratitude section, and tomorrow's action items.",
        "dev":     "You are a senior developer's log assistant. Transform notes into a structured Engineering Log with decisions, debugging sessions, architecture notes, TODOs, and a Mermaid diagram of the day's work.",
        "executive": "Write a sharp executive daily briefing: top decisions, metrics, risks, action items with owners. Include tables and full Dataview YAML.",
        "stoic":   "Write a Stoic practice journal. Include dichotomy of control analysis, virtue log, Stoic quotes, and a Memento Mori opening.",
        "creative": "Write a creative life journal. Evocative language, metaphors, inspiration catalogue, creative exercises, ideas seeded.",
        "minimal":  "Write a clean, minimal note under 300 words: summary, wins, blockers, tomorrow's top 3. YAML frontmatter only.",
    }

    system_prompt = presets.get(preset_choice, presets["journal"])

    data = {
        "title": title, "date": date, "body": body, "mood": mood,
        "energy": energy, "focus": focus, "wins": wins, "blockers": blockers,
        "tomorrow": tomorrow, "tags": tags, "links": links,
        "system_prompt": system_prompt,
        "features": [
            "Mermaid Mind Map", "Dataview Frontmatter", "Callout Blocks",
            "Tasks Plugin", "Wiki Links", "Graph Tags",
        ],
        "tone": "reflective", "length": "long",
        "config": {
            "ollama": host, "model": model,
            "vault": vault_path, "folder": folder,
            "autoopen": "false",
        }
    }

    print()
    print("  Generating note via Ollama…")
    print("─" * 55)

    cfg = get_cfg(data)
    sp  = build_system_prompt(data)
    um  = build_user_message(data)

    try:
        note = call_ollama(sp, um, cfg["ollama"], cfg["model"],
                           float(cfg["temp"]), int(cfg["tokens"]))
    except RuntimeError as e:
        print(f"\n  ERROR: {e}\n")
        sys.exit(1)

    note = note.strip()
    word_count = len(note.split())
    print(f"\n  ✓ Generated {word_count} words\n")

    # Preview first 20 lines
    preview_lines = note.splitlines()[:20]
    for line in preview_lines:
        print("  " + line)
    if len(note.splitlines()) > 20:
        print(f"  … [{len(note.splitlines()) - 20} more lines]")

    print()
    save = ask("Save to vault? [y/n]", "y")
    if save.lower() == "y":
        vault = Path(os.path.expanduser(vault_path))
        title_slug = slugify(title) if title else "daily"
        filename   = f"{date}-{title_slug}.md"
        note_path  = write_note_to_vault(note, filename, vault, folder)
        print(f"\n  ✓ Saved: {note_path}")

        open_flag = ask("Open in Obsidian? [y/n]", "y")
        if open_flag.lower() == "y":
            open_in_obsidian(vault, note_path)
    else:
        print("  Note not saved.")

    print()


# ─────────────────────────────────────────────────────────
# ENTRYPOINT
# ─────────────────────────────────────────────────────────

def parse_args():
    p = argparse.ArgumentParser(
        description="NoteForge — Obsidian Daily Note Server / CLI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Start the web server (default, serves the HTML frontend)
  python server.py

  # Start on a different port
  python server.py --port 8080

  # Use a specific model and vault
  python server.py --model mistral --vault ~/Documents/ObsidianVault

  # Use the interactive CLI instead of the web server
  python server.py --cli

  # CLI with custom model and vault
  python server.py --cli --model llama3 --vault ~/my-vault
        """
    )
    p.add_argument("--port",   type=int, default=5000,           help="Server port (default: 5000)")
    p.add_argument("--host",   default="127.0.0.1",               help="Server bind address (default: 127.0.0.1)")
    p.add_argument("--ollama", default="http://localhost:11434",  help="Ollama base URL")
    p.add_argument("--model",  default="llama3",                  help="Ollama model name (default: llama3)")
    p.add_argument("--vault",  default=str(Path.home() / "obsidian-vault"), help="Path to Obsidian vault")
    p.add_argument("--folder", default="Daily Notes",             help="Subfolder for daily notes")
    p.add_argument("--debug",  action="store_true",               help="Enable Flask debug mode")
    p.add_argument("--cli",    action="store_true",               help="Run in interactive CLI mode instead of web server")
    return p.parse_args()


if __name__ == "__main__":
    args = parse_args()

    if args.cli:
        # ── Interactive CLI mode ──────────────────────────────
        cli_dashboard(
            vault_path = args.vault,
            model      = args.model,
            host       = args.ollama,
            folder     = args.folder,
        )
    else:
        # ── Web server mode ───────────────────────────────────
        print(CLI_BANNER)
        log.info("Starting NoteForge server on http://%s:%d", args.host, args.port)
        log.info("Ollama: %s | Model: %s", args.ollama, args.model)
        log.info("Vault:  %s / %s", args.vault, args.folder)
        log.info("Open index.html in your browser, or point it to http://%s:%d", args.host, args.port)
        print()

        app.run(
            host  = args.host,
            port  = args.port,
            debug = args.debug,
        )
