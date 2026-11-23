REDCap Single-Line Converter - Ultra-Compact Portable Kit
=========================================================
Zero dependencies (Python 3 stdlib only), pure Command Prompt (no PowerShell), no admin rights.

Quick Start (Visual GUI - No CLI Needed):
  - Option A (Hybrid Python + Browser GUI): Double-click launch_gui.bat (or drag any
    REDCap CSV onto launch_gui.bat). Uses local Python if available (including py\python.exe)
    and automatically falls back to opening redcap_converter.html if Python is absent.
  - Option B (Zero-Install Offline HTML): Double-click redcap_converter.html directly in
    Edge/Chrome on any locked-down PC (zero Python, zero scripts, 100% offline in memory).
  - Visually search/filter fields, pick per-field collapse modes, preview 5-20 rows, and
    save/load .profile.json files compatible with the CLI and MCP server.

Quick Start (Interactive CMD Field Picker):
  1. Unzip this folder anywhere (e.g. C:\Tools\redcap-singleline\).
  2. Double-click run_converter.bat OR drag-and-drop any REDCap CSV onto run_converter.bat.
  3. Pick fields by number/range/name (e.g. 1-4, 7:join, 9:wide) and collapse mode.
  4. Optional: Save a JSON profile to re-run future exports in one command:
       run_converter.bat new_export.csv --profile my_study.profile.json

No Python Installed & No Admin Rights?
  - For the GUI: just double-click redcap_converter.html directly (no Python needed).
  - For the CLI/Python engine: download the official Python 3 Windows embeddable zip from
    python.org and unzip it into a subfolder named py\ inside this folder (py\python.exe).

Antigravity IDE + Orchestrator (Neon) MCP Setup:
  See ANTIGRAVITY_NEON_PROMPT.md and mcp_config.snippet.json.
