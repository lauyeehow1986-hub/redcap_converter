#!/usr/bin/env python3
"""Verification tests for Hybrid GUI: offline safety, Python-vs-JS parity, and HTTP server."""

from __future__ import annotations

import argparse
import csv
import json
import re
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from pathlib import Path

_HERE = Path(__file__).resolve().parent
SCRIPTS_DIR = _HERE if (_HERE / "redcap_flatten.py").exists() else (_HERE.parent / "scripts")
ASSETS_DIR = _HERE if (_HERE / "redcap_converter.html").exists() else (_HERE.parent / "assets")
HTML_PATH = ASSETS_DIR / "redcap_converter.html"
SERVER_SCRIPT = SCRIPTS_DIR / "redcap_gui_server.py"

sys.path.insert(0, str(SCRIPTS_DIR))
from redcap_flatten import VALID_MODES, convert_redcap, inspect_redcap  # noqa: E402
from redcap_gui_server import RedcapGuiApp  # noqa: E402


def _extract_js_engine(html_text: str) -> str:
    m = re.search(
        r"// REDCAP_CORE_ENGINE_START\s*(.*?)\s*// REDCAP_CORE_ENGINE_END",
        html_text,
        flags=re.DOTALL,
    )
    assert m, "Could not find REDCAP_CORE_ENGINE_START/END markers in redcap_converter.html"
    return m.group(1)


def test_offline_safety() -> None:
    html_text = HTML_PATH.read_text(encoding="utf-8")
    assert "window.__REDCAP_SERVER__ = null;" in html_text, "Missing boot marker"
    _extract_js_engine(html_text)
    bad_refs = re.findall(r"""(?:https?://|//cdn\.|@import\s+url)""", html_text, flags=re.IGNORECASE)
    assert not bad_refs, f"External URLs found in offline HTML: {bad_refs}"


