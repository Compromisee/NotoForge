#!/usr/bin/env python3
"""
NoteForge — Obsidian AI Workspace Backend
==========================================
Supports:
  - Ollama (local)
  - NVIDIA NIM API  (api.nvidia.com)
  - Any OpenAI-compatible endpoint (OpenAI, Groq, Together, LM Studio…)

Run:
    python server.py                          # default: Ollama on :5000
    python server.py --provider nvidia --nvidia-key nvapi-xxx
    python server.py --provider openai  --openai-key sk-xxx --openai-model gpt-4o
    python server.py --cli                    # interactive terminal mode
    python server.py --port 8080 --vault ~/MyVault

Requires:
    pip install flask flask-cors requests
"""

import os, sys, re, json, logging, argparse, subprocess
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import requests
from flask import Flask, request, jsonify
from flask_cors import CORS

# ── logging ─────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
    handlers=[logging.StreamHandler(sys.stdout),
              logging.FileHandler("noteforge.log", encoding="utf-8")],
)
log = logging.getLogger("noteforge")

app  = Flask(__name__)
CORS(app, resources={r"/*": {"origins": "*"}})

# ── defaults ─────────────────────────────────────────────────────────
DEFAULT = {
    "backend":       "http://localhost:5000",
    "vault":         str(Path.home() / "obsidian-vault"),
    "folder":        "Daily Notes",
    "ideasFolder":   "Ideas",
    "queriesFolder": "Queries",
    "dateformat":    "YYYY-MM-DD",
    "autoopen":      "true",
    "linkerMinLen":  200,
    # AI provider defaults
    "provider":      "ollama",
    "ollama": {
        "host":  "http://localhost:11434",
        "model": "llama3",
        "temp":  0.75,
    },
    "nvidia": {
        "key":    "",
        "model":  "meta/llama-3.1-70b-instruct",
        "temp":   0.7,
        "tokens": 4096,
    },
    "openai": {
        "key":    "",
        "base":   "https://api.openai.com/v1",
        "model":  "gpt-4o",
        "temp":   0.75,
        "tokens": 4096,
    },
}

# ════════════════════════════════════════════════════════════════════
#  HELPERS
# ════════════════════════════════════════════════════════════════════

def merge_cfg(payload: dict) -> dict:
    """Deep-merge the payload config over the defaults."""
    base = json.loads(json.dumps(DEFAULT))
    raw  = payload.get("config") or {}
    # top-level keys
    for k in ["vault","folder","ideasFolder","queriesFolder","dateformat","autoopen","linkerMinLen","provider"]:
        if k in raw:
            base[k] = raw[k]
    # nested providers
    for prov in ["ollama","nvidia","openai"]:
        if prov in raw and isinstance(raw[prov], dict):
            base[prov].update(raw[prov])
    return base


def vault_path(cfg: dict) -> Path:
    return Path(os.path.expandvars(os.path.expanduser(cfg.get("vault", "~/obsidian-vault"))))


def slugify(text: str) -> str:
    text = re.sub(r"[^\w\s-]", "", str(text).lower())
    return re.sub(r"[\s_-]+", "-", text).strip("-")[:80]


def wc(text: str) -> int:
    return len(str(text).split())


def get_streak(vault: Path, folder: str) -> int:
    nd = vault / folder
    if not nd.exists():
        return 0
    streak = 0
    d = datetime.now().date()
    for _ in range(365):
        if any(str(d) in f.name for f in nd.glob("*.md")):
            streak += 1
            d -= timedelta(days=1)
        else:
            break
    return streak


def open_obsidian(vault: Path, note_path: Path) -> None:
    try:
        rel = note_path.relative_to(vault)
        uri = f"obsidian://open?vault={vault.name}&file={str(rel)}"
        if sys.platform == "darwin":
            subprocess.Popen(["open", uri])
        elif sys.platform == "linux":
            subprocess.Popen(["xdg-open", uri])
        elif sys.platform == "win32":
            os.startfile(uri)
    except Exception as ex:
        log.warning("Could not open Obsidian: %s", ex)


def write_note(content: str, filename: str, vault: Path, folder: str) -> Path:
    nd = vault / folder
    nd.mkdir(parents=True, exist_ok=True)
    p = nd / filename
    ctr = 1
    while p.exists():
        p = nd / f"{Path(filename).stem}-{ctr}{Path(filename).suffix}"
        ctr += 1
    p.write_text(content, encoding="utf-8")
    log.info("Written: %s (%d bytes)", p, len(content.encode()))
    return p


# ════════════════════════════════════════════════════════════════════
#  AI PROVIDERS
# ════════════════════════════════════════════════════════════════════

def call_ai(system_prompt: str, user_message: str, cfg: dict) -> str:
    """Route to the correct AI provider and return the generated text."""
    provider = cfg.get("provider", "ollama").lower()

    if provider == "nvidia":
        return call_nvidia(system_prompt, user_message, cfg)
    elif provider == "openai":
        return call_openai_compat(system_prompt, user_message, cfg)
    else:
        return call_ollama(system_prompt, user_message, cfg)


# ── Ollama ───────────────────────────────────────────────────────────

