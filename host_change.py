"""Host execution gated by human input on the launcher's terminal, not MCP input."""
from dataclasses import dataclass, field
import json
import os
from pathlib import Path
import queue
import signal
import subprocess
import tempfile
import threading
import time


@dataclass
class Request:
    argv: tuple
    cwd: str
    stdin: str
    reason: str
    timeout: int
    deadline: float = field(default_factory=lambda: time.monotonic() + 180)
    answered: threading.Event = field(default_factory=threading.Event)
    approved: bool = False


class ApprovalGate:
    def __init__(self, enabled=False):
        self.enabled = enabled
        self.closed = threading.Event()
        self.pending = queue.Queue(maxsize=1)
        self.lock = threading.Lock()

    def close(self):
        self.closed.set()
        # Let a running command notice shutdown and reap its child before exit.
        if self.lock.acquire(timeout=5):
            self.lock.release()

    def execute_change(self, argv, cwd, reason, stdin="", timeout=120):
        if not self.enabled or self.closed.is_set():
            raise PermissionError("Host-Aenderung braucht ein interaktiv gestartetes opencode-Terminal. Nichts ausgefuehrt.")
        if (not isinstance(argv, list) or not 1 <= len(argv) <= 128
                or any(not isinstance(arg, str) or "\x00" in arg for arg in argv)
                or not argv[0] or sum(map(len, argv)) > 16000):
            raise ValueError("argv muss eine begrenzte Liste von Befehlsargumenten sein")
        if not isinstance(stdin, str) or len(stdin) > 16000 or "\x00" in stdin:
            raise ValueError("stdin ungueltig")
        if not isinstance(reason, str) or not reason.strip() or len(reason) > 2000:
            raise ValueError("Konkrete Begruendung erforderlich")
        if type(timeout) is not int or not 1 <= timeout <= 300:
            raise ValueError("timeout: 1 bis 300 Sekunden")
        path = Path(cwd).resolve(strict=True)
        if not path.is_dir():
            raise ValueError("Arbeitsverzeichnis fehlt")
        if not self.lock.acquire(blocking=False):
            raise PermissionError("Eine andere Host-Aenderung wartet bereits oder laeuft")
        try:
            request = Request(tuple(argv), str(path), stdin, reason, timeout)
            self.pending.put_nowait(request)
            while not request.answered.wait(0.1):
                if self.closed.is_set() or time.monotonic() >= request.deadline:
                    return {"status": "not_executed", "message": "Freigabe abgebrochen oder abgelaufen. Nichts ausgefuehrt."}
            if not request.approved or self.closed.is_set() or time.monotonic() >= request.deadline:
                return {"status": "not_executed", "message": "Nicht freigegeben. Nichts ausgefuehrt."}
            # No approval parameter or reusable grant is exposed to the model.
            with tempfile.TemporaryFile() as output:
                proc = subprocess.Popen(request.argv, cwd=request.cwd, stdin=subprocess.PIPE,
                                        stdout=output, stderr=subprocess.STDOUT, start_new_session=True)
                stopped = False
                deadline = time.monotonic() + request.timeout
                first = True
                try:
                    while True:
                        try:
                            proc.communicate(request.stdin.encode() if first else None, timeout=0.2)
                            break
                        except subprocess.TimeoutExpired:
                            first = False
                            if self.closed.is_set() or time.monotonic() >= deadline:
                                stopped = True
                                try:
                                    os.killpg(proc.pid, signal.SIGKILL)
                                except ProcessLookupError:
                                    pass
                                proc.communicate()
                                break
                finally:
                    if proc.poll() is None:
                        os.killpg(proc.pid, signal.SIGKILL)
                        proc.wait()
                output.seek(0)
                data = output.read(65537)
            return {"status": "interrupted" if stopped else "executed", "exit_code": proc.returncode,
                    "output": data[:65536].decode("utf-8", errors="replace"),
                    "truncated": len(data) > 65536,
                    "warning": "Bei Fehler oder Timeout koennen Teilwirkungen bestehen. Erst pruefen, nicht blind wiederholen."}
        finally:
            self.lock.release()


def description(request):
    # JSON escaping prevents command arguments from hiding terminal text with ANSI codes.
    return ("\n=== HOST-AENDERUNG: FREIGABE ERFORDERLICH ===\n"
            + "Grund: " + json.dumps(request.reason, ensure_ascii=True)
            + "\nVerzeichnis: " + json.dumps(request.cwd, ensure_ascii=True)
            + "\nBefehl (Argumente): " + json.dumps(request.argv, ensure_ascii=True)
            + "\nStandardeingabe: " + json.dumps(request.stdin, ensure_ascii=True)
            + f"\nZeitlimit: {request.timeout}s\n"
            + "Nur dieser Aufruf wird freigegeben. Keine dauerhafte Freigabe.\n"
            + "Allow once: einmal ausfuehren. Reject: ablehnen.\n"
            + "Alternativ J = ausfuehren; N / Enter / Escape = ablehnen.")
