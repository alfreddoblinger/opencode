"""Host reads plus changes requiring independent, per-call terminal approval."""
import hmac
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import secrets
import threading

from host_read import FUNCTIONS, MAX_OUTPUT, TOOLS, tool, STRING


def start_server(gate=None):
    token = secrets.token_urlsafe(32)
    functions = dict(FUNCTIONS)
    tools = list(TOOLS)
    if gate is not None:
        functions["execute_change"] = gate.execute_change
        change_tool = tool("execute_change",
            "Aenderung am Host beantragen: Docker, PostgreSQL/SQLite, Git oder Dateien. "
            "Der Mensch muss den genauen Befehl im Terminal bestaetigen; KEIN pauschales Verbot. "
            "argv ist eine Argumentliste, keine implizite Shell. stdin fuer SQL oder Dateiinhalte. "
            "Keine Lesebefehle hier ausfuehren. Nach Ausfuehrung mit Lesewerkzeug kontrollieren.",
            {"argv": {"type": "array", "items": STRING}, "cwd": STRING,
             "reason": STRING, "stdin": STRING, "timeout": {"type": "integer"}},
            ["argv", "cwd", "reason"])
        change_tool["annotations"] = {"readOnlyHint": False, "destructiveHint": True, "idempotentHint": False}
        tools.append(change_tool)

    class Handler(BaseHTTPRequestHandler):
        def setup(self):
            super().setup()
            self.connection.settimeout(30)

        def log_message(self, *args):
            pass

        def respond(self, status, payload=None):
            body = json.dumps(payload, ensure_ascii=True, default=str).encode() if payload is not None else b""
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            self.respond(405)

        def do_POST(self):
            expected_host = f"127.0.0.1:{self.server.server_port}"
            if (self.path != "/mcp" or self.headers.get("Host") != expected_host
                    or self.headers.get("Origin") is not None
                    or not hmac.compare_digest(self.headers.get("Authorization", ""), "Bearer " + token)):
                self.respond(403)
                return
            try:
                size = int(self.headers.get("Content-Length", "0"))
                if not 0 < size <= 32768:
                    raise ValueError("Ungueltige Anfragegroesse")
                request = json.loads(self.rfile.read(size))
                if not isinstance(request, dict) or request.get("jsonrpc") != "2.0":
                    raise ValueError("Ungueltiges JSON-RPC")
            except (ValueError, TimeoutError):
                self.respond(400)
                return
            if "id" not in request:
                self.respond(202)
                return
            method = request.get("method")
            if method == "initialize":
                result = {"protocolVersion": "2025-06-18", "capabilities": {"tools": {}},
                          "serverInfo": {"name": "local-host-tools", "version": "1.1"}}
            elif method == "ping":
                result = {}
            elif method == "tools/list":
                result = {"tools": tools}
            elif method == "tools/call":
                try:
                    params = request.get("params", {})
                    name = params.get("name")
                    if name not in functions:
                        raise ValueError("Unbekanntes Werkzeug")
                    output = functions[name](**params.get("arguments", {}))
                    text = json.dumps(output, ensure_ascii=True, default=str)
                    if len(text) > MAX_OUTPUT:
                        raise ValueError("Ergebnis zu gross. Abfrage eingrenzen.")
                    result = {"content": [{"type": "text", "text": text}]}
                except Exception as exc:
                    result = {"isError": True, "content": [{"type": "text", "text": str(exc)[:4000]}]}
            else:
                self.respond(200, {"jsonrpc": "2.0", "id": request["id"],
                                   "error": {"code": -32601, "message": "Method not found"}})
                return
            self.respond(200, {"jsonrpc": "2.0", "id": request["id"], "result": result})

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.daemon_threads = True
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    config = {"type": "remote", "url": f"http://127.0.0.1:{server.server_port}/mcp",
              "oauth": False, "headers": {"Authorization": "Bearer " + token}, "timeout": 600000}
    return server, thread, config