def call_ollama(system_prompt: str, user_message: str, cfg: dict) -> str:
    ol   = cfg.get("ollama", DEFAULT["ollama"])
    host = ol.get("host", "http://localhost:11434").rstrip("/")
    model= ol.get("model", "llama3")
    temp = float(ol.get("temp", 0.75))
    tokens = int(cfg.get("tokens", 4096))

    url = f"{host}/api/chat"
    payload = {
        "model":  model,
        "stream": False,
        "options": {"temperature": temp, "num_predict": tokens, "top_p": 0.92, "repeat_penalty": 1.1},
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user",   "content": user_message},
        ],
    }
    log.info("Ollama %s model=%s", url, model)
    try:
        r = requests.post(url, json=payload, timeout=360)
        r.raise_for_status()
        data = r.json()
        if "message" in data:
            return data["message"]["content"]
        if "response" in data:
            return data["response"]
        raise ValueError(f"Unexpected Ollama shape: {list(data)}")
    except requests.ConnectionError:
        raise RuntimeError(f"Cannot reach Ollama at {host}. Run: ollama serve")
    except requests.Timeout:
        raise RuntimeError("Ollama timed out (360 s). Try a smaller model.")
    except requests.HTTPError as ex:
        raise RuntimeError(f"Ollama HTTP {r.status_code}: {r.text[:300]}") from ex


# ── NVIDIA NIM ───────────────────────────────────────────────────────

def call_nvidia(system_prompt: str, user_message: str, cfg: dict) -> str:
    nv    = cfg.get("nvidia", DEFAULT["nvidia"])
    key   = nv.get("key", "").strip()
    model = nv.get("model", "meta/llama-3.1-70b-instruct")
    temp  = float(nv.get("temp", 0.7))
    tokens= int(nv.get("tokens", 4096))

    if not key:
        raise RuntimeError("NVIDIA API key not configured. Add it in Configuration > AI Provider.")

    url  = "https://integrate.api.nvidia.com/v1/chat/completions"
    hdrs = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    body = {
        "model":       model,
        "max_tokens":  tokens,
        "temperature": temp,
        "top_p":       0.9,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user",   "content": user_message},
        ],
    }
    log.info("NVIDIA NIM model=%s", model)
    try:
        r = requests.post(url, headers=hdrs, json=body, timeout=120)
        r.raise_for_status()
        data = r.json()
        return data["choices"][0]["message"]["content"]
    except requests.HTTPError:
        body_txt = ""
        try: body_txt = r.json().get("detail", r.text[:400])
        except Exception: body_txt = r.text[:400]
        raise RuntimeError(f"NVIDIA API error {r.status_code}: {body_txt}")
    except (KeyError, IndexError):
        raise RuntimeError("Unexpected response shape from NVIDIA API")


# ── OpenAI-compatible ────────────────────────────────────────────────

def call_openai_compat(system_prompt: str, user_message: str, cfg: dict) -> str:
    oa    = cfg.get("openai", DEFAULT["openai"])
    key   = oa.get("key", "").strip()
    base  = oa.get("base", "https://api.openai.com/v1").rstrip("/")
    model = oa.get("model", "gpt-4o")
    temp  = float(oa.get("temp", 0.75))
    tokens= int(oa.get("tokens", 4096))

    if not key:
        raise RuntimeError("API key not configured for OpenAI-compatible provider.")

    url  = f"{base}/chat/completions"
    hdrs = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    body = {
        "model":       model,
        "max_tokens":  tokens,
        "temperature": temp,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user",   "content": user_message},
        ],
    }
    log.info("OpenAI-compat %s model=%s", url, model)
    try:
        r = requests.post(url, headers=hdrs, json=body, timeout=120)
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"]
    except requests.HTTPError:
        raise RuntimeError(f"API error {r.status_code}: {r.text[:400]}")
    except (KeyError, IndexError):
        raise RuntimeError("Unexpected API response shape.")


# ════════════════════════════════════════════════════════════════════
#  PROMPT BUILDERS
# ════════════════════════════════════════════════════════════════════

def build_daily_message(data: dict) -> str:
    length_map = {"medium": "~400-500 words", "long": "~800-1000 words", "epic": "1500+ words"}
    lines = [
        "=== RAW DAILY NOTE DATA ===",
        f"DATE:     {data.get('date', '')}",
        f"TITLE:    {data.get('title', '')}",
        f"MOOD:     {data.get('mood', '')}",
        f"ENERGY:   {data.get('energy', '')}/10",
        f"FOCUS:    {data.get('focus', '')}",
        "",
        "--- MAIN ENTRY ---",
        data.get("body", ""),
        "",
    ]
    if data.get("wins"):
        lines += ["--- WINS ---", data["wins"], ""]
    if data.get("blockers"):
        lines += ["--- BLOCKERS ---", data["blockers"], ""]
    if data.get("tomorrow"):
        lines += ["--- TOMORROW ---", data["tomorrow"], ""]
    if data.get("tags"):
        lines += [f"--- TAGS --- " + ", ".join(f"#{t}" for t in data["tags"]), ""]
    if data.get("links"):
        lines += [f"--- OBSIDIAN LINKS TO WEAVE IN --- {data['links']}", ""]

    lines += [
        "=== GENERATION INSTRUCTIONS ===",
        f"Tone:   {data.get('tone', 'reflective')}",
        f"Length: {length_map.get(data.get('length','long'), '~800 words')}",
    ]
    if data.get("features"):
        lines += ["", "Required Obsidian features:", *[f"  - {f}" for f in data["features"]]]
    if data.get("extra"):
        lines += ["", "Additional instructions:", data["extra"]]
    if data.get("plugin_instructions"):
        lines += ["", "Plugin format requirements:", data["plugin_instructions"]]
    lines += ["", "Output ONLY the complete Markdown note starting with --- YAML frontmatter. No preamble."]
    return "\n".join(lines)


