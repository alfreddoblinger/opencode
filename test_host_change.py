import json
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from host_change import ApprovalGate, Request, description
from approval_terminal import ask


class ChangeTests(unittest.TestCase):
    def test_click_decisions_and_ignored_input(self):
        cases = [
            (b"\x1b[<0;6;23M", True),
            (b"\x1b[<0;22;23M", False),
            (b"\x1b[<35;6;23M\r", False),
            (b"\x1b[<0;6;23m\r", False),
            (b"\x1b[<0;6;12M\r", False),
            (b"\x1b[<2;6;23M\r", False),
            (b"\x1b[200~j\x1b[201~\r", False),
            (b"\x1b[<65;6;5M\x1b[<0;6;23M", True),
        ]
        for incoming, expected in cases:
            request = Request(("true",), "/tmp", "", "test", 1)
            with self.subTest(incoming=incoming), patch("approval_terminal.termios.tcflush"), \
                 patch("approval_terminal.dimensions", return_value=(80, 24)), \
                 patch("approval_terminal.write"), \
                 patch("approval_terminal.select.select", return_value=([0], [], [])), \
                 patch("approval_terminal.os.read", side_effect=[bytes([c]) for c in incoming]):
                self.assertEqual(ask(request, 0, 1), expected)

    def test_mouse_sequence_does_not_decline(self):
        request = Request(("true",), "/tmp", "", "test", 1)
        incoming = b"\x1b[<35;50;39Mj"
        with patch("approval_terminal.termios.tcflush"), patch("approval_terminal.write"), \
             patch("approval_terminal.select.select", return_value=([0], [], [])), \
             patch("approval_terminal.os.read", side_effect=[bytes([c]) for c in incoming]):
            self.assertTrue(ask(request, 0, 1))

    def test_single_key_decisions(self):
        for key, expected in [(b"j", True), (b"J", True), (b"n", False),
                              (b"N", False), (b"\r", False), (b"\n", False)]:
            request = Request(("true",), "/tmp", "", "test", 1)
            with self.subTest(key=key), patch("approval_terminal.termios.tcflush"), \
                 patch("approval_terminal.write"), \
                 patch("approval_terminal.select.select", return_value=([0], [], [])), \
                 patch("approval_terminal.os.read", return_value=key):
                self.assertEqual(ask(request, 0, 1), expected)

    def invoke(self, gate, args):
        output = []
        def run():
            output.append(gate.execute_change(**args))
        worker = threading.Thread(target=run)
        worker.start()
        request = gate.pending.get(timeout=2)
        return worker, request, output

    def test_no_terminal(self):
        with self.assertRaises(PermissionError):
            ApprovalGate().execute_change(["true"], "/tmp", "test")

    def test_denied_leaves_no_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "result"
            gate = ApprovalGate(enabled=True)
            worker, request, output = self.invoke(gate, dict(argv=["touch", str(target)], cwd=tmp, reason="test"))
            self.assertFalse(target.exists())
            request.answered.set()
            worker.join(3)
            self.assertFalse(worker.is_alive())
            self.assertFalse(target.exists())
            self.assertEqual(output[0]["status"], "not_executed")

    def test_approved_once_then_new_approval(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "result"
            args = dict(argv=[sys.executable, "-c", "from pathlib import Path; Path('result').write_text('ok')"], cwd=tmp, reason="test")
            gate = ApprovalGate(enabled=True)
            worker, request, output = self.invoke(gate, args)
            self.assertFalse(target.exists())
            request.approved = True
            request.answered.set()
            worker.join(3)
            self.assertEqual(output[0]["exit_code"], 0)
            self.assertEqual(target.read_text(), "ok")
            target.unlink()
            worker, request, output = self.invoke(gate, args)
            self.assertFalse(target.exists())
            request.answered.set()
            worker.join(3)
            self.assertFalse(target.exists())

    def test_expired_approval(self):
        gate = ApprovalGate(enabled=True)
        worker, request, output = self.invoke(gate, dict(argv=["true"], cwd="/tmp", reason="test"))
        request.deadline = time.monotonic() - 1
        request.approved = True
        request.answered.set()
        worker.join(3)
        self.assertEqual(output[0]["status"], "not_executed")

    def test_no_model_approval_argument(self):
        with self.assertRaises(TypeError):
            ApprovalGate(True).execute_change(argv=["true"], cwd="/tmp", reason="test", approved=True)

    def test_terminal_escapes_visible(self):
        request = Request(("echo", "\x1b[2J"), "/tmp", "\x1b[0m", "reason", 1)
        text = description(request)
        self.assertNotIn("\x1b", text)
        self.assertIn("\\u001b", text)

    def test_exit_and_stdin(self):
        gate = ApprovalGate(enabled=True)
        worker, request, output = self.invoke(gate, dict(argv=["/bin/cat"], cwd="/tmp", reason="test", stdin="hello"))
        request.approved = True
        request.answered.set()
        worker.join(3)
        self.assertEqual(output[0]["output"], "hello")


if __name__ == "__main__":
    unittest.main()
