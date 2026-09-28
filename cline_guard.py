"""Local Cline endpoint that removes display-only line labels from model input.

The upstream llama-server remains unchanged; this proxy only rewrites numbered
source blocks in chat history before forwarding requests. It never edits files
or rewrites model/tool responses.
"""

from http.client import HTTPConnection
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import re
import threading


_NUMBERED_LINE = re.compile(r"^[ \t]*(\d{1,7})[ \t]*\| ?(.*)$")
_PATCH_GUIDANCE = (
    "Display line numbers in tool output (for example `93 | code`) are not file "
    "contents. Never copy the number or `|` into editor/apply_patch changes; "
    "write only the original code and preserve its indentation."
)
_HOP_HEADERS = {
    "connection", "content-length", "host", "keep-alive",
    "proxy-authenticate", "proxy-authorization", "te", "trailers",
    "transfer-encoding", "upgrade",
}


def strip_display_line_numbers(text, minimum_run=3):
    """Remove consecutive numbered source labels, preserving code indentation."""
    lines = text.splitlines(keepends=True)
    parsed = []
    for line in lines:
        raw = line.rstrip("\r\n")
        ending = line[len(raw):]
        match = _NUMBERED_LINE.match(raw)
        parsed.append((int(match.group(1)), match.group(2), ending) if match else None)

    changed = 0
    index = 0
    while index < len(lines):
        if parsed[index] is None:
            index += 1
            continue
        end = index + 1
        while (end < len(lines) and parsed[end] is not None
               and parsed[end][0] == parsed[end - 1][0] + 1):
            end += 1
        if end - index >= minimum_run:
            for position in range(index, end):
                _, code, ending = parsed[position]
                lines[position] = code + ending
                changed += 1
        index = end
    return "".join(lines), changed


def sanitize_chat_request(body):
    """Return a JSON request with numbered history blocks cleaned, if present."""
    try:
        payload = json.loads(body)
    except (TypeError, ValueError):
        return body, 0
    if not isinstance(payload, dict):
        return body, 0

    changed = 0

    def clean(value):
        nonlocal changed
        if isinstance(value, str):
            result, count = strip_display_line_numbers(value)
            changed += count
            if count:
                return result
            if value.lstrip().startswith(("{", "[")) and "\\n" in value:
                try:
                    nested = json.loads(value)
                except ValueError:
                    pass
                else:
                    if isinstance(nested, (dict, list)):
                        before = changed
                        nested = clean(nested)
                        if changed > before:
                            return json.dumps(nested, ensure_ascii=False)
            return result
        if isinstance(value, list):
            return [clean(item) for item in value]
        if isinstance(value, dict):
            return {key: clean(item) for key, item in value.items()}
        return value

    for key in ("messages", "input"):
        if key in payload:
            payload[key] = clean(payload[key])
    if not changed:
        return body, 0
    messages = payload.get("messages")
    if isinstance(messages, list):
        for message in messages:
            if (isinstance(message, dict) and message.get("role") in ("system", "developer")
                    and isinstance(message.get("content"), str)):
                if _PATCH_GUIDANCE not in message["content"]:
                    message["content"] += "\n\n" + _PATCH_GUIDANCE
                break
        else:
            messages.insert(0, {"role": "system", "content": _PATCH_GUIDANCE})
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8"), changed


def start_cline_guard(upstream_host, upstream_port, listen_port, listen_host="127.0.0.1"):
    """Start a localhost-only, streaming-preserving proxy in a daemon thread."""
    class GuardHandler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, _format, *_args):
            return

        def do_GET(self):
            self._forward()

        def do_POST(self):
            self._forward()

        def do_OPTIONS(self):
            self._forward()

        def _forward(self):
            length = int(self.headers.get("Content-Length", "0"))
            if length < 0 or length > 32 * 1024 * 1024:
                self.send_error(413, "Request too large")
                return
            body = self.rfile.read(length) if length else b""
            if self.command == "POST" and self.path.split("?", 1)[0] in {
                "/v1/chat/completions", "/chat/completions", "/v1/responses"
            }:
                body, changed = sanitize_chat_request(body)
                if changed:
                    print(f"[CLINE GUARD] {changed} label nomor baris dihapus dari konteks baca.", flush=True)

            headers = {
                key: value for key, value in self.headers.items()
                if key.lower() not in _HOP_HEADERS and key.lower() != "accept-encoding"
            }
            headers["Accept-Encoding"] = "identity"
            headers["Content-Length"] = str(len(body))
            upstream = HTTPConnection(upstream_host, upstream_port, timeout=3600)
            try:
                upstream.request(self.command, self.path, body=body, headers=headers)
                response = upstream.getresponse()
                self.send_response(response.status, response.reason)
                for key, value in response.getheaders():
                    if key.lower() not in _HOP_HEADERS:
                        self.send_header(key, value)
                self.send_header("Connection", "close")
                self.end_headers()
                self.close_connection = True
                while True:
                    chunk = response.read1(16384)
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    self.wfile.flush()
            except (OSError, ConnectionError) as exc:
                if not self.wfile.closed:
                    try:
                        self.send_error(502, f"Upstream unavailable: {exc}")
                    except OSError:
                        pass
            finally:
                upstream.close()

    server = ThreadingHTTPServer((listen_host, listen_port), GuardHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True, name="cline-line-guard")
    thread.start()
    return server, thread