def build_idea_message(data: dict) -> str:
    depth_map = {"brief": "~300 words", "standard": "~600 words", "deep": "1000+ words"}
    lines = [
        f"IDEA TITLE: {data.get('title', 'Untitled')}",
        f"CATEGORY:   {data.get('category', 'idea')}",
        f"DEPTH:      {depth_map.get(data.get('depth','standard'), '~600 words')}",
        "",
        "--- RAW THOUGHT ---",
        data.get("body", ""),
        "",
    ]
    if data.get("context"):
        lines += [f"CONTEXT: {data['context']}", ""]
    if data.get("tags"):
        lines += [f"TAGS: " + ", ".join(f"#{t}" for t in data["tags"]), ""]
    lines += ["", "Output ONLY the complete Markdown note with YAML frontmatter. No preamble."]
    return "\n".join(lines)


def build_query_message(data: dict, context_notes: list) -> str:
    style_map = {
        "summary":    "Write a flowing narrative summary.",
        "bullets":    "Use bullet points and numbered lists.",
        "structured": "Use a structured report with headers and subheaders.",
        "timeline":   "Organize chronologically with dates and timeline markers.",
    }
    context_block = "\n\n---\n\n".join(
        f"FILE: {n['filename']}\n\n{n['content'][:1500]}" for n in context_notes
    )
    return "\n".join([
        "=== VAULT CONTEXT ===",
        context_block,
        "",
        "=== QUERY ===",
        data.get("query", ""),
        "",
        f"Style: {style_map.get(data.get('style','summary'), 'Narrative summary.')}",
        "",
        "Answer thoroughly using ONLY the vault context above. Cite note filenames where relevant.",
        "Output raw Markdown. Do not include YAML frontmatter. Start directly with the answer.",
    ])


def build_link_message(source_content: str, target_summaries: list) -> str:
    summaries = "\n".join(
        f"FILE: {t['filename']}\nSUMMARY: {t['snippet'][:400]}\n"
        for t in target_summaries
    )
    return "\n".join([
        "=== SOURCE NOTE ===",
        source_content[:2000],
        "",
        "=== CANDIDATE NOTES FOR LINKING ===",
        summaries,
        "",
        "Analyze the source note and each candidate. Identify which candidates share meaningful",
        "contextual relationships with the source (shared topics, people, projects, concepts, themes).",
        "",
        "For each strong match, output EXACTLY this JSON format (one per line):",
        '{"target": "FILENAME", "reason": "one sentence why these notes connect", "confidence": "high|medium|low", "context": "quoted phrase from source that connects"}',
        "",
        "Output ONLY the JSON lines. No preamble, no explanation, no markdown.",
    ])


def build_tag_message(content: str, existing_tags: list, count: int, style: str) -> str:
    style_desc = {
        "mixed":         "Generate a mix of hierarchical (parent/child like #work/project-alpha) and flat (#productivity) tags.",
        "flat":          "Generate only flat single-word or short-phrase tags (no slashes).",
        "hierarchical":  "Generate hierarchical tags with parent/child structure using slashes.",
    }
    existing_str = ", ".join(f"#{t}" for t in existing_tags) if existing_tags else "none"
    return "\n".join([
        "=== NOTE CONTENT ===",
        content[:3000],
        "",
        f"Existing tags (do NOT duplicate): {existing_str}",
        f"Target count: {count} tags",
        f"Style: {style_desc.get(style, style_desc['mixed'])}",
        "",
        "Analyze the note content deeply. Generate tags that are:",
        "  - Topically accurate and specific",
        "  - Useful for Obsidian graph clustering",
        "  - Compatible with Dataview queries",
        "  - Covering: topics, people, projects, emotions, domains, time periods, methodologies",
        "",
        "Output EXACTLY this JSON:",
        '{"tags": [{"tag": "tag-name", "reason": "why this tag"}, ...], "reasoning": "brief overall explanation"}',
        "",
        "No markdown fences, no preamble. Raw JSON only.",
    ])


# ════════════════════════════════════════════════════════════════════
#  VAULT UTILITIES
# ════════════════════════════════════════════════════════════════════

def scan_vault(vault: Path, max_files: int = 100, min_len: int = 100) -> list:
    """Return a list of {filename, path, content, snippet} dicts."""
    notes = []
    for f in sorted(vault.rglob("*.md"), key=lambda x: x.stat().st_mtime, reverse=True):
        if len(notes) >= max_files:
            break
        try:
            content = f.read_text(encoding="utf-8")
            if len(content) < min_len:
                continue
            notes.append({
                "filename": str(f.relative_to(vault)),
                "path":     str(f),
                "content":  content,
                "snippet":  content[:600],
            })
        except Exception:
            pass
    return notes


def scan_folder(vault: Path, folder: str, max_files: int = 50) -> list:
    nd = vault / folder
    if not nd.exists():
        return []
    notes = []
    for f in sorted(nd.glob("*.md"), key=lambda x: x.stat().st_mtime, reverse=True)[:max_files]:
        try:
            content = f.read_text(encoding="utf-8")
            notes.append({"filename": str(f.relative_to(vault)), "path": str(f), "content": content, "snippet": content[:600]})
        except Exception:
            pass
    return notes


