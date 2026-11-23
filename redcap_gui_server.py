#!/usr/bin/env python3
"""Zero-dependency local HTTP GUI server for REDCap Single-Line Conversion.

Serves redcap_converter.html on loopback (127.0.0.1) only and delegates all
CSV/TSV inspection, preview, and conversion directly to redcap_flatten.py.
Requires only Python 3 standard library - no pip install, no tkinter, no PowerShell.
"""

from __future__ import annotations

import argparse
import atexit
import json
import platform
import secrets
import shutil
import sys
import tempfile
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable
from urllib.parse import parse_qs, unquote, urlparse

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from redcap_flatten import VALID_MODES, convert_redcap, inspect_redcap  # noqa: E402


def _locate_html_path() -> Path:
    candidates = [
        SCRIPT_DIR / "redcap_converter.html",
        SCRIPT_DIR.parent / "assets" / "redcap_converter.html",
    ]
    for cand in candidates:
        if cand.is_file():
            return cand
    raise FileNotFoundError(
        f"redcap_converter.html not found in {[str(c) for c in candidates]}"
    )


def _safe_filename(name: str, fallback: str = "redcap_export.csv") -> str:
    cleaned = Path(name).name.replace('"', "").replace("\r", "").replace("\n", "").strip()
    return cleaned or fallback


def _get_header(headers: dict[str, str], target: str, default: str = "") -> str:
    low = target.lower()
    for k, v in headers.items():
        if k.lower() == low:
            return v
    return default


