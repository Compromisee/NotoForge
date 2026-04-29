# NoteForge v2.0 — Obsidian AI Workspace

A self-hosted Obsidian AI workspace: HTML dashboard + Python backend. Generates rich daily notes, elaborates ideas, answers vault queries, auto-links notes by context, auto-generates tags, integrates with Obsidian Tasks and Calendar plugins, and supports **Ollama (local)**, **NVIDIA NIM**, and any **OpenAI-compatible** endpoint.

---

## Table of Contents

1. [Feature Overview](#1-feature-overview)
2. [Architecture](#2-architecture)
3. [Requirements](#3-requirements)
4. [Quick Start](#4-quick-start)
5. [AI Provider Setup](#5-ai-provider-setup)
6. [Dashboard Tabs Reference](#6-dashboard-tabs-reference)
7. [Vault Intelligence: Auto Linker](#7-vault-intelligence-auto-linker)
8. [Vault Intelligence: Tag Generator](#8-vault-intelligence-tag-generator)
9. [Obsidian Plugin Integrations](#9-obsidian-plugin-integrations)
10. [Calendar and Tasks](#10-calendar-and-tasks)
11. [CLI Mode](#11-cli-mode)
12. [Backend API Reference](#12-backend-api-reference)
13. [Configuration Reference](#13-configuration-reference)
14. [Prompt Presets](#14-prompt-presets)
15. [Obsidian Feature Injections](#15-obsidian-feature-injections)
16. [Packaging to Executable (.exe / binary)](#16-packaging-to-executable)
17. [Obsidian Setup and Recommended Plugins](#17-obsidian-setup-and-recommended-plugins)
18. [Troubleshooting](#18-troubleshooting)

---

## 1. Feature Overview

| Feature | Description |
|---------|-------------|
| **Daily Note Generator** | Expands raw notes into rich, structured Obsidian Markdown |
| **Ideas and Thoughts** | Drop a rough idea, AI elaborates with mindmaps and connections |
| **Vault Query** | Ask natural language questions about your vault contents |
| **Auto Linker** | AI scans all notes, suggests and inserts contextual [[wikilinks]] |
| **Tag Generator** | AI analyzes content and generates optimal Obsidian tags |
| **Plugin Support** | Tasks, Calendar, Dataview, Periodic Notes, Templater, Kanban |
| **Calendar View** | Visual calendar with note and task indicators |
| **Task Scanner** | Parses Tasks plugin format across entire vault |
| **NVIDIA NIM** | Cloud AI via NVIDIA's NIM API (free tier available) |
| **Ollama** | 100% local AI, no data leaves your machine |
| **OpenAI-compatible** | OpenAI, Groq, Together AI, LM Studio, any v1/chat endpoint |
| **CLI Mode** | Full terminal workflow, no browser needed |
| **Packaging to EXE** | Bundle into a single executable via PyInstaller |

---

## 2. Architecture

```
Browser  (index.html — static file, no server needed)
    |
    |  HTTP JSON   localhost:5000
    v
Flask Backend  (server.py)
    |
    |── Ollama API      localhost:11434/api/chat
    |── NVIDIA NIM      integrate.api.nvidia.com/v1/chat/completions
    |── OpenAI-compat   any-base-url/chat/completions
    |
    v
Obsidian Vault  (local filesystem)
    |
    v
obsidian:// URI  -->  Obsidian desktop app
```

All vault operations are local filesystem reads and writes. API keys never leave your machine (they are only sent to the respective AI provider endpoint).

---

## 3. Requirements

### Python

```
Python 3.9+
pip install flask flask-cors requests
```

### AI (choose one or more)

| Provider | Setup |
|----------|-------|
| **Ollama** | Install from ollama.com, run `ollama serve`, pull a model |
| **NVIDIA NIM** | Get free API key at build.nvidia.com |
| **OpenAI** | Standard OpenAI API key |
| **Groq** | Key from console.groq.com, base URL `https://api.groq.com/openai/v1` |
| **LM Studio** | Run LM Studio local server, base URL `http://localhost:1234/v1` |

### Obsidian (optional)

Required only if you want auto-open and URI integration. The backend writes plain `.md` files — any editor works.

---

## 4. Quick Start

### Step 1 — Install Python dependencies

```bash
pip install flask flask-cors requests
```

### Step 2 — Start the backend

**With Ollama (default):**
```bash
ollama serve          # in one terminal
ollama pull llama3    # pull a model once
python server.py      # in another terminal
```

**With NVIDIA NIM:**
```bash
python server.py --provider nvidia --nvidia-key nvapi-YOUR_KEY_HERE
```

**With OpenAI:**
```bash
python server.py --provider openai --openai-key sk-YOUR_KEY_HERE
```

You should see:
```
  NoteForge v2.0 starting on http://127.0.0.1:5000
  Provider: ollama | Vault: /home/you/obsidian-vault
```

### Step 3 — Open the dashboard

Double-click `index.html` or open it in your browser:
```
file:///path/to/index.html
```

### Step 4 — Configure vault path

Click **Configuration** in the sidebar. Set your vault path to the absolute path of your Obsidian vault folder. Click **Save All Config**.

### Step 5 — Generate your first note

Go to **Daily Note**, fill in your entry, click **Generate and Send**.

---

## 5. AI Provider Setup

### Ollama (Local — Recommended for Privacy)

```bash
# Install: https://ollama.com
ollama serve
ollama pull llama3          # 8B — good balance
ollama pull llama3:70b      # 70B — best quality, needs 48GB RAM
ollama pull mistral         # fast, 7B
ollama pull gemma2          # good structured output
ollama pull qwen2.5:14b     # excellent for long-form writing
```

In the dashboard: **Configuration > AI Provider > Ollama**. Set the host and model name.

Ping test:
```bash
curl http://localhost:11434/api/tags
```

### NVIDIA NIM (Cloud — Free Tier Available)

1. Go to [build.nvidia.com](https://build.nvidia.com)
2. Create a free account
3. Navigate to any model page and click "Get API Key"
4. Your key starts with `nvapi-`

Available models (configured in the dropdown):

| Model | Notes |
|-------|-------|
| `meta/llama-3.1-70b-instruct` | Best general quality |
| `meta/llama-3.1-8b-instruct` | Fast, lower cost |
| `meta/llama-3.3-70b-instruct` | Latest Llama 3.3 |
| `nvidia/llama-3.1-nemotron-70b-instruct` | NVIDIA-tuned, excellent |
| `mistralai/mistral-large-2-instruct` | Mistral flagship |
| `google/gemma-2-27b-it` | Google Gemma 2 |
| `microsoft/phi-3-medium-128k-instruct` | Long context |

In the dashboard: **Configuration > AI Provider > NVIDIA AI**. Paste your key and select a model.

Command line:
```bash
python server.py --provider nvidia --nvidia-key nvapi-xxxxxxxxxx --nvidia-model meta/llama-3.1-70b-instruct
```

### OpenAI and Compatible Endpoints

**OpenAI:**
```bash
python server.py --provider openai --openai-key sk-xxx --openai-model gpt-4o
```

**Groq (free, very fast):**
- Get key: console.groq.com
- Base URL: `https://api.groq.com/openai/v1`
- Models: `llama-3.1-70b-versatile`, `mixtral-8x7b-32768`

**Together AI:**
- Base URL: `https://api.together.xyz/v1`

**LM Studio (local):**
- Start local server in LM Studio
- Base URL: `http://localhost:1234/v1`
- API key: anything (e.g. `lm-studio`)

---

## 6. Dashboard Tabs Reference

### Daily Note

The main note composer. Fields:

- **Title** — headline for the day; used in filename
- **Date** — defaults to today (YYYY-MM-DD)
- **Raw Notes** — free-form dump of the day's events, thoughts, observations
- **Mood** — click a mood button (Energized, Calm, Focused, Tired, Frustrated, Anxious, Excited, Neutral)
- **Energy Level** — 1–10 slider
- **Focus Area** — Work, Personal, Health, Creative, Learning, Social, Finance, Mixed
- **Wins** — accomplishments today
- **Blockers** — what got in the way
- **Tomorrow's Intentions** — goals for next day (auto-converted to Tasks plugin format if plugin enabled)
- **Tags** — press Enter or comma to add tag chips
- **Obsidian Notes to Link** — notes to weave as wikilinks

**AI Prompt Customizer:**
- **System Prompt** — fully editable; control exactly what the AI writes
- **Tone** — Reflective, Analytical, Motivational, Journalistic, Stoic, Casual
- **Length** — Medium (~400w), Long (~800w), Epic (1500w+)
- **Extra Instructions** — per-note overrides

**Presets:** Deep Journal, Dev Log, Executive, Stoic, Creative, Minimal

### Ideas and Thoughts

For rough ideas, questions, shower thoughts, fragments. The AI:
- Identifies the type of idea
- Explores 3–5 angles and dimensions
- Asks and answers key questions the idea raises
- Maps connections to adjacent concepts
- Generates a Mermaid mindmap
- Suggests wikilinks and tags
- Provides "Where to go from here" next steps

**Depth levels:** Brief (~300w), Standard (~600w), Deep (1000w+)

Saved ideas persist in browser storage and are listed in the panel below the output.

### Vault Query

Ask natural language questions about your vault. The backend:
1. Scans your vault notes (up to 100)
2. Ranks by keyword relevance to your query
3. Feeds the top 15 as context to the AI
4. Returns a sourced, detailed answer

**Scopes:** Daily Notes folder, Entire vault, Specific folder

**Answer styles:** Narrative summary, Bullet list, Structured report, Chronological timeline

Any answer can be saved as a standalone Obsidian note in a configurable Queries folder.

### Note History

Persistent log of all generated notes with title, filename, word count, date, and type badge (daily, idea, query, note). Stored in browser localStorage.

### Preview

Live Markdown preview of the last generated note. Buttons:
- **Copy** — copy to clipboard
- **Download .md** — save file locally
- **Send to Obsidian** — write to vault and optionally open in Obsidian

---

## 7. Vault Intelligence: Auto Linker

The Auto Linker scans your vault and uses AI to find meaningful contextual connections between notes, then suggests [[wikilinks]] to insert.

### How it works

1. **Scan** — backend reads all `.md` files in your vault (configurable max)
2. **Batch analysis** — for each source note, the AI compares it against batches of candidate notes
3. **Suggestions** — AI returns JSON objects: `{target, reason, confidence, context}`
4. **Review** — you see each suggestion with the source file, target file, reason, and confidence
5. **Accept/Reject** — accept or reject each individually, or use Accept All / Reject All
6. **Apply** — accepted links are written to the source files in a "Related Notes" section

### Controls

| Setting | Description |
|---------|-------------|
| **Source Note** | Specific file to find links for, or blank to process all notes |
| **Similarity Threshold** | High = only very strong matches; Low = more suggestions |
| **Max Notes to Scan** | 20 / 50 / 100 / All |
| **Insertion Mode** | Suggest only (review first) or Auto-insert approved |

### What the AI looks for

- Shared topics, themes, or concepts
- Same people, projects, or organizations mentioned
- Complementary ideas or arguments
- Sequential or causal relationships
- Shared time periods or events
- Reference relationships (one note cites concepts from another)

### Vault statistics

After a scan, a statistics panel shows: notes scanned, suggestions found, existing links in vault, total vault notes.

---

## 8. Vault Intelligence: Tag Generator

Analyzes note content and generates tags optimized for Obsidian.

### Modes

| Mode | Description |
|------|-------------|
| **Paste content** | Paste any text directly into the analyzer |
| **Point to file** | Provide a vault-relative file path |
| **Scan entire vault** | Generate missing tags for all notes (slow) |

### Tag styles

- **Mixed** — combines flat tags (`#productivity`) and hierarchical (`#work/project-alpha`)
- **Flat** — single words or short phrases only
- **Hierarchical** — parent/child structure with slashes

### Tag quality

The AI optimizes tags for:
- Topical accuracy and specificity
- Obsidian graph view clustering
- Dataview query compatibility
- Coverage: topics, people, projects, emotions, domains, time periods, methodologies

### Applying tags

Tags can be accepted/rejected individually. Clicking "Apply Tags to Note" writes accepted tags into the YAML frontmatter of the file. If no frontmatter exists, it is created.

---

## 9. Obsidian Plugin Integrations

### Tasks Plugin

GitHub: https://github.com/obsidian-tasks-group/obsidian-tasks

When enabled, NoteForge uses the Tasks plugin syntax in all generated notes:

```markdown
- [ ] Review project proposal 📅 2025-01-16 ⏫
- [ ] Write unit tests 📅 2025-01-17 🔼
- [ ] Deploy to staging 🔁 every week
```

Priority markers:
- `🔺` — highest
- `⏫` — high
- `🔼` — medium
- `🔽` — low

**Install in Obsidian:** Settings > Community Plugins > Browse > search "Tasks"

### Calendar Plugin

GitHub: https://github.com/liamcain/obsidian-calendar-plugin

When enabled:
- Daily note filenames use the format the Calendar plugin expects (configurable date format)
- YAML `date:` field is populated in ISO format
- Weekly review sections are added automatically on Friday notes
- Monthly summary prompts are added on the last day of the month
- The NoteForge calendar view shows dots for days with notes and tasks

**Install in Obsidian:** Settings > Community Plugins > Browse > search "Calendar"

### Dataview

When enabled, every note gets comprehensive YAML frontmatter:

```yaml
---
title: "My Daily Note"
date: 2025-01-15
aliases: ["2025-01-15", "Jan 15 2025"]
tags: [daily-note, work, rust, tauri]
mood: Focused
energy: 8
focus: creative
type: daily
created: 2025-01-15T21:30:00
week: "2025-W03"
related: ["[[Project Alpha]]", "[[Goals 2025]]"]
---
```

Example Dataview queries:

```dataview
TABLE mood, energy, focus
FROM "Daily Notes"
WHERE date >= date(today) - dur(7 days)
SORT energy DESC
```

```dataview
LIST
FROM "Daily Notes"
WHERE energy < 5
SORT date ASC
```

**Install:** Settings > Community Plugins > Browse > search "Dataview"

### Periodic Notes

When enabled, NoteForge adds periodic review content:
- **Friday notes** — automatic weekly review section
- **Month-end notes** — monthly summary and retrospective prompts
- **Quarter-end notes** — quarterly goal review

**Install:** Settings > Community Plugins > Browse > search "Periodic Notes"

### Templater

When enabled, Templater variable syntax is included in notes:

```
<% tp.date.now("YYYY-MM-DD") %>
<% tp.file.title %>
```

**Install:** Settings > Community Plugins > Browse > search "Templater"

### Kanban

When enabled, a Kanban board code block is embedded in daily notes:

```kanban
## Backlog
- [ ] Task A
- [ ] Task B

## In Progress
- [ ] Task C

## Done
- [x] Task D
```

**Install:** Settings > Community Plugins > Browse > search "Kanban"

---

## 10. Calendar and Tasks

### Calendar View

The calendar shows the current month with indicators:
- **Purple dot** — a daily note exists for that day
- **Gold dot** — the day has tasks with due dates
- **Click a day** — sets the date field in Daily Note composer and switches to compose tab

Use **Sync Vault** to reload note and task data from the backend.

### Task Scanner

Clicking **Scan Vault** in the Tasks panel reads all `.md` files in your vault and parses Tasks plugin format. Tasks are displayed with:
- Due date (color-coded: overdue=red, due soon=gold, future=green)
- Priority badge
- Source note filename

**Filters:** All, Due Soon (3 days), Overdue, High Priority, No Due Date

Tasks can be checked off in the UI (local state only; does not modify the vault file — use Obsidian for that).

---

## 11. CLI Mode

Full interactive terminal workflow — no browser required.

```bash
# Default Ollama
python server.py --cli

# NVIDIA NIM
python server.py --cli --provider nvidia --nvidia-key nvapi-xxx

# OpenAI
python server.py --cli --provider openai --openai-key sk-xxx --openai-model gpt-4o

# Custom vault
python server.py --cli --vault ~/Documents/MyVault --folder "Journal"
```

CLI prompts you for: mode (daily/idea/query), all entry fields, then generates and optionally saves to vault.

---

## 12. Backend API Reference

All endpoints accept and return JSON. The `config` object in the request body overrides defaults.

### `GET /health`

```json
{
  "status": "ok",
  "provider": "ollama",
  "ai_ok": true,
  "ai_status": "ok — 4 model(s)",
  "model": "llama3",
  "server": "NoteForge v2.0"
}
```

### `POST /generate`

Generate a note. Does not save to disk.

**Request:**
```json
{
  "type": "daily",
  "title": "Shipped auth",
  "date": "2025-01-15",
  "body": "Raw notes...",
  "mood": "Focused",
  "energy": "8",
  "focus": "work",
  "wins": "JWT shipped",
  "blockers": "Rate limiting",
  "tomorrow": "Fix rate limiting",
  "tags": ["rust", "tauri"],
  "system_prompt": "optional override",
  "tone": "reflective",
  "length": "long",
  "features": ["Mermaid Mind Map", "Wiki Links"],
  "config": { "provider": "nvidia", "nvidia": { "key": "nvapi-...", "model": "meta/llama-3.1-70b-instruct" } }
}
```

**Response:**
```json
{
  "note": "---\ntitle: ...",
  "filename": "2025-01-15-shipped-auth.md",
  "words": 847,
  "date": "2025-01-15"
}
```

### `POST /send`

Write a note to the vault.

**Request:**
```json
{
  "note": "full markdown content",
  "filename": "2025-01-15-daily.md",
  "folder_override": "Daily Notes",
  "config": { "vault": "~/vault", "autoopen": "true" }
}
```

**Response:**
```json
{
  "status": "ok",
  "path": "/home/user/vault/Daily Notes/2025-01-15-daily.md",
  "filename": "2025-01-15-daily.md",
  "streak": 7
}
```

### `POST /query`

Query your vault.

**Request:**
```json
{
  "query": "What were my biggest blockers in January?",
  "scope": "vault",
  "maxnotes": 25,
  "style": "summary"
}
```

**Response:**
```json
{
  "answer": "Based on your January notes...",
  "sources": ["Daily Notes/2025-01-10.md", "Projects/Alpha.md"],
  "notes_scanned": 25,
  "query": "What were my biggest blockers..."
}
```

### `POST /link_suggest`

```json
{
  "source": "Daily Notes/2025-01-15.md",
  "threshold": "medium",
  "maxnotes": "50"
}
```

Response: `{ "suggestions": [...], "notes_scanned": 50, "existing_links": 124, "vault_size": 87 }`

### `POST /link_apply`

```json
{
  "suggestions": [
    { "source_file": "Daily Notes/2025-01-15.md", "target_file": "Projects/Alpha.md", "state": "accepted" }
  ]
}
```

Response: `{ "applied": 1, "errors": [] }`

### `POST /generate_tags`

```json
{
  "mode": "paste",
  "content": "full note text...",
  "style": "mixed",
  "count": 10,
  "existing": "#rust, #tauri"
}
```

Response: `{ "tags": [{"tag": "systems-programming", "reason": "..."}, ...], "reasoning": "..." }`

### `POST /apply_tags`

```json
{ "tags": ["rust", "systems-programming"], "file": "Daily Notes/2025-01-15.md" }
```

### `GET /tasks`

Returns all tasks parsed from the vault.

### `GET /calendar_data?year=2025&month=1`

Returns day-by-day note and task indicators for a month.

### `GET /vault/stats`

Returns total notes, daily notes, word count, streak.

---

## 13. Configuration Reference

| Field | Default | Description |
|-------|---------|-------------|
| Backend URL | `http://localhost:5000` | Where server.py is running |
| Vault Path | `~/obsidian-vault` | Absolute path to Obsidian vault |
| Daily Notes Folder | `Daily Notes` | Subfolder for daily notes |
| Ideas Folder | `Ideas` | Subfolder for idea notes |
| Queries Folder | `Queries` | Subfolder for query result notes |
| Date Format | `YYYY-MM-DD` | Filename date prefix |
| Auto-open | `true` | Open in Obsidian after saving |
| Linker Min Length | `200` | Min characters for a note to be link-analyzed |

**CLI flags:**

```
--port              Server port (default 5000)
--host              Bind address (default 127.0.0.1)
--vault             Vault path
--folder            Daily notes subfolder
--provider          ollama | nvidia | openai
--ollama            Ollama host URL
--model             Ollama model name
--nvidia-key        NVIDIA API key
--nvidia-model      NVIDIA model string
--openai-key        OpenAI / compatible API key
--openai-base       API base URL
--openai-model      Model name
--debug             Flask debug mode
--cli               Interactive terminal mode
```

---

## 14. Prompt Presets

| Preset | Best for | Output |
|--------|----------|--------|
| Deep Journal | Personal reflection, emotions | First-person, literary, 800w+ |
| Dev Log | Software engineering days | Structured, technical, Mermaid diagrams |
| Executive | Business and leadership | Sharp, tables, action items with owners |
| Stoic | Philosophy, discipline | Dichotomy of control, Stoic quotes |
| Creative | Art, writing, design days | Evocative, metaphorical, inspiration-led |
| Minimal | Quick capture | Bullets, 3 sentences, under 300 words |

All presets can be further customized in the system prompt text area.

---

## 15. Obsidian Feature Injections

| Feature | Injected syntax |
|---------|----------------|
| Mermaid Mind Map | `mindmap` code block |
| Mermaid Timeline | `timeline` code block |
| Dataview Frontmatter | Full YAML with all fields |
| Callout Blocks | `> [!insight]`, `> [!tip]`, `> [!warning]`, `> [!quote]` |
| Tasks Plugin Format | `- [ ] task 📅 YYYY-MM-DD` with priority markers |
| Wiki Links | `[[concept]]` for people, projects, concepts |
| Graph Tags | Tags chosen for graph view clustering |
| Kanban Card | Kanban board code block |
| Periodic Notes | Weekly/monthly review sections |
| Spaced Repetition | Key learnings flagged for Anki |
| Breadcrumbs | `parent`, `child` metadata fields |
| Templater Vars | `<% tp.date.now() %>` expressions |

---

## 16. Packaging to Executable

Package NoteForge into a standalone `.exe` (Windows) or binary (macOS/Linux) using PyInstaller. No Python installation required on the target machine.

### Step 1 — Install PyInstaller

```bash
pip install pyinstaller
```

### Step 2 — Install all dependencies first

```bash
pip install flask flask-cors requests pyinstaller
```

### Step 3 — Build the executable

**Windows (produces `dist/server.exe`):**

```bash
pyinstaller --onefile --name NoteForge --icon noteforge.ico server.py
```

**macOS/Linux (produces `dist/NoteForge`):**

```bash
pyinstaller --onefile --name NoteForge server.py
```

**With console window hidden (Windows, use --noconsole only for GUI apps — NOT recommended for NoteForge since you want to see logs):**

```bash
pyinstaller --onefile --name NoteForge server.py
```

### Step 4 — Bundle with the HTML file

After building, copy `index.html` next to the executable:

```
dist/
  NoteForge.exe       (or NoteForge on macOS/Linux)
  index.html
```

### Step 5 — Run

```bash
# Windows
dist\NoteForge.exe

# macOS/Linux
./dist/NoteForge

# With NVIDIA key
dist\NoteForge.exe --provider nvidia --nvidia-key nvapi-xxxxx

# Custom vault
dist\NoteForge.exe --vault C:\Users\You\Documents\ObsidianVault
```

Then open `index.html` in your browser.

### Step 6 — Create a launcher script (optional)

**Windows `launch.bat`:**
```bat
@echo off
start NoteForge.exe --vault "%USERPROFILE%\Documents\ObsidianVault"
timeout /t 2 > nul
start index.html
```

**macOS/Linux `launch.sh`:**
```bash
#!/bin/bash
./NoteForge --vault ~/Documents/ObsidianVault &
sleep 2
open index.html        # macOS
# xdg-open index.html  # Linux
```

### Spec file for advanced control

Create `noteforge.spec` for full control over the build:

```python
# noteforge.spec
from PyInstaller.building.build_main import Analysis, PYZ, EXE

a = Analysis(
    ['server.py'],
    pathex=['.'],
    binaries=[],
    datas=[('index.html', '.')],   # bundle index.html too if desired
    hiddenimports=['flask_cors'],
    hookspath=[],
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz, a.scripts, a.binaries, a.datas,
    name='NoteForge',
    debug=False,
    console=True,          # keep True to see server logs
    onefile=True,
)
```

Build with the spec:
```bash
pyinstaller noteforge.spec
```

### Distributing to other machines

The `dist/NoteForge.exe` is self-contained. Copy it along with `index.html` to any Windows machine. No Python, Flask, or any dependency installation needed. The user needs:

- The NoteForge executable
- `index.html` (open in any browser)
- Ollama installed (if using local AI) OR a NVIDIA/OpenAI API key

### macOS app bundle (optional)

```bash
pip install pyinstaller
pyinstaller --onefile --windowed --name NoteForge \
  --osx-bundle-identifier com.noteforge.app server.py
```

Note: On macOS you may need to right-click and "Open" the first time due to Gatekeeper.

### Windows Defender false positives

PyInstaller executables sometimes trigger Windows Defender. To fix:
1. Add the `dist/` folder to Windows Defender exclusions
2. Or sign the executable with a code signing certificate
3. Or rebuild with `--key` flag for encrypted bytecode

---

## 17. Obsidian Setup and Recommended Plugins

### Vault folder structure

```
ObsidianVault/
  Daily Notes/
    2025-01-15-shipped-auth.md
    2025-01-16-daily.md
  Ideas/
    2025-01-15-distributed-systems-idea.md
  Queries/
    2025-01-20-query-january-blockers.md
  Projects/
  People/
  Resources/
```

### Recommended plugin install order

1. **Dataview** — query notes as a database
2. **Tasks** — task tracking with due dates
3. **Calendar** — visual calendar view
4. **Periodic Notes** — weekly/monthly/quarterly notes
5. **Templater** — dynamic templates
6. **Kanban** — board view for tasks

### Example Dataview queries to add to your vault

**Weekly energy report:**
```dataview
TABLE date, mood, energy, focus
FROM "Daily Notes"
WHERE date >= date(today) - dur(7 days)
SORT date DESC
```

**All high-priority tasks:**
```tasks
not done
priority is high
sort by due
```

**Ideas by category:**
```dataview
TABLE file.ctime AS created, tags
FROM "Ideas"
SORT file.ctime DESC
```

---

## 18. Troubleshooting

### Backend unreachable

```bash
# Check it's running
curl http://localhost:5000/health

# Try a different port
python server.py --port 8080
# Then update Backend URL in Configuration to http://localhost:8080
```

### Ollama not responding

```bash
# Check if running
ollama list

# Start it
ollama serve

# Test directly
curl http://localhost:11434/api/tags

# Pull the model
ollama pull llama3
```

### NVIDIA API 401 Unauthorized

- Make sure your key starts with `nvapi-`
- Get a fresh key from build.nvidia.com
- Try the "Test NVIDIA API Key" button in Configuration

### NVIDIA API 402 / quota exceeded

- The free tier has monthly credit limits
- Visit build.nvidia.com to check your usage
- Consider switching to Ollama for free unlimited local inference

### Vault not found / Permission denied

- Use the full absolute path (not `~/`) if running from unusual environments
- Windows: use `C:\Users\You\ObsidianVault` format
- Check write permissions: `ls -la ~/obsidian-vault`

### Generated note is too short

- Select "Epic" length in the prompt customizer
- Add to Extra Instructions: "Write at least 1200 words. Be detailed and expansive."
- Use a larger model (llama3:70b, nemotron-70b)

### Auto Linker finds no suggestions

- Make sure your vault has multiple notes with overlapping topics
- Lower the similarity threshold to "Low"
- Increase Max Notes to Scan
- Ensure notes have at least 200 characters (configurable in Config)

### Tags not applying to file

- The file path must be relative to the vault root (e.g., `Daily Notes/2025-01-15.md`)
- Check vault path is correct in Configuration
- Ensure the file exists and is writable

### PyInstaller build fails

```bash
# Make sure all deps installed in same environment
pip install flask flask-cors requests pyinstaller

# If hidden import errors
pyinstaller --onefile --hidden-import flask_cors server.py

# Clean previous build
rm -rf build dist *.spec
pyinstaller --onefile --name NoteForge server.py
```

### macOS: "cannot be opened because the developer cannot be verified"

```bash
# Remove quarantine attribute
xattr -d com.apple.quarantine dist/NoteForge
```

---

## License

MIT — free to use, modify, distribute.

*NoteForge — Because your days deserve more than a bullet point.*