def extract_tasks_from_vault(vault: Path, max_files: int = 200) -> list:
    """Parse Obsidian Tasks plugin format from all vault notes."""
    TASK_RE = re.compile(
        r"- \[([ xX])\] (.+?)(?:\s+📅\s*(\d{4}-\d{2}-\d{2}))?(?:\s+⏫|\s+🔺|\s+🔼|\s+🔽)?",
        re.MULTILINE
    )
    PRIORITY_MAP = {"🔺": "high", "⏫": "high", "🔼": "medium", "🔽": "low"}
    tasks = []
    for note in scan_vault(vault, max_files=max_files, min_len=10):
        for m in TASK_RE.finditer(note["content"]):
            done     = m.group(1).lower() == "x"
            text     = m.group(2).strip()
            due      = m.group(3) or ""
            priority = "medium"
            for emoji, p in PRIORITY_MAP.items():
                if emoji in text:
                    priority = p
                    text = text.replace(emoji, "").strip()
                    break
            tasks.append({
                "text":     text,
                "done":     done,
                "due":      due,
                "priority": priority,
                "source":   note["filename"],
            })
    return tasks


def get_calendar_days(vault: Path, folder: str, year: int, month: int) -> dict:
    """Return a dict of {YYYY-MM-DD: {note: bool, task: bool}} for the given month."""
    days = {}
    nd   = vault / folder
    if not nd.exists():
        return days
    import calendar as cal_mod
    _, num_days = cal_mod.monthrange(year, month)
    for d in range(1, num_days + 1):
        date_str = f"{year}-{str(month).zfill(2)}-{str(d).zfill(2)}"
        has_note = any(date_str in f.name for f in nd.glob("*.md"))
        days[date_str] = {"note": has_note, "task": False}
    # mark days with tasks
    for task in extract_tasks_from_vault(vault, max_files=100):
        if task["due"] and task["due"][:7] == f"{year}-{str(month).zfill(2)}":
            if task["due"] in days:
                days[task["due"]]["task"] = True
    return days


def insert_wikilinks(content: str, links: list) -> str:
    """Insert [[wikilink]] references into note content at the end."""
    if not links:
        return content
    link_section = "\n\n## Related Notes\n\n" + "\n".join(f"- [[{lnk}]]" for lnk in links)
    # Insert before last heading or append
    if "## " in content:
        parts = content.rsplit("## ", 1)
        return parts[0] + link_section + "\n\n## " + parts[1]
    return content + link_section


def apply_tags_to_file(file_path: Path, new_tags: list) -> bool:
    """Add tags to the YAML frontmatter of an existing note."""
    content = file_path.read_text(encoding="utf-8")
    if content.startswith("---"):
        # find end of frontmatter
        end = content.find("---", 3)
        if end > 0:
            fm  = content[3:end]
            rest = content[end+3:]
            # check if tags already exists
            if "tags:" in fm:
                # append to existing list
                existing_match = re.search(r"tags:\s*\[([^\]]*)\]", fm)
                if existing_match:
                    old = [t.strip().strip('"').strip("'").lstrip("#") for t in existing_match.group(1).split(",") if t.strip()]
                    merged = list(dict.fromkeys(old + new_tags))
                    fm = fm[:existing_match.start()] + f"tags: [{', '.join(merged)}]" + fm[existing_match.end():]
                else:
                    # multiline tags
                    fm = re.sub(r"(tags:.*?\n)((?:  - .*\n)*)",
                               lambda m: m.group(1) + m.group(2) + "".join(f"  - {t}\n" for t in new_tags),
                               fm, flags=re.DOTALL)
            else:
                fm += f"\ntags: [{', '.join(new_tags)}]"
            file_path.write_text("---" + fm + "---" + rest, encoding="utf-8")
            return True
    # No frontmatter — prepend
    fm_block = f"---\ntags: [{', '.join(new_tags)}]\n---\n\n"
    file_path.write_text(fm_block + content, encoding="utf-8")
    return True


# ════════════════════════════════════════════════════════════════════
#  ROUTES
# ════════════════════════════════════════════════════════════════════

@app.route("/health", methods=["GET"])
def health():
    cfg      = merge_cfg({})
    provider = cfg.get("provider", "ollama")
    ai_ok    = False
    ai_status= "not tested"
    model    = "unknown"

    try:
        if provider == "ollama":
            ol   = cfg["ollama"]
            r    = requests.get(f"{ol['host']}/api/tags", timeout=4)
            ai_ok= r.ok
            if r.ok:
                models = [m["name"] for m in r.json().get("models", [])]
                ai_status = f"ok — {len(models)} model(s)"
                model = ol["model"]
        elif provider == "nvidia":
            ai_status = "key present" if cfg["nvidia"].get("key") else "no key"
            ai_ok     = bool(cfg["nvidia"].get("key"))
            model     = cfg["nvidia"]["model"]
        elif provider == "openai":
            ai_status = "key present" if cfg["openai"].get("key") else "no key"
            ai_ok     = bool(cfg["openai"].get("key"))
            model     = cfg["openai"]["model"]
    except Exception as ex:
        ai_status = str(ex)

    return jsonify({"status": "ok", "provider": provider, "ai_ok": ai_ok,
                    "ai_status": ai_status, "model": model, "server": "NoteForge v2.0"})


