#!/usr/bin/env python3
"""Run the whole OpenCode process under the installed bwrap AppArmor profile."""
import os
import json
from pathlib import Path
import subprocess
import sys
from read_server import start_server
from host_change import ApprovalGate
from approval_terminal import run_terminal

ROOT = Path(__file__).resolve().parent


def main():
    home = Path.home().resolve()
    workspace = Path.cwd().resolve()
    if workspace == home or not workspace.is_relative_to(home):
        raise SystemExit("Bitte in einem Projekt-Unterverzeichnis Ihres Home-Verzeichnisses starten.")
    if workspace != ROOT and (ROOT.is_relative_to(workspace) or workspace.is_relative_to(ROOT)):
        raise SystemExit("Installation und Laufzeitdaten sind kein beschreibbares Arbeitsprojekt.")
    if workspace.relative_to(home).parts[0].startswith("."):
        raise SystemExit("Bitte kein persoenliches Konfigurationsverzeichnis als Projekt verwenden.")
    runtime = ROOT / ".runtime"
    # Keep developer smoke tests out of the user's session list and --continue.
    if os.environ.get("OPENCODE_ISOLATED_TEST") == "1":
        runtime = runtime / "tests"
    runtime.mkdir(mode=0o700, exist_ok=True)
    for name in ("config", "data", "cache", "state"):
        (runtime / name).mkdir(mode=0o700, exist_ok=True)
    cmd = [
        "/usr/bin/bwrap", "--die-with-parent", "--new-session",
        "--unshare-user", "--unshare-pid", "--unshare-ipc", "--unshare-uts",
        "--cap-drop", "ALL", "--ro-bind", "/", "/",
        "--proc", "/proc", "--dev", "/dev",
        "--tmpfs", "/tmp", "--tmpfs", "/var/tmp", "--tmpfs", "/run",
        "--tmpfs", str(home), "--ro-bind", str(ROOT), str(ROOT),
        "--bind", str(runtime), str(runtime),
    ]
    if workspace != ROOT:
        cmd += ["--bind", str(workspace), str(workspace)]
    cmd += ["--remount-ro", str(home)]
    # Verify enforcement inside bwrap, rather than relying on a profile file existing.
    environment = {
        "HOME": str(home), "USER": home.name, "LOGNAME": home.name,
        "PATH": "/usr/local/bin:/usr/bin:/bin", "LANG": "C.UTF-8",
        "TERM": os.environ.get("TERM", "xterm-256color"),
        "OPENCODE_CONFIG": str(ROOT / "opencode.json"),
        "XDG_CONFIG_HOME": str(runtime / "config"),
        "XDG_DATA_HOME": str(runtime / "data"),
        "XDG_CACHE_HOME": str(runtime / "cache"),
        "XDG_STATE_HOME": str(runtime / "state"),
    }
    gate = ApprovalGate()
    server, thread, reader = start_server(gate)
    environment["OPENCODE_CONFIG_CONTENT"] = json.dumps({"mcp": {"host": reader}})
    cmd += ["--clearenv"]
    for key, value in environment.items():
        cmd += ["--setenv", key, value]
    cmd += ["--chdir", str(workspace), "--", "/usr/bin/python3", str(ROOT / "sandbox_entry.py")]
    try:
        result = run_terminal(cmd + sys.argv[1:], environment, gate)
    finally:
        gate.close()
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
    raise SystemExit(result)


if __name__ == "__main__":
    main()