class RedcapGuiApp:
    """Pure in-process request router and state manager for the Hybrid GUI."""

    def __init__(
        self,
        html_path: Path,
        preloaded_input: str | None = None,
        on_shutdown: Callable[[], None] | None = None,
    ) -> None:
        self.html_path = html_path
        self.on_shutdown = on_shutdown
        self.token = secrets.token_urlsafe(24)
        self.temp_dir = Path(tempfile.mkdtemp(prefix="redcap_gui_"))
        self.lock = threading.Lock()
        self.uploaded_files: dict[str, dict[str, Any]] = {}
        self.downloads: dict[str, dict[str, Any]] = {}
        self.preloaded: dict[str, Any] | None = None

        if preloaded_input:
            p = Path(preloaded_input).resolve()
            if not p.is_file():
                raise FileNotFoundError(f"Preloaded input file not found: {p}")
            info = inspect_redcap(p)
            self.preloaded = {
                "file_key": None,
                "filename": p.name,
                "source": "path",
                "input_path": str(p),
                "inspect": info,
            }

    def cleanup(self) -> None:
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def resolve_input(self, payload: dict[str, Any]) -> tuple[Path, str, str | None, str | None]:
        file_key = payload.get("file_key")
        input_path = payload.get("input_path")
        if file_key:
            with self.lock:
                entry = self.uploaded_files.get(str(file_key))
            if not entry:
                raise FileNotFoundError("Uploaded file session expired or not found.")
            return Path(entry["path"]), str(entry["filename"]), str(file_key), None
        if input_path:
            p = Path(str(input_path)).expanduser().resolve()
            if not p.is_file():
                raise FileNotFoundError(f"Input file not found: {p}")
            return p, p.name, None, str(p)
        raise ValueError("Missing file_key or input_path.")

    def _response(
        self,
        status: int,
        body: bytes,
        content_type: str,
        extra_headers: dict[str, str] | None = None,
    ) -> tuple[int, dict[str, str], bytes]:
        headers = {
            "Content-Type": content_type,
            "Content-Length": str(len(body)),
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
            "Connection": "close",
        }
        if extra_headers:
            headers.update(extra_headers)
        return status, headers, body

    def _json_response(self, status: int, data: dict[str, Any]) -> tuple[int, dict[str, str], bytes]:
        raw = json.dumps(data).encode("utf-8")
        return self._response(status, raw, "application/json; charset=utf-8")

    def _require_post_token(self, headers: dict[str, str]) -> bool:
        got = _get_header(headers, "X-Redcap-Token", "")
        return bool(got) and secrets.compare_digest(got, self.token)

    def handle_get(self, raw_path: str) -> tuple[int, dict[str, str], bytes]:
        try:
            parsed = urlparse(raw_path)
            if parsed.path == "/":
                html_text = self.html_path.read_text(encoding="utf-8")
                boot_payload = {
                    "enabled": True,
                    "token": self.token,
                    "python_version": platform.python_version(),
                    "preloaded": self.preloaded,
                }
                boot_js = (
                    "window.__REDCAP_SERVER__ = "
                    + json.dumps(boot_payload).replace("</", "<\\/")
                    + ";"
                )
                marker = "window.__REDCAP_SERVER__ = null;"
                if marker not in html_text:
                    raise RuntimeError("Boot marker missing in redcap_converter.html")
                rendered = html_text.replace(marker, boot_js, 1)
                return self._response(200, rendered.encode("utf-8"), "text/html; charset=utf-8")

            if parsed.path == "/api/health":
                return self._json_response(
                    200,
                    {
                        "ok": True,
                        "mode": "python",
                        "python_version": platform.python_version(),
                        "preloaded": self.preloaded is not None,
                    },
                )

            if parsed.path.startswith("/api/download/"):
                qs = parse_qs(parsed.query)
                tok = (qs.get("token") or [""])[0]
                if not tok or not secrets.compare_digest(tok, self.token):
                    return self._json_response(403, {"error": "Invalid or missing download token."})
                dl_id = unquote(parsed.path[len("/api/download/") :]).strip("/")
                with self.lock:
                    entry = self.downloads.get(dl_id)
                if not entry or not Path(entry["path"]).is_file():
                    return self._json_response(404, {"error": "Download not found or expired."})
                raw = Path(entry["path"]).read_bytes()
                dl_name = _safe_filename(str(entry["filename"]), "redcap_singleline.csv")
                ctype = (
                    "text/tab-separated-values; charset=utf-8"
                    if dl_name.lower().endswith(".tsv")
                    else "text/csv; charset=utf-8"
                )
                return self._response(
                    200,
                    raw,
                    ctype,
                    {"Content-Disposition": f'attachment; filename="{dl_name}"'},
                )

            return self._json_response(404, {"error": f"Not found: {parsed.path}"})
        except Exception as exc:
            return self._json_response(500, {"error": str(exc)})

    def handle_post(
        self, raw_path: str, headers: dict[str, str], body_bytes: bytes
    ) -> tuple[int, dict[str, str], bytes]:
        try:
            if not self._require_post_token(headers):
                return self._json_response(403, {"error": "Invalid or missing security token."})

            parsed = urlparse(raw_path)

            if parsed.path == "/api/upload":
                raw_name = unquote(_get_header(headers, "X-Filename", "redcap_export.csv"))
                fname = _safe_filename(raw_name, "redcap_export.csv")
                if not body_bytes:
                    return self._json_response(400, {"error": "Uploaded file is empty."})
                fkey = secrets.token_urlsafe(12)
                dest = self.temp_dir / f"upload_{fkey}_{fname}"
                dest.write_bytes(body_bytes)
                info = inspect_redcap(dest)
                with self.lock:
                    self.uploaded_files[fkey] = {"path": str(dest), "filename": fname}
                return self._json_response(
                    200,
                    {
                        "file_key": fkey,
                        "filename": fname,
                        "source": "upload",
                        "input_path": None,
                        "inspect": info,
                    },
                )

            if body_bytes:
                body = json.loads(body_bytes.decode("utf-8"))
                if not isinstance(body, dict):
                    raise ValueError("Expected JSON object body.")
            else:
                body = {}

            if parsed.path == "/api/inspect":
                target, fname, fkey, resolved_input = self.resolve_input(body)
                info = inspect_redcap(target, id_col=body.get("id_col") or None)
                return self._json_response(
                    200,
                    {
                        "file_key": fkey,
                        "filename": fname,
                        "source": "upload" if fkey else "path",
                        "input_path": resolved_input,
                        "inspect": info,
                    },
                )

            if parsed.path == "/api/preview":
                target, _fname, _fkey, _resolved = self.resolve_input(body)
                default_mode = str(body.get("default_mode") or "wide")
                if default_mode not in VALID_MODES:
                    raise ValueError(f"Invalid default_mode '{default_mode}'")
                res = convert_redcap(
                    input_path=target,
                    output_path=None,
                    fields=body.get("fields"),
                    default_mode=default_mode,
                    field_modes=body.get("field_modes"),
                    id_col=body.get("id_col") or None,
                    include_dag=bool(body.get("include_dag", True)),
                    sep=str(body["sep"]) if "sep" in body and body["sep"] is not None else "; ",
                    tag_instance=bool(body.get("tag_instance", False)),
                    filter_events=body.get("filter_events") or None,
                    filter_instruments=body.get("filter_instruments") or None,
                    preview_limit=int(body.get("preview_limit", 5)),
                )
                return self._json_response(200, res)

            if parsed.path == "/api/convert":
                target, fname, _fkey, _resolved = self.resolve_input(body)
                default_mode = str(body.get("default_mode") or "wide")
                if default_mode not in VALID_MODES:
                    raise ValueError(f"Invalid default_mode '{default_mode}'")
                fmt = str(body.get("format") or "csv").lower()
                raw_out_path = str(body.get("output_path") or "").strip()
                wants_download = bool(body.get("download", not bool(raw_out_path)))

                if raw_out_path and not wants_download:
                    out_path = Path(raw_out_path).expanduser().resolve()
                    dl_id = None
                    dl_name = out_path.name
                else:
                    ext = ".tsv" if fmt == "tsv" else ".csv"
                    stem = Path(fname).stem or "redcap_export"
                    dl_name = f"{stem}_singleline{ext}"
                    dl_id = secrets.token_urlsafe(12)
                    out_path = self.temp_dir / f"out_{dl_id}_{dl_name}"

                res = convert_redcap(
                    input_path=target,
                    output_path=out_path,
                    fields=body.get("fields"),
                    default_mode=default_mode,
                    field_modes=body.get("field_modes"),
                    id_col=body.get("id_col") or None,
                    include_dag=bool(body.get("include_dag", True)),
                    sep=str(body["sep"]) if "sep" in body and body["sep"] is not None else "; ",
                    tag_instance=bool(body.get("tag_instance", False)),
                    filter_events=body.get("filter_events") or None,
                    filter_instruments=body.get("filter_instruments") or None,
                )
                if dl_id:
                    with self.lock:
                        self.downloads[dl_id] = {"path": str(out_path), "filename": dl_name}
                    res["download_id"] = dl_id
                    res["download_filename"] = dl_name
                    res["output_file"] = None
                return self._json_response(200, res)

            if parsed.path == "/api/shutdown":
                if self.on_shutdown is not None:
                    self.on_shutdown()
                return self._json_response(200, {"ok": True})

            return self._json_response(404, {"error": f"Not found: {parsed.path}"})
        except FileNotFoundError as exc:
            return self._json_response(404, {"error": str(exc)})
        except (ValueError, json.JSONDecodeError, UnicodeDecodeError) as exc:
            return self._json_response(400, {"error": str(exc)})
        except Exception as exc:
            return self._json_response(500, {"error": str(exc)})