@app.route("/generate", methods=["POST"])
def generate():
    data = request.get_json(force=True) or {}
    cfg  = merge_cfg(data)
    kind = data.get("type", "daily")

    log.info("generate type=%s provider=%s", kind, cfg.get("provider"))

    # Build date string and filename
    date_str = data.get("date") or datetime.now().strftime("%Y-%m-%d")
    title    = (data.get("title") or "").strip()
    slug     = slugify(title) if title else kind
    filename = f"{date_str}-{slug}.md"

    # Build system + user message
    sys_prompt = (data.get("system_prompt") or "").strip()
    if not sys_prompt:
        sys_prompt = _default_sys_prompt(kind)

    if kind == "daily":
        user_msg = build_daily_message(data)
    elif kind == "idea":
        user_msg = build_idea_message(data)
    else:
        user_msg = data.get("body") or data.get("query") or ""

    try:
        note = call_ai(sys_prompt, user_msg, cfg)
    except RuntimeError as ex:
        log.error("AI error: %s", ex)
        return jsonify({"error": str(ex)}), 502

    note = _clean_md(note)
    log.info("Generated %d words", wc(note))
    return jsonify({"note": note, "filename": filename, "words": wc(note), "date": date_str, "title": title})


@app.route("/send", methods=["POST"])
def send():
    data     = request.get_json(force=True) or {}
    cfg      = merge_cfg(data)
    content  = data.get("note") or data.get("content") or ""
    filename = data.get("filename") or "note.md"
    folder_override = data.get("folder_override") or cfg.get("folder", "Daily Notes")

    if not content:
        return jsonify({"error": "No note content"}), 400

    vault = vault_path(cfg)
    try:
        p = write_note(content, filename, vault, folder_override)
    except PermissionError as ex:
        return jsonify({"error": f"Permission denied: {ex}"}), 500
    except Exception as ex:
        return jsonify({"error": str(ex)}), 500

    if cfg.get("autoopen") == "true":
        open_obsidian(vault, p)

    streak = get_streak(vault, cfg.get("folder", "Daily Notes"))
    return jsonify({"status": "ok", "path": str(p), "filename": p.name,
                    "vault": str(vault), "streak": streak})


@app.route("/query", methods=["POST"])
def query():
    data  = request.get_json(force=True) or {}
    cfg   = merge_cfg(data)
    vault = vault_path(cfg)

    q         = data.get("query", "").strip()
    scope     = data.get("scope", "vault")
    folder    = data.get("folder") or cfg.get("folder", "Daily Notes")
    max_notes = int(data.get("maxnotes") or 25)
    style     = data.get("style", "summary")

    if not q:
        return jsonify({"error": "No query provided"}), 400

    log.info("Vault query: %s (scope=%s max=%d)", q[:60], scope, max_notes)

    # Load notes
    if scope == "daily":
        notes = scan_folder(vault, cfg.get("folder", "Daily Notes"), max_notes)
    elif scope == "folder" and folder:
        notes = scan_folder(vault, folder, max_notes)
    else:
        notes = scan_vault(vault, max_notes)

    if not notes:
        return jsonify({"answer": f"No notes found in vault at {vault}. Check your vault path in Configuration.",
                        "sources": [], "notes_scanned": 0}), 200

    # Relevance filter: simple keyword match to pick best context
    kw = re.findall(r"\b\w{4,}\b", q.lower())
    def relevance(n):
        c = n["content"].lower()
        return sum(1 for k in kw if k in c)
    notes_sorted = sorted(notes, key=relevance, reverse=True)[:15]
    sources = [n["filename"] for n in notes_sorted]

    sys_prompt = (
        "You are a smart knowledge assistant with access to a user's Obsidian vault notes. "
        "Answer the query accurately and thoroughly using ONLY the provided vault context. "
        "Cite note filenames when referencing specific information. "
        "Output well-formatted Markdown."
    )

    user_msg = build_query_message(data, notes_sorted)

    try:
        answer = call_ai(sys_prompt, user_msg, cfg)
    except RuntimeError as ex:
        return jsonify({"error": str(ex)}), 502

    return jsonify({"answer": _clean_md(answer), "sources": sources,
                    "notes_scanned": len(notes), "query": q})


@app.route("/link_suggest", methods=["POST"])
def link_suggest():
    data  = request.get_json(force=True) or {}
    cfg   = merge_cfg(data)
    vault = vault_path(cfg)

    source_file = data.get("source", "").strip()
    threshold   = data.get("threshold", "medium")
    max_notes   = data.get("maxnotes", "50")
    max_n       = 200 if max_notes == "all" else int(max_notes)
    min_len     = int(cfg.get("linkerMinLen", 200))

    log.info("Auto linker source=%s threshold=%s max=%s", source_file or "all", threshold, max_notes)

    all_notes = scan_vault(vault, max_notes=max_n, min_len=min_len)
    vault_size = len(list(vault.rglob("*.md")))

    if not all_notes:
        return jsonify({"suggestions": [], "notes_scanned": 0, "vault_size": vault_size, "existing_links": 0})

    # Count existing wikilinks in vault
    existing_links = sum(len(re.findall(r"\[\[.+?\]\]", n["content"])) for n in all_notes)

    confidence_floor = {"high": "high", "medium": "medium", "low": "low"}[threshold]

    suggestions = []
    sources_to_process = [n for n in all_notes if source_file in n["filename"]] if source_file else all_notes[:20]

    BATCH = 8  # notes per AI call to avoid context overflow
    for source in sources_to_process[:10]:
        candidates = [n for n in all_notes if n["filename"] != source["filename"]]
        # process in batches
        for i in range(0, min(len(candidates), 40), BATCH):
            batch = candidates[i:i+BATCH]
            sys_p = (
                "You are a knowledge graph AI. Analyze note relationships and return JSON link suggestions. "
                "Only suggest meaningful, contextually relevant links — not superficial keyword matches."
            )
            user_msg = build_link_message(source["content"], batch)
            try:
                raw = call_ai(sys_p, user_msg, cfg)
                for line in raw.strip().splitlines():
                    line = line.strip()
                    if not line.startswith("{"):
                        continue
                    try:
                        obj = json.loads(line)
                        conf = obj.get("confidence", "medium")
                        # apply threshold filter
                        conf_rank = {"high":3,"medium":2,"low":1}
                        if conf_rank.get(conf,1) >= conf_rank.get(confidence_floor,2):
                            suggestions.append({
                                "source_file": source["filename"],
                                "target_file": obj.get("target",""),
                                "reason":      obj.get("reason",""),
                                "confidence":  conf,
                                "context":     obj.get("context",""),
                            })
                    except json.JSONDecodeError:
                        pass
            except RuntimeError as ex:
                log.warning("Link batch failed: %s", ex)
                break

    return jsonify({
        "suggestions":    suggestions,
        "notes_scanned":  len(all_notes),
        "existing_links": existing_links,
        "vault_size":     vault_size,
    })