def _run_js_batch(engine_js: str, cases: list[dict], td: Path) -> list[dict]:
    harness_path = td / "parity_harness.mjs"
    cases_path = td / "parity_cases.json"
    cases_path.write_text(json.dumps(cases), encoding="utf-8")
    harness_code = (
        'import fs from "node:fs";\n'
        + engine_js
        + "\n"
        + """
const cases = JSON.parse(fs.readFileSync(process.argv[2], "utf8"));
const results = [];
for (const c of cases) {
  const bytes = fs.readFileSync(c.path);
  const text = globalThis.RedcapEngine.decodeBytes(bytes);
  const info = globalThis.RedcapEngine.inspectRedcapText(text, {
    filename: c.filename,
    id_col: c.id_col || undefined,
  });
  const conv = globalThis.RedcapEngine.convertRedcapText(text, Object.assign({ filename: c.filename }, c.convert_opts));
  const outDelim = c.out_delim || ",";
  const serialized = globalThis.RedcapEngine.serializeDelimited(conv.output_columns, conv.all_rows, outDelim, true);
  results.push({ inspect: info, convert: conv, serialized });
}
process.stdout.write(JSON.stringify(results));
"""
    )
    harness_path.write_text(harness_code, encoding="utf-8")
    proc = subprocess.run(
        ["node", str(harness_path), str(cases_path)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    )
    return json.loads(proc.stdout)


def _write_mixed_csv(path: Path) -> None:
    headers = [
        "study_id",
        "alt_id",
        "redcap_event_name",
        "redcap_repeat_instrument",
        "redcap_repeat_instance",
        "redcap_data_access_group",
        "age",
        "med_name",
        "med_dose_mg",
        "bp_sys",
        "symp___1",
        "symp___2",
        "notes",
    ]
    rows = [
        ["101", "A-101", "baseline_arm_1", "", "", "hosp_a", "54", "", "", "128", "1", "0", "Baseline\nok"],
        ["101", "A-101", "baseline_arm_1", "medications", "1", "hosp_a", "", "Aspirin", "100", "", "", "", ""],
        ["101", "A-101", "baseline_arm_1", "medications", "2", "hosp_a", "", "Metformin", "500", "", "", "", ""],
        ["101", "A-101", "baseline_arm_1", "medications", "3", "hosp_a", "", "Aspirin", "N/A", "", "", "", ""],
        ["101", "A-101", "unsched_arm_1", "", "1", "hosp_a", "", "", "", "142", "", "", "Followup 1"],
        ["101", "A-101", "unsched_arm_1", "", "2", "hosp_a", "", "", "", "136", "", "", "Followup 2"],
        ["102", "A-102", "baseline_arm_1", "", "", "hosp_b", "67", "", "", "120", "0", "1", ""],
        ["102", "A-102", "baseline_arm_1", "medications", "1", "hosp_b", "", "Drug1", "10", "", "", "", ""],
        ["102", "A-102", "baseline_arm_1", "medications", "2", "hosp_b", "", "Drug2", "20", "", "", "", ""],
        ["102", "A-102", "baseline_arm_1", "medications", "10", "hosp_b", "", "Drug10", "100", "", "", "", ""],
    ]
    with open(path, "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(headers)
        w.writerows(rows)


def _write_labeled_edge_csv(path: Path) -> None:
    headers = ["Record ID", "Repeat Instrument", "Repeat Instance", "Diagnosis", "Lab Value", "Rare Metric"]
    rows = [
        ["P01", "", "", "HTN", "", ""],
        ["P01", "Labs", "1", "", "1", "0.00001234"],
        ["P01", "Labs", "2", "", "2", "0.00001234"],
        ["P01", "Labs", "3", "", "7", ""],
        ["P02", "", "", "DM", "", ""],
        ["P02", "Labs", "1", "", "6.0", "12346"],
        ["P02", "Labs", "2", "", "6.5", "12346"],
    ]
    with open(path, "w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(headers)
        w.writerows(rows)


def _write_cp1252_late_tsv(path: Path) -> None:
    headers = ["rec_id", "repeat_instrument", "repeat_instance", "note"]
    pad = "A" * 5000
    rows = [
        ["R1", "notes", "1", pad],
        ["R1", "notes", "2", "Caf\u00e9 \u201ctest\u201d"],
    ]
    lines = ["\t".join(headers)] + ["\t".join(r) for r in rows]
    path.write_bytes(("\r\n".join(lines) + "\r\n").encode("cp1252"))


def test_python_vs_js_parity(td: Path) -> None:
    engine_js = _extract_js_engine(HTML_PATH.read_text(encoding="utf-8"))
    mixed_csv = td / "mixed.csv"
    labeled_csv = td / "labeled.csv"
    cp1252_tsv = td / "late_cp1252.tsv"
    _write_mixed_csv(mixed_csv)
    _write_labeled_edge_csv(labeled_csv)
    _write_cp1252_late_tsv(cp1252_tsv)

    cases = [
        {
            "name": "all_11_modes_plus_tag",
            "path": str(mixed_csv),
            "filename": mixed_csv.name,
            "convert_opts": {
                "fields": ["age", "med_name", "med_dose_mg", "bp_sys", "symp___*", "notes"],
                "default_mode": "auto",
                "field_modes": {
                    "age": "first",
                    "med_name": "unique",
                    "med_dose_mg": "sum",
                    "bp_sys": "max",
                    "notes": "last",
                },
                "sep": " | ",
                "tag_instance": True,
            },
        },
        {
            "name": "wide_and_aggregates",
            "path": str(mixed_csv),
            "filename": mixed_csv.name,
            "convert_opts": {
                "fields": ["med_name", "med_dose_mg", "bp_sys"],
                "default_mode": "wide",
                "field_modes": {"med_dose_mg": "min", "bp_sys": "count"},
                "include_dag": False,
                "filter_events": ["baseline_arm_1"],
            },
        },
        {
            "name": "join_and_id_override",
            "path": str(mixed_csv),
            "filename": mixed_csv.name,
            "id_col": "alt_id",
            "convert_opts": {
                "fields": ["med_name", "med_dose_mg"],
                "default_mode": "join",
                "field_modes": {"med_dose_mg": "mean"},
                "id_col": "alt_id",
                "filter_instruments": ["medications"],
                "tag_instance": True,
            },
        },
        {
            "name": "labeled_float_formatting",
            "path": str(labeled_csv),
            "filename": labeled_csv.name,
            "convert_opts": {
                "fields": ["Diagnosis", "Lab Value", "Rare Metric"],
                "default_mode": "wide",
                "field_modes": {"Lab Value": "mean", "Rare Metric": "mean"},
            },
        },
        {
            "name": "cp1252_past_4096_tsv",
            "path": str(cp1252_tsv),
            "filename": cp1252_tsv.name,
            "out_delim": "\t",
            "convert_opts": {
                "fields": ["note"],
                "default_mode": "join",
                "sep": " || ",
            },
        },
    ]

    js_results = _run_js_batch(engine_js, cases, td)

    for idx, (c, js_res) in enumerate(zip(cases, js_results)):
        opts = c["convert_opts"]
        py_info = inspect_redcap(c["path"], id_col=c.get("id_col"))
        js_info = js_res["inspect"]
        for key in ("total_rows", "unique_records", "id_col", "events", "repeat_instruments", "max_repeat_instance", "field_count", "fields"):
            assert py_info[key] == js_info[key], f"[{c['name']}] inspect mismatch on {key}: {py_info[key]} != {js_info[key]}"

        py_out_path = td / f"py_out_{idx}.{'tsv' if c.get('out_delim') == '\t' else 'csv'}"
        py_res = convert_redcap(
            input_path=c["path"],
            output_path=py_out_path,
            fields=opts.get("fields"),
            default_mode=opts.get("default_mode", "wide"),
            field_modes=opts.get("field_modes"),
            id_col=opts.get("id_col"),
            include_dag=opts.get("include_dag", True),
            sep=opts.get("sep", "; "),
            tag_instance=opts.get("tag_instance", False),
            filter_events=opts.get("filter_events"),
            filter_instruments=opts.get("filter_instruments"),
        )
        js_conv = js_res["convert"]
        for key in ("input_rows", "output_rows", "unique_records_total", "output_column_count", "output_columns", "resolved_modes"):
            assert py_res[key] == js_conv[key], f"[{c['name']}] convert mismatch on {key}: {py_res[key]} != {js_conv[key]}"

        py_bytes = py_out_path.read_bytes()
        js_bytes = js_res["serialized"].encode("utf-8")
        assert py_bytes == js_bytes, f"[{c['name']}] serialized file bytes differ between Python and JS"


def test_gui_app_routes(td: Path) -> None:
    """In-process route verification (runs cleanly even when sandbox blocks TCP connect)."""
    mixed_csv = td / "app_mixed.csv"
    _write_mixed_csv(mixed_csv)
    shutdown_called = {"flag": False}
    app = RedcapGuiApp(
        HTML_PATH,
        preloaded_input=str(mixed_csv),
        on_shutdown=lambda: shutdown_called.__setitem__("flag", True),
    )
    temp_dir_path = app.temp_dir
    try:
        # 1. GET /
        st, _hdrs, html_bytes = app.handle_get("/")
        assert st == 200
        html_body = html_bytes.decode("utf-8")
        m = re.search(r"window\.__REDCAP_SERVER__\s*=\s*(\{.*?\});", html_body, flags=re.DOTALL)
        assert m, "Boot payload not injected in GET /"
        boot = json.loads(m.group(1).replace("<\\/", "</"))
        assert boot["enabled"] is True
        assert boot["preloaded"]["inspect"]["unique_records"] == 2
        token = boot["token"]

        # 2. GET /api/health
        st, _hdrs, raw = app.handle_get("/api/health")
        health = json.loads(raw.decode("utf-8"))
        assert st == 200 and health["ok"] is True and health["mode"] == "python" and health["preloaded"] is True

        # 3. POST /api/inspect without token -> 403
        st403, _hdrs, _ = app.handle_post("/api/inspect", {}, json.dumps({"input_path": str(mixed_csv)}).encode("utf-8"))
        assert st403 == 403

        # 4. POST /api/upload raw CSV bytes
        st_up, _hdrs, raw_up = app.handle_post(
            "/api/upload",
            {"X-Redcap-Token": token, "X-Filename": "uploaded_study.csv"},
            mixed_csv.read_bytes(),
        )
        assert st_up == 200
        up_res = json.loads(raw_up.decode("utf-8"))
        file_key = up_res["file_key"]
        assert up_res["filename"] == "uploaded_study.csv"
        assert up_res["inspect"]["unique_records"] == 2

        # 5. POST /api/inspect with id_col override
        st_ins, _hdrs, raw_ins = app.handle_post(
            "/api/inspect",
            {"X-Redcap-Token": token},
            json.dumps({"file_key": file_key, "id_col": "alt_id"}).encode("utf-8"),
        )
        assert st_ins == 200
        ins_res = json.loads(raw_ins.decode("utf-8"))
        assert ins_res["inspect"]["id_col"] == "alt_id"

        # 6. POST /api/preview
        st_prev, _hdrs, raw_prev = app.handle_post(
            "/api/preview",
            {"X-Redcap-Token": token},
            json.dumps({"file_key": file_key, "fields": ["med_name"], "default_mode": "wide", "preview_limit": 5}).encode("utf-8"),
        )
        assert st_prev == 200
        prev_res = json.loads(raw_prev.decode("utf-8"))
        assert prev_res["output_columns"] == [
            "study_id",
            "redcap_data_access_group",
            "med_name__baseline_arm_1_medications_i1",
            "med_name__baseline_arm_1_medications_i2",
            "med_name__baseline_arm_1_medications_i3",
            "med_name__baseline_arm_1_medications_i10",
        ]

        # 7. POST /api/convert (download mode) + GET /api/download
        st_conv, _hdrs, raw_conv = app.handle_post(
            "/api/convert",
            {"X-Redcap-Token": token},
            json.dumps({
                "file_key": file_key,
                "fields": ["age", "med_name", "med_dose_mg"],
                "default_mode": "wide",
                "field_modes": {"med_name": "join", "med_dose_mg": "sum"},
                "sep": " | ",
                "download": True,
            }).encode("utf-8"),
        )
        assert st_conv == 200
        conv_res = json.loads(raw_conv.decode("utf-8"))
        assert conv_res["output_rows"] == 2
        dl_id = conv_res["download_id"]

        st_bad_dl, _hdrs, _ = app.handle_get(f"/api/download/{dl_id}?token=wrong")
        assert st_bad_dl == 403

        st_dl, dl_hdrs, dl_bytes = app.handle_get(f"/api/download/{dl_id}?token={token}")
        assert st_dl == 200
        assert "attachment" in dl_hdrs.get("Content-Disposition", "")
        dl_rows = list(csv.DictReader(dl_bytes.decode("utf-8-sig").splitlines()))
        assert len(dl_rows) == 2
        assert dl_rows[0]["med_dose_mg"] == "600"
        assert dl_rows[1]["med_name"] == "Drug1 | Drug2 | Drug10"

        # 8. POST /api/convert direct disk output_path
        disk_out = td / "app_direct_disk.csv"
        st_disk, _hdrs, raw_disk = app.handle_post(
            "/api/convert",
            {"X-Redcap-Token": token},
            json.dumps({
                "input_path": str(mixed_csv),
                "output_path": str(disk_out),
                "fields": ["age", "bp_sys"],
                "field_modes": {"bp_sys": "max"},
                "download": False,
            }).encode("utf-8"),
        )
        assert st_disk == 200 and disk_out.is_file()
        assert json.loads(raw_disk.decode("utf-8"))["output_rows"] == 2

        # 9. POST /api/shutdown
        st_bye, _hdrs, raw_bye = app.handle_post("/api/shutdown", {"X-Redcap-Token": token}, b"{}")
        assert st_bye == 200 and json.loads(raw_bye.decode("utf-8"))["ok"] is True
        assert shutdown_called["flag"] is True
    finally:
        app.cleanup()
    assert not temp_dir_path.exists(), "Temp dir was not cleaned up"


def _http_json(
    opener: urllib.request.OpenerDirector,
    url: str,
    method: str = "GET",
    body: dict | None = None,
    headers: dict | None = None,
) -> tuple[int, dict]:
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers=headers or {})
    if body is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with opener.open(req, timeout=5) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as err:
        return err.code, json.loads(err.read().decode("utf-8"))


def test_live_http_server(td: Path, require_live_socket: bool = False) -> bool:
    mixed_csv = td / "srv_mixed.csv"
    _write_mixed_csv(mixed_csv)
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    proc = subprocess.Popen(
        [sys.executable, "-u", str(SERVER_SCRIPT), "--port", "0", "--no-browser", "--input", str(mixed_csv)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    base_url = None
    try:
        assert proc.stdout is not None
        for _ in range(40):
            line = proc.stdout.readline()
            if not line:
                break
            if line.strip().startswith("REDCAP_GUI_URL="):
                base_url = line.strip().split("=", 1)[1].strip()
                break
        assert base_url, f"Server did not emit REDCAP_GUI_URL. stderr={proc.stderr.read() if proc.stderr else ''}"

        try:
            with opener.open(base_url, timeout=3) as resp:
                assert resp.status == 200
                html_body = resp.read().decode("utf-8")
        except urllib.error.URLError as exc:
            if isinstance(exc.reason, PermissionError) and not require_live_socket:
                print("[SKIP] Live loopback socket probe blocked by sandbox (WinError 10013); in-process route tests passed.")
                return False
            raise

        m = re.search(r"window\.__REDCAP_SERVER__\s*=\s*(\{.*?\});", html_body, flags=re.DOTALL)
        assert m, "Boot payload not injected in GET /"
        boot = json.loads(m.group(1).replace("<\\/", "</"))
        token = boot["token"]

        st, health = _http_json(opener, base_url + "api/health")
        assert st == 200 and health["ok"] is True and health["mode"] == "python"

        st_403, _ = _http_json(opener, base_url + "api/inspect", method="POST", body={"input_path": str(mixed_csv)})
        assert st_403 == 403

        up_req = urllib.request.Request(
            base_url + "api/upload",
            data=mixed_csv.read_bytes(),
            method="POST",
            headers={
                "Content-Type": "application/octet-stream",
                "X-Redcap-Token": token,
                "X-Filename": "uploaded_study.csv",
            },
        )
        with opener.open(up_req, timeout=5) as resp:
            assert resp.status == 200
            up_res = json.loads(resp.read().decode("utf-8"))
        file_key = up_res["file_key"]

        st_conv, conv_res = _http_json(
            opener,
            base_url + "api/convert",
            method="POST",
            headers={"X-Redcap-Token": token},
            body={
                "file_key": file_key,
                "fields": ["age", "med_name", "med_dose_mg"],
                "default_mode": "wide",
                "field_modes": {"med_name": "join", "med_dose_mg": "sum"},
                "sep": " | ",
                "download": True,
            },
        )
        assert st_conv == 200 and conv_res["output_rows"] == 2
        dl_id = conv_res["download_id"]
        with opener.open(base_url + f"api/download/{dl_id}?token={token}", timeout=5) as resp:
            assert resp.status == 200
            dl_rows = list(csv.DictReader(resp.read().decode("utf-8-sig").splitlines()))
        assert len(dl_rows) == 2 and dl_rows[0]["med_dose_mg"] == "600"

        st_bye, bye_res = _http_json(
            opener,
            base_url + "api/shutdown",
            method="POST",
            headers={"X-Redcap-Token": token},
            body={},
        )
        assert st_bye == 200 and bye_res["ok"] is True
        rc = proc.wait(timeout=5)
        assert rc == 0, f"Expected server exit code 0, got {rc}"
        return True
    finally:
        if proc.poll() is None:
            proc.terminate()
            proc.wait(timeout=5)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Run Hybrid GUI offline, JS parity, and HTTP server tests.")
    ap.add_argument("--require-live-socket", action="store_true", help="Fail instead of skipping if loopback connect is blocked.")
    args = ap.parse_args(argv)

    assert len(VALID_MODES) == 11
    test_offline_safety()
    with tempfile.TemporaryDirectory() as tmp:
        td = Path(tmp)
        test_python_vs_js_parity(td)
        test_gui_app_routes(td)
        live_ran = test_live_http_server(td, require_live_socket=args.require_live_socket)
    mode_msg = "live loopback HTTP" if live_ran else "in-process HTTP routes"
    print(f"ALL HYBRID GUI TESTS PASSED (offline audit + 11-mode Python-vs-JS parity + {mode_msg})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
