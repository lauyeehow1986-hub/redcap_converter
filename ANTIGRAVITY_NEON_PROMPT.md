# Antigravity IDE + Orchestrator (Neon) Workflow

This guide sets up the portable, zero-dependency `redcap-singleline` MCP server in Google Antigravity IDE (or CLI) using **Orchestrator (Neon)** as the planner and **Hydrogen** as the execution worker, using **Command Prompt (`cmd.exe`) only** (no PowerShell, no admin rights).

## 1. Zero-Admin Portable Setup (Windows CMD)

1. Unzip the portable kit to any user-writable folder (for example `C:\Tools\redcap-singleline\`).
2. Verify Python 3 is available in Command Prompt (`cmd.exe`):
   ```cmd
   python --version
   ```
   If Python is not installed and you have no admin rights, download the official Python 3 Windows **embeddable package (64-bit zip)** from python.org and unzip it into `C:\Tools\redcap-singleline\py\` (so `C:\Tools\redcap-singleline\py\python.exe` exists). Both `run_converter.bat` and `start_mcp.bat` auto-detect `.\py\python.exe` first.
3. Register the MCP server in Antigravity's central config file:
   - Path: `%USERPROFILE%\.gemini\config\mcp_config.json`
   - Or in Antigravity IDE: open the agent panel `...` menu -> **Manage MCP Servers** -> **View raw config**.
   - Merge this entry (update the path if you unzipped elsewhere):
     ```json
     {
       "mcpServers": {
         "redcap-singleline": {
           "command": "cmd.exe",
           "args": ["/c", "C:\\Tools\\redcap-singleline\\start_mcp.bat"],
           "env": { "PYTHONIOENCODING": "utf-8" }
         }
       }
     }
     ```
4. Refresh MCP servers in Antigravity (**Settings -> Customizations -> Installed MCP Servers -> Refresh**).

## 2. Copy-Paste Master Prompt for Orchestrator (Neon)

Select **Orchestrator (Neon)** in the Antigravity model selector and paste this prompt:

```text
You are operating as Orchestrator (Neon) with Hydrogen as execution worker.
Workspace folder: C:\Tools\redcap-singleline
Constraint: Use Command Prompt (cmd.exe) only. Never use PowerShell, never require admin rights, and keep all code zero-dependency Python 3 standard library.

Goal: Build/verify and run our portable general REDCap Repeating Instruments & Events Single-Line Converter using the `redcap-singleline` MCP server.

Execution Plan:
1. Call `inspect_redcap_csv` on my target REDCap CSV file: "<PATH_TO_YOUR_REDCAP_EXPORT.csv>".
2. Present a compact grouped table of detected fields (static, repeating_instrument, repeating_event, longitudinal) and ask me which fields to collapse into a single line per record, plus my preferred collapse mode per field (`wide`, `join`, `unique`, `first`, `last`, `count`, `min`, `max`, `sum`, `mean`).
3. Once I choose the fields, call `preview_singleline` (preview_limit=5) and show me the exact resulting column names and sample single-line rows.
4. On my approval, call `convert_redcap_to_singleline` to write the output CSV, verify `output_rows == unique_records_total`, and call `manage_conversion_profile` to save a reusable JSON profile so I can re-run future exports via `run_converter.bat <new_export.csv> --profile <profile.json>` in CMD.

If I ask to extend the converter (for example adding custom date formatting or new aggregation rules), plan the minimal diff in Neon, delegate edits and unit-test execution (`cmd /c python test_redcap_flatten.py`) to Hydrogen, and keep total footprint compact with zero external pip dependencies.
```