@app.route("/link_apply", methods=["POST"])
def link_apply():
    data    = request.get_json(force=True) or {}
    cfg     = merge_cfg(data)
    vault   = vault_path(cfg)
    accepted= data.get("suggestions", [])

    applied = 0
    errors  = []

    for sugg in accepted:
        source_file = sugg.get("source_file", "")
        target_file = sugg.get("target_file", "")
        if not source_file or not target_file:
            continue

        note_path = vault / source_file
        target_name = Path(target_file).stem  # note name without .md

        if not note_path.exists():
            errors.append(f"Not found: {source_file}")
            continue

        try:
            content = note_path.read_text(encoding="utf-8")
            # Check if link already present
            if f"[[{target_name}]]" in content or f"[[{target_file}]]" in content:
                continue
            # Append to Related Notes section or create it
            updated = _insert_related_link(content, target_name)
            note_path.write_text(updated, encoding="utf-8")
            applied += 1
            log.info("Linked %s -> [[%s]]", source_file, target_name)
        except Exception as ex:
            errors.append(f"Error writing {source_file}: {ex}")

    return jsonify({"applied": applied, "errors": errors})


def _insert_related_link(content: str, link_name: str) -> str:
    """Add [[link_name]] to the Related Notes section, creating it if needed."""
    related_heading = "## Related Notes"
    new_link = f"- [[{link_name}]]"
    if related_heading in content:
        idx = content.index(related_heading) + len(related_heading)
        return content[:idx] + "\n\n" + new_link + content[idx:]
    else:
        return content.rstrip() + f"\n\n{related_heading}\n\n{new_link}\n"


@app.route("/generate_tags", methods=["POST"])
def generate_tags():
    data  = request.get_json(force=True) or {}
    cfg   = merge_cfg(data)
    vault = vault_path(cfg)

    mode     = data.get("mode", "paste")
    content  = data.get("content", "").strip()
    file     = data.get("file", "").strip()
    style    = data.get("style", "mixed")
    count    = int(data.get("count", 10))
    existing_raw = data.get("existing", "")
    existing = [t.strip().lstrip("#") for t in existing_raw.split(",") if t.strip()]

    # Load content if file mode
    if mode == "file" and file:
        p = vault / file
        if not p.exists():
            return jsonify({"error": f"File not found: {file}"}), 404
        content = p.read_text(encoding="utf-8")

    if not content:
        return jsonify({"error": "No content to analyze"}), 400

    log.info("Tag generation mode=%s count=%d style=%s", mode, count, style)

    sys_p = (
        "You are an expert Obsidian knowledge graph curator. "
        "Analyze note content and generate optimal tags for knowledge management. "
        "Return ONLY valid JSON — no markdown, no explanation."
    )
    user_msg = build_tag_message(content, existing, count, style)

    try:
        raw = call_ai(sys_p, user_msg, cfg)
    except RuntimeError as ex:
        return jsonify({"error": str(ex)}), 502

    # Parse JSON
    raw = raw.strip()
    raw = re.sub(r"^```[^\n]*\n?", "", raw)
    raw = re.sub(r"\n?```$", "", raw)
    try:
        parsed = json.loads(raw)
        tags      = parsed.get("tags", [])
        reasoning = parsed.get("reasoning", "")
    except json.JSONDecodeError:
        # Fallback: extract tags from text
        tags = [{"tag": t.lstrip("#"), "reason": ""} for t in re.findall(r"#[\w/-]+", raw)]
        reasoning = "JSON parse error — extracted tags from raw text."

    return jsonify({"tags": tags, "reasoning": reasoning, "mode": mode})


@app.route("/apply_tags", methods=["POST"])
def apply_tags():
    data   = request.get_json(force=True) or {}
    cfg    = merge_cfg(data)
    vault  = vault_path(cfg)
    tags   = data.get("tags", [])
    file   = data.get("file", "").strip()

    if not tags:
        return jsonify({"error": "No tags to apply"}), 400
    if not file:
        return jsonify({"status": "ok", "message": "Tags returned but no file specified", "tags": tags})

    p = vault / file
    if not p.exists():
        return jsonify({"error": f"File not found: {file}"}), 404

    try:
        apply_tags_to_file(p, tags)
        log.info("Applied %d tags to %s", len(tags), file)
        return jsonify({"status": "ok", "applied": len(tags), "file": file})
    except Exception as ex:
        return jsonify({"error": str(ex)}), 500


