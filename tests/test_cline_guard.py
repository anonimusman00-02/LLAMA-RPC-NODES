import json
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.request import Request, urlopen

from cline_guard import sanitize_chat_request, start_cline_guard, strip_display_line_numbers


class LineNumberTests(unittest.TestCase):
    def test_consecutive_labels_removed_without_losing_indentation(self):
        original = "Header\n 91 | \n 92 | def total(a, b):\n 93 |     return a - b\nFooter\n"
        cleaned, count = strip_display_line_numbers(original)
        self.assertEqual(cleaned, "Header\n\ndef total(a, b):\n    return a - b\nFooter\n")
        self.assertEqual(count, 3)

    def test_isolated_label_and_patch_lines_are_untouched(self):
        original = "93 | may be real text\n- 92 | old\n+ 93 | new\n"
        cleaned, count = strip_display_line_numbers(original)
        self.assertEqual((cleaned, count), (original, 0))

    def test_only_message_content_changes(self):
        source = {"messages": [
            {"role": "tool", "content": "1 | one\n2 | two\n3 | three\n"},
        ], "tools": [{"function": {"description": "1 | one\n2 | two\n3 | three\n"}}]}
        result, count = sanitize_chat_request(json.dumps(source).encode())
        parsed = json.loads(result)
        self.assertEqual(parsed["messages"][0]["role"], "system")
        self.assertIn("Never copy the number", parsed["messages"][0]["content"])
        self.assertEqual(parsed["messages"][1]["content"], "one\ntwo\nthree\n")
        self.assertEqual(parsed["tools"], source["tools"])
        self.assertEqual(count, 3)

    def test_json_encoded_tool_result_is_cleaned(self):
        encoded = json.dumps({"result": "91 | before\n92 | def total(a, b):\n93 |     return a - b\n"})
        source = {"messages": [{"role": "system", "content": "Original instructions."},
                               {"role": "tool", "content": encoded}]}
        result, count = sanitize_chat_request(json.dumps(source).encode())
        parsed = json.loads(result)
        self.assertEqual(count, 3)
        self.assertTrue(parsed["messages"][0]["content"].startswith("Original instructions."))
        self.assertIn("Never copy the number", parsed["messages"][0]["content"])
        self.assertEqual(json.loads(parsed["messages"][1]["content"])["result"],
                         "before\ndef total(a, b):\n    return a - b\n")


class ProxyTests(unittest.TestCase):
    def test_forwards_cleaned_request_and_raw_response(self):
        received = []

        class UpstreamHandler(BaseHTTPRequestHandler):
            def log_message(self, *_args):
                return

            def do_POST(self):
                length = int(self.headers["Content-Length"])
                received.append((self.path, json.loads(self.rfile.read(length))))
                response = b'{"ok":true}'
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(response)))
                self.end_headers()
                self.wfile.write(response)

        upstream = ThreadingHTTPServer(("127.0.0.1", 0), UpstreamHandler)
        upstream_thread = threading.Thread(target=upstream.serve_forever, daemon=True)
        upstream_thread.start()
        guard, guard_thread = start_cline_guard(
            "127.0.0.1", upstream.server_address[1], 0
        )
        try:
            payload = json.dumps({"messages": [{"role": "tool",
                "content": "91 | before\n92 | def total(a, b):\n93 |     return a - b\n"}]}).encode()
            request = Request(
                f"http://127.0.0.1:{guard.server_address[1]}/v1/chat/completions",
                data=payload,
                headers={"Content-Type": "application/json"},
            )
            with urlopen(request, timeout=5) as response:
                self.assertEqual(response.read(), b'{"ok":true}')
            self.assertEqual(received[0][0], "/v1/chat/completions")
            self.assertEqual(
                received[0][1]["messages"][1]["content"],
                "before\ndef total(a, b):\n    return a - b\n",
            )
        finally:
            guard.shutdown()
            guard.server_close()
            guard_thread.join(timeout=2)
            upstream.shutdown()
            upstream.server_close()
            upstream_thread.join(timeout=2)


if __name__ == "__main__":
    unittest.main()
