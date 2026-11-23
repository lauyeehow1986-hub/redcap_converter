---
name: redcap-singleline-converter
description: Build, configure, and run a compact, portable, non-admin Command Prompt converter, Hybrid Browser/Python GUI, and zero-dependency stdio MCP server that flattens any REDCap repeating instruments and repeating events CSV or TSV export into a single line per record with selective field picking. Use whenever the user wants to convert multi-line REDCap exports to one row per record, collapse repeating instruments or longitudinal events, pick specific REDCap fields via GUI or CLI to pivot wide or join, set up a portable Windows REDCap tool without PowerShell or admin rights, or orchestrate REDCap conversion in Google Antigravity IDE with Orchestrator (Neon).
---

# REDCap Single-Line Converter

Flatten any multi-line REDCap export (classic or longitudinal, raw or labeled headers, repeating instruments and repeating events) into a single line per record while letting the user pick which fields to include and how to collapse each field.

## When to Use

- Converting a multi-line REDCap CSV or TSV export into one row per record ID.
- Letting non-CLI users visually pick fields, assign collapse modes, preview rows, and save profiles in the **Hybrid Browser/Python GUI** (`redcap_converter.html` / `launch_gui.bat`).
- Letting a user interactively pick specific fields via CLI (`wide`, `join`, `unique`, `first`, `last`, `count`, `min`, `max`, `sum`, `mean`, `auto`).
- Deploying a portable Windows tool that avoids PowerShell, `tkinter` dependencies, and administrator privileges or pip installations.
- Connecting a lightweight stdio MCP server to Google Antigravity IDE using Orchestrator (Neon) to plan and Hydrogen to execute.

## Bundled Assets

- `scripts/redcap_flatten.py`: Zero-dependency Python 3 stdlib converter with interactive CMD field picker, CLI flags, wildcard checkbox selection (`var___*`), and JSON profile support.
- `scripts/redcap_gui_server.py`: Zero-dependency loopback (`127.0.0.1`) HTTP server backing the Hybrid GUI with `redcap_flatten.py`.
- `scripts/redcap_mcp_server.py`: Zero-dependency JSON-RPC 2.0 stdio MCP server exposing `inspect_redcap_csv`, `preview_singleline`, `convert_redcap_to_singleline`, and `manage_conversion_profile`.
- `scripts/test_redcap_flatten.py` & `scripts/test_gui_and_parity.py`: End-to-end converter, MCP, offline-safety, Python-vs-JS parity, and live HTTP GUI server tests.
- `assets/redcap_converter.html`: Self-contained Hybrid GUI (runs offline in browser with zero Python via `file://`, or automatically connects to `redcap_gui_server.py` when launched via `launch_gui.bat`).
- `assets/launch_gui.bat`: Pure `cmd.exe` Hybrid GUI launcher supporting drag-and-drop CSV files, portable `.\py\python.exe`, and automatic fallback to `redcap_converter.html` when Python is absent.
- `assets/run_converter.bat`: Pure `cmd.exe` CLI launcher supporting drag-and-drop CSV files and portable embeddable Python (`.\py\python.exe`).
- `assets/start_mcp.bat`: Pure `cmd.exe` MCP launcher for `mcp_config.json`.
- `assets/mcp_config.snippet.json`: Ready-to-merge config block for `%USERPROFILE%\.gemini\config\mcp_config.json`.
- `references/antigravity-neon-workflow.md`: Step-by-step Antigravity IDE Orchestrator (Neon) setup and copy-paste master prompt.

## Steps

1. Inspect the REDCap export schema first so you never guess column names or repeat structure.
   - Via MCP: call `inspect_redcap_csv(input_path="...")`.
   - Via CMD: run `run_converter.bat export.csv --inspect`.
   - Via Hybrid GUI: double-click `launch_gui.bat` (or `redcap_converter.html` when zero-install offline mode is needed) and drag/drop the CSV.
   - Confirm the detected record ID column (column 1 by default), system columns (`redcap_event_name`, `redcap_repeat_instrument`, `redcap_repeat_instance`, `redcap_data_access_group`, or their labeled equivalents), and whether each field is `static`, `repeating_instrument`, `repeating_event`, or `longitudinal`.

2. Select fields and per-field collapse modes.
   - `wide`: Expands multi-line values into naturally sorted columns (`field__event_inst_i1`, `field__event_inst_i2`, ..., `field__event_inst_i10`).
   - `join` or `unique`: Collapses multi-line values into one cell separated by `--sep` (default `"; "`), optionally prefixed with `[slot]` via `--tag-instance`.
   - `first`, `last`, `count`, `min`, `max`, `sum`, `mean`: Produces a single summary value per record.
   - `auto`: Keeps static fields as one column and pivots multi-line fields wide.
   - Checkbox groups support wildcards such as `symptoms___*`.

3. Preview before writing the full file.
   - Via MCP: call `preview_singleline` with `preview_limit=5` to verify output columns and sample values.
   - Via Hybrid GUI: click **Preview Output** to inspect the sticky-header single-line preview table.

4. Run the full single-line conversion and verify row integrity.
   - Via MCP: call `convert_redcap_to_singleline(input_path="...", output_path="...", fields=[...], default_mode="wide", field_modes={...})`.
   - Via Hybrid GUI: click **Convert & Export** and verify the green integrity banner (`output_rows == unique_records_total`).
   - Via CMD interactive picker: double-click `run_converter.bat` or drag any REDCap CSV onto `run_converter.bat`.

5. Save a reusable JSON profile for recurring exports.
   - Call `manage_conversion_profile(action="save", ...)`, click **Save Profile (.json)** in the Hybrid GUI, or answer `y` at the end of interactive CMD mode so future exports run cleanly across GUI, CLI (`--profile study.profile.json`), and MCP.

## Gotchas

- Never use PowerShell scripts, `tkinter` (missing from Python Windows embeddable zips), or `pip install` when deploying on locked-down hospital or institutional Windows PCs. Both the Python server and the embedded JS engine work with zero external dependencies.
- Never assume the primary key is always named `record_id`. Many REDCap projects rename column 1 (for example `study_id` or `patient_id`). The converter auto-detects column 1 and accepts `--id-col` (or dropdown override in the GUI).
- Repeating events leave `redcap_repeat_instrument` blank while populating `redcap_repeat_instance`. Always distinguish repeating instruments from repeating events so wide column names stay collision-free.
- In wide mode, sort repeat instances numerically (`i1, i2, ..., i10`), not lexicographically (`i1, i10, i2`).