class _LocalHttpServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def create_server(
    port: int = 0,
    preloaded_input: str | None = None,
    html_path: Path | None = None,
) -> tuple[ThreadingHTTPServer, RedcapGuiApp, str]:
    resolved_html = html_path or _locate_html_path()
    holder: dict[str, _LocalHttpServer] = {}

    def _trigger_shutdown() -> None:
        srv = holder.get("server")
        if srv is not None:
            threading.Thread(target=srv.shutdown, daemon=True).start()

    app = RedcapGuiApp(
        resolved_html,
        preloaded_input=preloaded_input,
        on_shutdown=_trigger_shutdown,
    )

    class RedcapGuiHandler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
            return

        def _send_tuple(self, resp: tuple[int, dict[str, str], bytes]) -> None:
            status, headers, body = resp
            self.close_connection = True
            self.send_response(status)
            for k, v in headers.items():
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:  # noqa: N802
            try:
                self._send_tuple(app.handle_get(self.path))
            except (BrokenPipeError, ConnectionAbortedError, ConnectionResetError):
                return

        def do_POST(self) -> None:  # noqa: N802
            try:
                raw_len = self.headers.get("Content-Length", "0")
                try:
                    length = int(raw_len)
                except ValueError:
                    self._send_tuple(app._json_response(400, {"error": "Invalid Content-Length header."}))
                    return
                if length < 0:
                    self._send_tuple(app._json_response(400, {"error": "Negative Content-Length."}))
                    return
                body_bytes = self.rfile.read(length) if length > 0 else b""
                req_headers = {k: v for k, v in self.headers.items()}
                self._send_tuple(app.handle_post(self.path, req_headers, body_bytes))
            except (BrokenPipeError, ConnectionAbortedError, ConnectionResetError):
                return

    server = _LocalHttpServer(("127.0.0.1", port), RedcapGuiHandler)
    holder["server"] = server
    actual_port = server.server_address[1]
    url = f"http://127.0.0.1:{actual_port}/"
    return server, app, url


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Launch the portable local browser GUI server for REDCap Single-Line Conversion."
    )
    ap.add_argument("--input", "-i", help="Optional REDCap CSV/TSV file to preload in the GUI")
    ap.add_argument("--port", "-p", type=int, default=0, help="Loopback TCP port (default: 0 = auto)")
    ap.add_argument("--no-browser", action="store_true", help="Do not auto-open the web browser")
    args = ap.parse_args(argv)

    server, app, url = create_server(port=args.port, preloaded_input=args.input)
    atexit.register(app.cleanup)

    print("=" * 64, flush=True)
    print(" REDCap Single-Line Converter - Local Python GUI Server", flush=True)
    print(f" REDCAP_GUI_URL={url}", flush=True)
    print(" Privacy: Bound strictly to 127.0.0.1 (offline loopback only)", flush=True)
    print(" Press Ctrl+C or click 'Stop Server' in the browser to exit.", flush=True)
    print("=" * 64, flush=True)

    if not args.no_browser:
        threading.Timer(0.25, lambda: webbrowser.open(url)).start()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        app.cleanup()
    return 0


if __name__ == "__main__":
    sys.exit(main())
