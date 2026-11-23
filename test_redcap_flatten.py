#!/usr/bin/env python3
"""End-to-end verification tests for redcap_flatten.py and redcap_mcp_server.py."""

import csv
import json
import subprocess
import sys
import tempfile
from pathlib import Path

_HERE = Path(__file__).resolve().parent
SCRIPTS_DIR = _HERE if (_HERE / "redcap_flatten.py").exists() else (_HERE.parent / "scripts")
sys.path.insert(0, str(SCRIPTS_DIR))

from redcap_flatten import convert_redcap, inspect_redcap  # noqa: E402


def write_sample_longitudinal_mixed(path: Path) -> None:
    """Create a realistic REDCap CSV with static baseline, repeating instrument, repeating event, checkboxes, and multi-line text."""
    headers = [
        "study_id",
        "redcap_event_name",
        "redcap_repeat_instrument",
        "redcap_repeat_instance",
        "redcap_data_access_group",
        "age",
        "sex",
        "med_name",
        "med_dose_mg",
        "bp_sys",
        "symp___1",
        "symp___2",
        "notes",
    ]
    rows = [
        # Record 101: baseline static + 2 repeating meds + 2 repeating unscheduled visits
        ["101", "baseline_arm_1", "", "", "hosp_a", "54", "M", "", "", "128", "1", "0", "Baseline\nok"],
        ["101", "baseline_arm_1", "medications", "1", "hosp_a", "", "", "Aspirin", "100", "", "", "", ""],
        ["101", "baseline_arm_1", "medications", "2", "hosp_a", "", "", "Metformin", "500", "", "", "", ""],
        ["101", "unsched_arm_1", "", "1", "hosp_a", "", "", "", "", "142", "", "", "Followup 1"],
        ["101", "unsched_arm_1", "", "2", "hosp_a", "", "", "", "", "136", "", "", "Followup 2"],
        # Record 102: baseline static + 10 repeating meds (tests natural numeric sort i1..i10!)
        ["102", "baseline_arm_1", "", "", "hosp_b", "67", "F", "", "", "120", "0", "1", ""],
        ["102", "baseline_arm_1", "medications", "1", "hosp_b", "", "", "Drug1", "10", "", "", "", ""],
        ["102", "baseline_arm_1", "medications", "2", "hosp_b", "", "", "Drug2", "20", "", "", "", ""],
        ["102", "baseline_arm_1", "medications", "10", "hosp_b", "", "", "Drug10", "100", "", "", "", ""],
    ]
    with open(path, "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(headers)
        w.writerows(rows)


def write_sample_labeled_classic(path: Path) -> None:
    """Create a labeled classic REDCap export (no event column, human-readable system headers)."""
    headers = ["Record ID", "Repeat Instrument", "Repeat Instance", "Diagnosis", "Lab Value"]
    rows = [
        ["P01", "", "", "HTN", ""],
        ["P01", "Labs", "1", "", "5.2"],
        ["P01", "Labs", "2", "", "6.8"],
        ["P02", "", "", "DM", ""],
        ["P02", "Labs", "1", "", "7.1"],
    ]
    with open(path, "w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(headers)
        w.writerows(rows)


def test_converter_and_mcp() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        td = Path(tmp)
        mixed_csv = td / "mixed_redcap.csv"
        out_csv = td / "mixed_singleline.csv"
        labeled_csv = td / "labeled_classic.csv"
        labeled_out = td / "labeled_singleline.csv"

        write_sample_longitudinal_mixed(mixed_csv)
        write_sample_labeled_classic(labeled_csv)

        # 1. Inspect mixed longitudinal + repeating export
        info = inspect_redcap(mixed_csv)
        assert info["id_col"] == "study_id"
        assert info["unique_records"] == 2
        assert info["total_rows"] == 9
        assert info["max_repeat_instance"] == 10
        kinds = {f["name"]: f["kind"] for f in info["fields"]}
        assert kinds["age"] == "static"
        assert kinds["med_name"] == "repeating_instrument"
        assert kinds["bp_sys"] == "repeating_event"

        # 2. Convert with selective fields & mixed modes + wildcard checkbox
        res = convert_redcap(
            input_path=mixed_csv,
            output_path=out_csv,
            fields=["age", "med_name", "med_dose_mg", "bp_sys", "symp___*"],
            default_mode="wide",
            field_modes={"med_name": "join", "med_dose_mg": "sum", "bp_sys": "max"},
            sep=" | ",
        )
        assert res["output_rows"] == 2
        with open(out_csv, "r", encoding="utf-8-sig", newline="") as fh:
            rows = list(csv.DictReader(fh))
        assert len(rows) == 2
        r101, r102 = rows[0], rows[1]
        assert r101["study_id"] == "101"
        assert r101["redcap_data_access_group"] == "hosp_a"
        assert r101["age"] == "54"
        assert r101["med_name"] == "Aspirin | Metformin"
        assert r101["med_dose_mg"] == "600"
        assert r101["bp_sys"] == "142"
        assert r101["symp___1"] == "1" and r101["symp___2"] == "0"
        assert r102["med_name"] == "Drug1 | Drug2 | Drug10"  # natural numeric sort!
        assert r102["med_dose_mg"] == "130"

        # 3. Wide mode natural column ordering test (i1, i2, i10 - NOT i1, i10, i2)
        res_wide = convert_redcap(
            input_path=mixed_csv,
            output_path=None,
            fields=["med_name"],
            default_mode="wide",
            preview_limit=2,
        )
        assert res_wide["output_columns"] == [
            "study_id",
            "redcap_data_access_group",
            "med_name__baseline_arm_1_medications_i1",
            "med_name__baseline_arm_1_medications_i2",
            "med_name__baseline_arm_1_medications_i10",
        ], f"Unexpected columns: {res_wide['output_columns']}"

        # 4. Labeled classic REDCap test
        res_lbl = convert_redcap(
            input_path=labeled_csv,
            output_path=labeled_out,
            fields=["Diagnosis", "Lab Value"],
            default_mode="wide",
            field_modes={"Lab Value": "mean"},
        )
        assert res_lbl["output_rows"] == 2
        with open(labeled_out, "r", encoding="utf-8-sig", newline="") as fh:
            lrows = list(csv.DictReader(fh))
        assert lrows[0]["Record ID"] == "P01"
        assert lrows[0]["Diagnosis"] == "HTN"
        assert lrows[0]["Lab Value"] == "6"

        # 5. End-to-end stdio JSON-RPC 2.0 MCP Server test
        server_script = SCRIPTS_DIR / "redcap_mcp_server.py"
        requests = [
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2024-11-05"}},
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
            {
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {"name": "inspect_redcap_csv", "arguments": {"input_path": str(mixed_csv)}},
            },
            {
                "jsonrpc": "2.0",
                "id": 4,
                "method": "tools/call",
                "params": {
                    "name": "convert_redcap_to_singleline",
                    "arguments": {
                        "input_path": str(mixed_csv),
                        "output_path": str(td / "mcp_out.csv"),
                        "fields": ["age", "med_name"],
                        "field_modes": {"med_name": "join"},
                    },
                },
            },
        ]
        payload = "\n".join(json.dumps(r) for r in requests) + "\n"
        proc = subprocess.run(
            [sys.executable, "-u", str(server_script)],
            input=payload,
            text=True,
            capture_output=True,
            check=True,
        )
        responses = [json.loads(line) for line in proc.stdout.strip().splitlines()]
        assert len(responses) == 4, f"Expected 4 responses, got {len(responses)}"
        assert responses[0]["result"]["serverInfo"]["name"] == "redcap-singleline-mcp"
        tool_names = [t["name"] for t in responses[1]["result"]["tools"]]
        assert set(tool_names) == {
            "inspect_redcap_csv",
            "preview_singleline",
            "convert_redcap_to_singleline",
            "manage_conversion_profile",
        }
        inspect_payload = json.loads(responses[2]["result"]["content"][0]["text"])
        assert inspect_payload["unique_records"] == 2
        conv_payload = json.loads(responses[3]["result"]["content"][0]["text"])
        assert conv_payload["output_rows"] == 2
        assert Path(td / "mcp_out.csv").exists()

    print("ALL TESTS PASSED (converter + labeled classic + wide natural sort + stdio MCP JSON-RPC 2.0)")


if __name__ == "__main__":
    test_converter_and_mcp()
