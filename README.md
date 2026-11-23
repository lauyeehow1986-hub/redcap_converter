# REDCap Single-Line Converter (Portable Hybrid GUI, CLI & MCP)

Flatten any multi-line REDCap CSV/TSV export (classic or longitudinal, raw or labeled headers, repeating instruments and repeating events) into a single row per record while selectively picking fields and per-field collapse strategies.

- **100% Local & Offline (PHI-Safe):** No network calls, no external CDNs, no telemetry. All data stays on your machine.
- **Zero External Dependencies:** Pure Python 3 standard library + self-contained HTML/JS. No `pip install`, no `tkinter`, no PowerShell, and no administrator privileges required.

---

## Quick Start

### 1. Visual Hybrid GUI (Recommended for Non-CLI Users)
- **Option A — Hybrid Launcher (Windows):** Double-click `launch_gui.bat` (or drag any REDCap CSV/TSV onto it).
  - Automatically detects installed Python 3 or portable `.\py\python.exe` (including Python's official Windows embeddable zip, which omits `tkinter`) and opens the local loopback (`127.0.0.1`) GUI in your default browser backed by `redcap_flatten.py`.
  - If Python is not installed at all, `launch_gui.bat` automatically falls back to opening `redcap_converter.html` directly in your browser.
- **Option B — Zero-Install Single-File Mode:** Double-click or share `redcap_converter.html` directly in Edge or Chrome. Runs 100% offline in-browser with no Python or batch files required.

**GUI Features:**
- Drag-and-drop CSV/TSV inspection (and direct local path input in Python mode for 100 MB+ exports)
- Search by field name or `*` wildcard, filter by field type (`STATIC`, `REP-INST`, `REP-EVT`, `LONG`), instrument, or event
- Shift+Click range selection, one-click `prefix___*` checkbox group buttons, and per-field or bulk collapse mode overrides
- Live 5 / 10 / 20-record single-line preview table and row-integrity verification (`output_rows == unique_records_total`)
- Save/load `.profile.json` configurations interoperable with the CLI and Antigravity MCP server

### 2. Interactive Command Prompt & CLI
- Double-click `run_converter.bat` or drag any REDCap CSV onto `run_converter.bat` to open the interactive CMD field picker (`1-4, 7:join, 9:wide`).
- Or run headless with flags / saved profiles:
  ```cmd
  run_converter.bat export.csv --profile study.profile.json
  run_converter.bat export.csv -f "age,med_name:join,med_dose_mg:sum,symp___*" -o out_singleline.csv
  ```

### 3. Antigravity IDE Skill & MCP Server
- Register `start_mcp.bat` using `mcp_config.snippet.json` in `%USERPROFILE%\.gemini\config\mcp_config.json`.
- Exposes 4 zero-dependency stdio JSON-RPC 2.0 MCP tools: `inspect_redcap_csv`, `preview_singleline`, `convert_redcap_to_singleline`, and `manage_conversion_profile`.
- See `SKILL.md` and `ANTIGRAVITY_NEON_PROMPT.md` for workflow setup.

---

## Supported Collapse Modes

| Mode | Behavior |
| :--- | :--- |
| `wide` | Expands multi-line values into naturally sorted columns (`field__event_inst_i1`, `..._i2`, ..., `..._i10`) |
| `auto` | Keeps single-entry fields as one column and pivots multi-line fields wide |
| `join` | Combines all non-empty values in chronological/instance order separated by `--sep` (default `; `) |
| `unique` | Combines distinct non-empty values into one cell |
| `first` / `last` | Keeps earliest or latest non-empty value |
| `count` | Counts non-empty values per record |
| `min` / `max` / `sum` / `mean` | Numeric summary aggregations (non-numeric tokens safely ignored) |

---

## No Python Installed & No Admin Rights?
- **For the Visual GUI:** Just double-click `redcap_converter.html` directly (no Python needed).
- **For CLI / Large-File Python Engine:** Download the official Python 3 Windows **embeddable package (64-bit zip)** from python.org and unzip it into a `py\` subfolder next to `launch_gui.bat` and `run_converter.bat` (`py\python.exe`).

---

## Verification Tests

Run the included end-to-end tests (Python 3 stdlib + Node.js required for JS parity tests):

```cmd
python test_redcap_flatten.py
python test_gui_and_parity.py
```