@app.route("/tasks", methods=["GET"])
def get_tasks():
    cfg   = merge_cfg(request.args.to_dict())
    vault = vault_path(cfg)
    tasks = extract_tasks_from_vault(vault, max_files=200)
    log.info("Tasks scanned: %d", len(tasks))
    return jsonify({"tasks": tasks, "count": len(tasks)})


@app.route("/calendar_data", methods=["GET"])
def calendar_data():
    cfg   = merge_cfg(request.args.to_dict())
    vault = vault_path(cfg)
    year  = int(request.args.get("year",  datetime.now().year))
    month = int(request.args.get("month", datetime.now().month))
    days  = get_calendar_days(vault, cfg.get("folder","Daily Notes"), year, month)
    return jsonify({"days": days, "year": year, "month": month})


@app.route("/history", methods=["GET"])
def get_history():
    cfg    = merge_cfg(request.args.to_dict())
    vault  = vault_path(cfg)
    folder = cfg.get("folder", "Daily Notes")
    nd     = vault / folder
    if not nd.exists():
        return jsonify({"notes": [], "folder": str(nd)})
    notes = []
    for f in sorted(nd.glob("*.md"), reverse=True)[:50]:
        s = f.stat()
        notes.append({"filename": f.name, "path": str(f), "size": s.st_size,
                       "modified": datetime.fromtimestamp(s.st_mtime).isoformat()})
    return jsonify({"notes": notes, "folder": str(nd), "count": len(notes)})


@app.route("/vault/stats", methods=["GET"])
def vault_stats():
    cfg    = merge_cfg(request.args.to_dict())
    vault  = vault_path(cfg)
    folder = cfg.get("folder","Daily Notes")
    if not vault.exists():
        return jsonify({"exists": False})
    all_md    = list(vault.rglob("*.md"))
    nd        = vault / folder
    daily_md  = list(nd.glob("*.md")) if nd.exists() else []
    total_wds = sum(len(f.read_text(encoding="utf-8","ignore").split()) for f in daily_md[:50])
    return jsonify({"exists": True, "vault": str(vault), "total_notes": len(all_md),
                    "daily_notes": len(daily_md), "total_words": total_wds,
                    "streak": get_streak(vault, folder)})


@app.route("/note/<path:filename>", methods=["GET"])
def get_note(filename):
    cfg  = merge_cfg(request.args.to_dict())
    v    = vault_path(cfg)
    p    = v / cfg.get("folder","Daily Notes") / filename
    if not p.exists():
        return jsonify({"error": "Not found"}), 404
    c = p.read_text(encoding="utf-8")
    return jsonify({"filename": filename, "content": c, "words": wc(c)})


@app.route("/models", methods=["GET"])
def list_models():
    cfg = merge_cfg({})
    ol  = cfg["ollama"]
    try:
        r = requests.get(f"{ol['host']}/api/tags", timeout=5)
        r.raise_for_status()
        return jsonify({"models": [m["name"] for m in r.json().get("models",[])]})
    except Exception as ex:
        return jsonify({"error": str(ex)}), 502


# ════════════════════════════════════════════════════════════════════
#  INTERNAL HELPERS
# ════════════════════════════════════════════════════════════════════

