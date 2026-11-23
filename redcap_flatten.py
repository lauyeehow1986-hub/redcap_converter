#!/usr/bin/env python3
"""Compact, zero-dependency REDCap Repeating Instruments & Events Single-Line Converter.

Works on any REDCap CSV/TSV export (classic or longitudinal, raw or labeled headers).
Requires only Python 3 standard library - no pip install, no PowerShell, no admin rights.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import statistics
import sys
from collections import OrderedDict
from pathlib import Path
from typing import Any

# Allow large clinical narrative cells without hitting Python's 131 KB CSV field default
_csv_limit = min(sys.maxsize, 2**31 - 1)
while _csv_limit > 131072:
    try:
        csv.field_size_limit(_csv_limit)
        break
    except OverflowError:
        _csv_limit //= 2

# Raw and labeled REDCap system column aliases (lowercased for matching)
SYS_EVENT_COLS = {"redcap_event_name", "event name"}
SYS_INST_NAME_COLS = {"redcap_repeat_instrument", "repeat instrument"}
SYS_INST_NUM_COLS = {"redcap_repeat_instance", "repeat instance"}
SYS_DAG_COLS = {"redcap_data_access_group", "data access group"}
SYS_SURVEY_COLS = {"redcap_survey_identifier", "survey identifier"}

VALID_MODES = {"auto", "wide", "join", "unique", "first", "last", "count", "min", "max", "sum", "mean"}


def _open_text(path: str | Path):
    """Open CSV/TSV handling UTF-8 BOM and common Windows encodings."""
    for enc in ("utf-8-sig", "utf-8", "cp1252", "latin-1"):
        try:
            with open(path, "r", encoding=enc, newline="") as fh:
                while fh.read(65536):
                    pass
            return open(path, "r", encoding=enc, newline="")
        except UnicodeDecodeError:
            continue
    return open(path, "r", encoding="latin-1", newline="")


def _detect_delimiter(path: str | Path) -> str:
    with _open_text(path) as fh:
        sample = fh.read(8192)
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",\t;")
        return dialect.delimiter
    except csv.Error:
        return "\t" if str(path).lower().endswith(".tsv") else ","


def _read_rows(path: str | Path, delimiter: str | None = None) -> tuple[list[str], list[dict[str, str]], str]:
    delim = delimiter or _detect_delimiter(path)
    with _open_text(path) as fh:
        reader = csv.DictReader(fh, delimiter=delim)
        if not reader.fieldnames:
            raise ValueError(f"No header row found in {path}")
        headers = [h.strip() if h else "" for h in reader.fieldnames]
        reader.fieldnames = headers
        rows = [{k: (v if v is not None else "") for k, v in row.items()} for row in reader]
    return headers, rows, delim


def _find_col(headers: list[str], aliases: set[str]) -> str | None:
    for h in headers:
        if h.strip().lower() in aliases:
            return h
    return None


def _parse_int_safe(val: str) -> tuple[int, str]:
    s = val.strip()
    if s.isdigit():
        return (0, f"{int(s):09d}")
    return (1, s)


def _slug(text: str) -> str:
    s = re.sub(r"[^A-Za-z0-9]+", "_", text.strip()).strip("_")
    return s or "x"


def inspect_redcap(path: str | Path, id_col: str | None = None, delimiter: str | None = None) -> dict[str, Any]:
    """Inspect any REDCap CSV/TSV export and classify every field."""
    headers, rows, delim = _read_rows(path, delimiter)
    rec_col = id_col if (id_col and id_col in headers) else headers[0]
    event_col = _find_col(headers, SYS_EVENT_COLS)
    inst_name_col = _find_col(headers, SYS_INST_NAME_COLS)
    inst_num_col = _find_col(headers, SYS_INST_NUM_COLS)
    dag_col = _find_col(headers, SYS_DAG_COLS)
    survey_col = _find_col(headers, SYS_SURVEY_COLS)

    sys_cols = {c for c in (rec_col, event_col, inst_name_col, inst_num_col, dag_col, survey_col) if c}
    data_fields = [h for h in headers if h and h not in sys_cols]

    records: set[str] = set()
    events: list[str] = []
    events_seen: set[str] = set()
    repeat_instruments: list[str] = []
    rep_inst_seen: set[str] = set()
    max_instance = 0

    # Per-field provenance tracking
    field_stats: dict[str, dict[str, Any]] = {
        f: {
            "non_empty": 0,
            "in_static": False,
            "in_rep_instrument": set(),
            "in_rep_event": False,
            "events": set(),
            "max_per_record": 0,
            "_rec_counts": {},
        }
        for f in data_fields
    }

    for row in rows:
        rid = row.get(rec_col, "").strip()
        if not rid:
            continue
        records.add(rid)
        ev = row.get(event_col, "").strip() if event_col else ""
        ri = row.get(inst_name_col, "").strip() if inst_name_col else ""
        rn = row.get(inst_num_col, "").strip() if inst_num_col else ""

        if ev and ev not in events_seen:
            events_seen.add(ev)
            events.append(ev)
        if ri and ri not in rep_inst_seen:
            rep_inst_seen.add(ri)
            repeat_instruments.append(ri)
        if rn.isdigit():
            max_instance = max(max_instance, int(rn))

        is_rep_inst = bool(ri)
        is_rep_evt = bool(rn) and not is_rep_inst

        for f in data_fields:
            val = row.get(f, "").strip()
            if val != "":
                st = field_stats[f]
                st["non_empty"] += 1
                if ev:
                    st["events"].add(ev)
                if is_rep_inst:
                    st["in_rep_instrument"].add(ri)
                elif is_rep_evt:
                    st["in_rep_event"] = True
                else:
                    st["in_static"] = True
                rc = st["_rec_counts"]
                rc[rid] = rc.get(rid, 0) + 1
                if rc[rid] > st["max_per_record"]:
                    st["max_per_record"] = rc[rid]

    fields_out = []
    for idx, f in enumerate(data_fields, 1):
        st = field_stats[f]
        if st["in_rep_instrument"]:
            kind = "repeating_instrument"
        elif st["in_rep_event"]:
            kind = "repeating_event"
        elif len(st["events"]) > 1 or st["max_per_record"] > 1:
            kind = "longitudinal"
        else:
            kind = "static"
        fields_out.append(
            {
                "index": idx,
                "name": f,
                "kind": kind,
                "non_empty": st["non_empty"],
                "max_per_record": st["max_per_record"],
                "instruments": sorted(st["in_rep_instrument"]),
                "events": sorted(st["events"]),
            }
        )

    return {
        "file": str(path),
        "delimiter": delim,
        "total_rows": len(rows),
        "unique_records": len(records),
        "id_col": rec_col,
        "system_columns": {
            "event": event_col,
            "repeat_instrument": inst_name_col,
            "repeat_instance": inst_num_col,
            "dag": dag_col,
            "survey_identifier": survey_col,
        },
        "events": events,
        "repeat_instruments": repeat_instruments,
        "max_repeat_instance": max_instance,
        "field_count": len(fields_out),
        "fields": fields_out,
    }


def _build_slot_key(ev: str, ri: str, rn: str, has_multi_events: bool) -> str:
    parts = []
    if ev and has_multi_events:
        parts.append(_slug(ev))
    if ri:
        parts.append(_slug(ri))
    if rn:
        parts.append(f"i{rn}")
    return "_".join(parts) if parts else "base"


def _aggregate_values(
    items: list[tuple[str, str]],
    mode: str,
    sep: str,
    tag_instance: bool,
) -> str:
    """Collapse [(slot_label, value), ...] into a single string."""
    if not items:
        return ""
    vals = [v for _, v in items]
    if mode == "first":
        return vals[0]
    if mode == "last":
        return vals[-1]
    if mode == "count":
        return str(len(vals))
    if mode == "unique":
        seen: list[str] = []
        seen_set: set[str] = set()
        for slot, v in items:
            if v not in seen_set:
                seen_set.add(v)
                seen.append(f"[{slot}] {v}" if (tag_instance and slot != "base") else v)
        return sep.join(seen)
    if mode == "join":
        if tag_instance:
            return sep.join(f"[{slot}] {v}" if slot != "base" else v for slot, v in items)
        return sep.join(vals)
    if mode in ("min", "max", "sum", "mean"):
        nums = []
        for v in vals:
            try:
                nums.append(float(v))
            except ValueError:
                pass
        if not nums:
            return ""
        if mode == "min":
            res = min(nums)
        elif mode == "max":
            res = max(nums)
        elif mode == "sum":
            res = sum(nums)
        else:
            res = statistics.fmean(nums)
        return f"{int(res)}" if res.is_integer() and mode != "mean" else f"{res:.4g}"
    return sep.join(vals)


def convert_redcap(
    input_path: str | Path,
    output_path: str | Path | None = None,
    fields: list[str] | None = None,
    default_mode: str = "wide",
    field_modes: dict[str, str] | None = None,
    id_col: str | None = None,
    include_dag: bool = True,
    sep: str = "; ",
    tag_instance: bool = False,
    filter_events: list[str] | None = None,
    filter_instruments: list[str] | None = None,
    delimiter: str | None = None,
    preview_limit: int | None = None,
) -> dict[str, Any]:
    """Flatten a multi-line REDCap export into one line per record."""
    if default_mode not in VALID_MODES:
        raise ValueError(f"Invalid default_mode '{default_mode}'. Choose from {sorted(VALID_MODES)}")

    headers, rows, delim = _read_rows(input_path, delimiter)
    rec_col = id_col if (id_col and id_col in headers) else headers[0]
    event_col = _find_col(headers, SYS_EVENT_COLS)
    inst_name_col = _find_col(headers, SYS_INST_NAME_COLS)
    inst_num_col = _find_col(headers, SYS_INST_NUM_COLS)
    dag_col = _find_col(headers, SYS_DAG_COLS)
    survey_col = _find_col(headers, SYS_SURVEY_COLS)

    sys_cols = {c for c in (rec_col, event_col, inst_name_col, inst_num_col, dag_col, survey_col) if c}

    # Resolve selected fields (supports wildcards like symptoms___*)
    if not fields:
        selected = [h for h in headers if h and h not in sys_cols]
    else:
        selected = []
        for pattern in fields:
            if "*" in pattern:
                rx = re.compile("^" + re.escape(pattern).replace(r"\*", ".*") + "$")
                for h in headers:
                    if h not in sys_cols and rx.match(h) and h not in selected:
                        selected.append(h)
            elif pattern in headers and pattern != rec_col and pattern not in selected:
                selected.append(pattern)

    if not selected:
        raise ValueError("No valid fields selected for conversion.")

    fmodes = dict(field_modes or {})
    for k, v in fmodes.items():
        if v not in VALID_MODES:
            raise ValueError(f"Invalid mode '{v}' for field '{k}'.")

    ev_filter = {e.strip().lower() for e in filter_events} if filter_events else None
    inst_filter = {i.strip().lower() for i in filter_instruments} if filter_instruments else None

    # Track order of records and events
    record_order: list[str] = []
    record_seen: set[str] = set()
    event_order: dict[str, int] = {}
    all_events: set[str] = set()

    for row in rows:
        rid = row.get(rec_col, "").strip()
        if not rid:
            continue
        if rid not in record_seen:
            record_seen.add(rid)
            record_order.append(rid)
        if event_col:
            ev = row.get(event_col, "").strip()
            if ev:
                all_events.add(ev)
                if ev not in event_order:
                    event_order[ev] = len(event_order)

    has_multi_events = len(all_events) > 1
    if preview_limit is not None and preview_limit > 0:
        target_records = record_order[:preview_limit]
        target_set = set(target_records)
    else:
        target_records = record_order
        target_set = record_seen

    # Collect per-record values
    dag_map: dict[str, str] = {}
    # rec_data[rid][field] -> list of (sort_key, slot_key, value)
    rec_data: dict[str, dict[str, list[tuple[tuple, str, str]]]] = {
        rid: {f: [] for f in selected} for rid in target_records
    }
    # Track max values per record and all observed slots per field
    field_max_count: dict[str, int] = {f: 0 for f in selected}
    field_slots: dict[str, dict[str, tuple]] = {f: {} for f in selected}

    for row_idx, row in enumerate(rows):
        rid = row.get(rec_col, "").strip()
        if rid not in target_set:
            continue
        if dag_col and rid not in dag_map:
            dv = row.get(dag_col, "").strip()
            if dv:
                dag_map[rid] = dv

        ev = row.get(event_col, "").strip() if event_col else ""
        ri = row.get(inst_name_col, "").strip() if inst_name_col else ""
        rn = row.get(inst_num_col, "").strip() if inst_num_col else ""

        if ev_filter is not None and ev.lower() not in ev_filter:
            continue
        if inst_filter is not None and ri.lower() not in inst_filter:
            continue

        slot = _build_slot_key(ev, ri, rn, has_multi_events)
        skey = (event_order.get(ev, 999999), ri, _parse_int_safe(rn), row_idx)

        for f in selected:
            val = row.get(f, "").strip()
            if val != "":
                lst = rec_data[rid][f]
                lst.append((skey, slot, val))
                if len(lst) > field_max_count[f]:
                    field_max_count[f] = len(lst)
                if slot not in field_slots[f] or skey < field_slots[f][slot]:
                    field_slots[f][slot] = skey

    # Build output schema
    out_headers: list[str] = [rec_col]
    if include_dag and dag_col and dag_map:
        out_headers.append(dag_col)

    resolved_modes: dict[str, str] = {}
    wide_cols_map: dict[str, list[tuple[str, str]]] = {}  # field -> [(slot, col_name)]

    for f in selected:
        m = fmodes.get(f, default_mode)
        is_multi = field_max_count[f] > 1 or len(field_slots[f]) > 1
        if m == "auto":
            m = "wide" if is_multi else "first"
        resolved_modes[f] = m

        if m == "wide" and is_multi:
            ordered_slots = sorted(field_slots[f].keys(), key=lambda s: field_slots[f][s])
            pairs = []
            for s in ordered_slots:
                col_name = f"{f}__{s}" if s != "base" else f
                pairs.append((s, col_name))
                out_headers.append(col_name)
            wide_cols_map[f] = pairs
        else:
            out_headers.append(f)

    # Assemble single-line rows
    out_rows: list[dict[str, str]] = []
    for rid in target_records:
        out_row: dict[str, str] = OrderedDict()
        out_row[rec_col] = rid
        if include_dag and dag_col and dag_map:
            out_row[dag_col] = dag_map.get(rid, "")

        for f in selected:
            items_raw = sorted(rec_data[rid][f], key=lambda x: x[0])
            m = resolved_modes[f]
            if m == "wide" and f in wide_cols_map:
                slot_vals: dict[str, list[str]] = {}
                for _, slot, val in items_raw:
                    slot_vals.setdefault(slot, []).append(val)
                for slot, col_name in wide_cols_map[f]:
                    out_row[col_name] = sep.join(slot_vals.get(slot, []))
            else:
                out_row[f] = _aggregate_values(
                    [(slot, val) for _, slot, val in items_raw],
                    mode="first" if m == "wide" else m,
                    sep=sep,
                    tag_instance=tag_instance,
                )
        out_rows.append(out_row)

    written_path = None
    if output_path is not None:
        out_p = Path(output_path)
        out_p.parent.mkdir(parents=True, exist_ok=True)
        out_delim = "\t" if str(out_p).lower().endswith(".tsv") else ","
        with open(out_p, "w", encoding="utf-8-sig", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=out_headers, delimiter=out_delim)
            writer.writeheader()
            writer.writerows(out_rows)
        written_path = str(out_p.resolve())

    return {
        "input_file": str(input_path),
        "output_file": written_path,
        "input_rows": len(rows),
        "output_rows": len(out_rows),
        "unique_records_total": len(record_order),
        "output_column_count": len(out_headers),
        "output_columns": out_headers,
        "resolved_modes": resolved_modes,
        "preview_rows": out_rows[:10] if preview_limit is not None else out_rows[:3],
    }


def _parse_selection(expr: str, fields_meta: list[dict[str, Any]]) -> tuple[list[str], dict[str, str]]:
    """Parse interactive picker expressions like '1-4, 7:join, 9:wide' or 'all' or 'rep'."""
    by_idx = {f["index"]: f["name"] for f in fields_meta}
    by_name = {f["name"]: f["name"] for f in fields_meta}
    selected: list[str] = []
    overrides: dict[str, str] = {}

    tokens = [t.strip() for t in re.split(r"[,\s]+", expr.strip()) if t.strip()]
    for tok in tokens:
        mode = None
        if ":" in tok:
            tok, mode = tok.split(":", 1)
            mode = mode.strip().lower()
            if mode not in VALID_MODES:
                print(f"  [!] Ignoring unknown mode '{mode}' (valid: {', '.join(sorted(VALID_MODES))})")
                mode = None
        low = tok.lower()
        matched: list[str] = []
        if low == "all":
            matched = [f["name"] for f in fields_meta]
        elif low == "rep":
            matched = [f["name"] for f in fields_meta if f["kind"] != "static"]
        elif low == "static":
            matched = [f["name"] for f in fields_meta if f["kind"] == "static"]
        elif re.match(r"^\d+-\d+$", tok):
            a, b = (int(x) for x in tok.split("-"))
            for i in range(min(a, b), max(a, b) + 1):
                if i in by_idx:
                    matched.append(by_idx[i])
        elif tok.isdigit() and int(tok) in by_idx:
            matched = [by_idx[int(tok)]]
        elif "*" in tok:
            rx = re.compile("^" + re.escape(tok).replace(r"\*", ".*") + "$")
            matched = [f["name"] for f in fields_meta if rx.match(f["name"])]
        elif tok in by_name:
            matched = [tok]
        else:
            print(f"  [!] Unrecognized token: {tok}")
        for name in matched:
            if name not in selected:
                selected.append(name)
            if mode:
                overrides[name] = mode
    return selected, overrides


def run_interactive(input_path: str) -> int:
    """Compact Command Prompt interactive field picker."""
    info = inspect_redcap(input_path)
    print("=" * 68)
    print(f" REDCap Single-Line Converter | {Path(input_path).name}")
    print(f" Rows: {info['total_rows']} -> Unique Records: {info['unique_records']} (ID: {info['id_col']})")
    if info["events"]:
        print(f" Events ({len(info['events'])}): {', '.join(info['events'][:6])}")
    if info["repeat_instruments"]:
        print(f" Repeating Instruments: {', '.join(info['repeat_instruments'])}")
    print("=" * 68)

    fields_meta = info["fields"]
    tag_map = {
        "static": "STATIC",
        "repeating_instrument": "REP-INST",
        "repeating_event": "REP-EVT",
        "longitudinal": "LONG",
    }
    for f in fields_meta:
        tag = tag_map.get(f["kind"], f["kind"])
        extra = f" [{','.join(f['instruments'])}]" if f["instruments"] else ""
        print(f" {f['index']:>3}. {f['name']:<32} [{tag:<8}] n={f['non_empty']} max/rec={f['max_per_record']}{extra}")

    print("-" * 68)
    print(" Select fields by number/range/name (e.g. 1-3, 5:join, 8:wide) or 'all' / 'rep'.")
    print(" Modes: wide | join | unique | first | last | count | min | max | sum | mean")
    expr = input(" Fields [all]: ").strip() or "all"
    selected, overrides = _parse_selection(expr, fields_meta)
    if not selected:
        print("No fields selected. Exiting.")
        return 1

    default_mode = input(" Default collapse mode for multi-line fields [wide/join/unique/first/last] (default: wide): ").strip().lower() or "wide"
    if default_mode not in VALID_MODES:
        default_mode = "wide"

    sep = "; "
    tag_inst = False
    if default_mode in ("join", "unique") or any(v in ("join", "unique") for v in overrides.values()):
        sep = input(" Join separator [; ]: ") or "; "
        tag_inst = input(" Prefix values with [event_i#]? [y/N]: ").strip().lower() == "y"

    default_out = str(Path(input_path).with_name(Path(input_path).stem + "_singleline.csv"))
    out_path = input(f" Output CSV [{default_out}]: ").strip() or default_out

    res = convert_redcap(
        input_path=input_path,
        output_path=out_path,
        fields=selected,
        default_mode=default_mode,
        field_modes=overrides,
        sep=sep,
        tag_instance=tag_inst,
    )
    print("-" * 68)
    print(f" DONE! {res['input_rows']} rows -> {res['output_rows']} single-line records ({res['output_column_count']} columns)")
    print(f" Saved: {res['output_file']}")

    save_prof = input(" Save field selection as reusable JSON profile? [y/N]: ").strip().lower()
    if save_prof == "y":
        prof_path = str(Path(out_path).with_suffix(".profile.json"))
        profile = {
            "fields": selected,
            "default_mode": default_mode,
            "field_modes": overrides,
            "sep": sep,
            "tag_instance": tag_inst,
        }
        Path(prof_path).write_text(json.dumps(profile, indent=2), encoding="utf-8")
        print(f" Profile saved: {prof_path}")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Convert multi-line REDCap repeating exports into a single line per record.")
    ap.add_argument("input", nargs="?", help="Input REDCap CSV/TSV file")
    ap.add_argument("-o", "--output", help="Output single-line CSV/TSV path")
    ap.add_argument("-f", "--fields", help="Comma-separated fields (supports * wildcards and field:mode overrides)")
    ap.add_argument("-m", "--mode", default="wide", choices=sorted(VALID_MODES), help="Default collapse mode (default: wide)")
    ap.add_argument("--id-col", help="Override record ID column name (default: column 1)")
    ap.add_argument("--sep", default="; ", help="Join separator (default: '; ')")
    ap.add_argument("--tag-instance", action="store_true", help="Prefix joined values with [slot]")
    ap.add_argument("--events", help="Comma-separated event names to include")
    ap.add_argument("--instruments", help="Comma-separated repeat instruments to include")
    ap.add_argument("--profile", help="Load field selection & modes from a JSON profile")
    ap.add_argument("--inspect", action="store_true", help="Print JSON schema inspection and exit")
    ap.add_argument("-i", "--interactive", action="store_true", help="Launch interactive CMD field picker")
    args = ap.parse_args(argv)

    if not args.input:
        inp = input("Enter or drag-and-drop REDCap CSV path: ").strip().strip('"')
        if not inp:
            return 1
        return run_interactive(inp)

    if args.inspect:
        print(json.dumps(inspect_redcap(args.input, id_col=args.id_col), indent=2))
        return 0

    if args.interactive or (not args.output and not args.fields and not args.profile):
        return run_interactive(args.input)

    fields_list = None
    field_modes: dict[str, str] = {}
    default_mode = args.mode
    sep = args.sep
    tag_inst = args.tag_instance

    if args.profile:
        prof = json.loads(Path(args.profile).read_text(encoding="utf-8"))
        fields_list = prof.get("fields")
        default_mode = prof.get("default_mode", default_mode)
        field_modes.update(prof.get("field_modes", {}))
        sep = prof.get("sep", sep)
        tag_inst = prof.get("tag_instance", tag_inst)

    if args.fields:
        fields_list = []
        for item in args.fields.split(","):
            item = item.strip()
            if not item:
                continue
            if ":" in item:
                fname, fmode = item.split(":", 1)
                fname, fmode = fname.strip(), fmode.strip().lower()
                fields_list.append(fname)
                field_modes[fname] = fmode
            else:
                fields_list.append(item)

    out_path = args.output or str(Path(args.input).with_name(Path(args.input).stem + "_singleline.csv"))
    res = convert_redcap(
        input_path=args.input,
        output_path=out_path,
        fields=fields_list,
        default_mode=default_mode,
        field_modes=field_modes,
        id_col=args.id_col,
        sep=sep,
        tag_instance=tag_inst,
        filter_events=[e.strip() for e in args.events.split(",")] if args.events else None,
        filter_instruments=[i.strip() for i in args.instruments.split(",")] if args.instruments else None,
    )
    print(json.dumps(res, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