def _clean_md(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    return text


def _default_sys_prompt(kind: str) -> str:
    if kind == "daily":
        return (
            "You are a meticulous Obsidian daily note assistant. Write deeply reflective, "
            "detailed Markdown notes with YAML frontmatter, Mermaid mindmaps, wikilinks, "
            "callout blocks, and Tasks plugin-compatible task lists. "
            "Output raw Markdown only starting with --- YAML frontmatter."
        )
    elif kind == "idea":
        return (
            "You are a Zettelkasten note architect. Expand rough ideas into comprehensive "
            "Markdown notes with YAML frontmatter, wikilinks, callout blocks [!insight], "
            "Mermaid mindmap, and next-step recommendations. "
            "Output raw Markdown only."
        )
    return "You are a helpful Obsidian knowledge management assistant. Output raw Markdown."


# ════════════════════════════════════════════════════════════════════
#  CLI MODE
# ════════════════════════════════════════════════════════════════════

BANNER = r"""
  _   _       _       _____                    
 | \ | |     | |     |  ___|__  _ __ __ _  ___ 
 |  \| | ___ | |_ ___| |_ / _ \| '__/ _` |/ _ \
 | |\  |/ _ \| __/ _ \  _| (_) | | | (_| |  __/
 |_| \_|\___/ \__\___/_|  \___/|_|  \__, |\___|
                                     |___/      
  Obsidian AI Workspace  v2.0
"""

def cli_mode(args):
    print(BANNER)

    def ask(prompt, default=""):
        v = input(f"  {prompt}" + (f" [{default}]" if default else "") + ": ").strip()
        return v or default

    def askml(prompt):
        print(f"  {prompt} (blank line to finish):")
        lines = []
        while True:
            line = input("    > ")
            if not line:
                break
            lines.append(line)
        return "\n".join(lines)

    print("─" * 55)
    print("  Mode: 1=Daily Note  2=Idea  3=Query")
    mode_ch = ask("Mode", "1")
    kind = {"1":"daily","2":"idea","3":"query"}.get(mode_ch,"daily")

    cfg = {
        "provider": args.provider,
        "vault":    args.vault,
        "folder":   args.folder,
        "autoopen": "false",
        "ollama": {"host": args.ollama, "model": args.model, "temp": 0.75},
        "nvidia": {"key": args.nvidia_key or "", "model": args.nvidia_model or "meta/llama-3.1-70b-instruct", "temp": 0.7, "tokens": 4096},
        "openai": {"key": args.openai_key or "", "base": args.openai_base or "https://api.openai.com/v1",
                   "model": args.openai_model or "gpt-4o", "temp": 0.75, "tokens": 4096},
    }

    today = datetime.now().strftime("%Y-%m-%d")

    if kind == "daily":
        date  = ask("Date", today)
        title = ask("Title / headline")
        mood  = ask("Mood", "Neutral")
        energy= ask("Energy (1-10)", "7")
        focus = ask("Focus area", "general")
        body  = askml("What happened today?")
        wins  = askml("Wins / accomplishments")
        blockers = askml("Blockers / challenges")
        tomorrow = askml("Tomorrow's intentions")
        tags_raw = ask("Tags (comma-separated)")
        tags  = [t.strip() for t in tags_raw.split(",") if t.strip()]
        data  = {"type":"daily","date":date,"title":title,"mood":mood,"energy":energy,
                 "focus":focus,"body":body,"wins":wins,"blockers":blockers,"tomorrow":tomorrow,
                 "tags":tags,"tone":"reflective","length":"long","features":
                 ["Mermaid Mind Map","Dataview Frontmatter","Callout Blocks","Tasks Plugin Format","Wiki Links","Graph Tags"]}
        sp    = _default_sys_prompt("daily")
        msg   = build_daily_message(data)

    elif kind == "idea":
        title = ask("Idea title")
        body  = askml("Your raw thought or idea")
        data  = {"type":"idea","title":title,"body":body,"depth":"standard"}
        sp    = _default_sys_prompt("idea")
        msg   = build_idea_message(data)

    else:
        q = ask("Your query")
        vault_p = vault_path(cfg)
        notes   = scan_vault(vault_p, max_files=25)
        data    = {"query":q,"style":"summary"}
        sp      = "You are a helpful knowledge assistant. Answer using the provided vault context."
        msg     = build_query_message(data, notes[:10])

    print("\n  Generating with provider:", cfg["provider"], "...")
    print("─" * 55)

    # merge config correctly
    merged = merge_cfg({"config": cfg})
    try:
        result = call_ai(sp, msg, merged)
    except RuntimeError as ex:
        print(f"\n  ERROR: {ex}\n")
        sys.exit(1)

    result = _clean_md(result)
    print(f"\n  Generated {wc(result)} words\n")
    for line in result.splitlines()[:20]:
        print("  " + line)
    if result.count("\n") > 20:
        print(f"  ... [{result.count(chr(10))-20} more lines]")

    save = ask("\n  Save to vault? [y/n]", "y")
    if save.lower() == "y":
        vault_p = vault_path(cfg)
        slug    = slugify(data.get("title") or kind)
        date    = data.get("date") or today
        fname   = f"{date}-{slug}.md"
        folder  = cfg["folder"] if kind=="daily" else ("Ideas" if kind=="idea" else "Queries")
        p = write_note(result, fname, vault_p, folder)
        print(f"\n  Saved: {p}")
        if ask("  Open in Obsidian? [y/n]","y").lower()=="y":
            open_obsidian(vault_p, p)
    print()


# ════════════════════════════════════════════════════════════════════
#  ENTRY POINT
# ════════════════════════════════════════════════════════════════════

def parse_args():
    p = argparse.ArgumentParser(
        description="NoteForge v2.0 — Obsidian AI Workspace",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python server.py                                          # Ollama on :5000
  python server.py --provider nvidia --nvidia-key nvapi-x  # NVIDIA NIM
  python server.py --provider openai --openai-key sk-x     # OpenAI
  python server.py --port 8080 --vault ~/Docs/MyVault
  python server.py --cli                                    # terminal UI
  python server.py --cli --provider nvidia --nvidia-key nvapi-x
        """,
    )
    p.add_argument("--port",         type=int,   default=5000)
    p.add_argument("--host",         default="127.0.0.1")
    p.add_argument("--vault",        default=str(Path.home()/"obsidian-vault"))
    p.add_argument("--folder",       default="Daily Notes")
    p.add_argument("--debug",        action="store_true")
    p.add_argument("--cli",          action="store_true", help="Interactive CLI mode")

    # AI providers
    p.add_argument("--provider",     default="ollama",    choices=["ollama","nvidia","openai"])
    p.add_argument("--ollama",       default="http://localhost:11434")
    p.add_argument("--model",        default="llama3")
    p.add_argument("--nvidia-key",   default="")
    p.add_argument("--nvidia-model", default="meta/llama-3.1-70b-instruct")
    p.add_argument("--openai-key",   default="")
    p.add_argument("--openai-base",  default="https://api.openai.com/v1")
    p.add_argument("--openai-model", default="gpt-4o")

    return p.parse_args()


if __name__ == "__main__":
    args = parse_args()

    if args.cli:
        cli_mode(args)
    else:
        print(BANNER)
        log.info("NoteForge v2.0 starting on http://%s:%d", args.host, args.port)
        log.info("Provider: %s | Vault: %s", args.provider, args.vault)
        if args.provider == "ollama":
            log.info("Ollama: %s | Model: %s", args.ollama, args.model)
        elif args.provider == "nvidia":
            log.info("NVIDIA model: %s | Key: %s", args.nvidia_model, "SET" if args.nvidia_key else "NOT SET")
        elif args.provider == "openai":
            log.info("OpenAI base: %s | Model: %s", args.openai_base, args.openai_model)
        log.info("Open index.html in your browser")
        print()
        app.run(host=args.host, port=args.port, debug=args.debug)
