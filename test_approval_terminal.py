"""Manual PTY integration test. Only creates a marker in a temporary directory."""
import json
import os
from pathlib import Path
import sys
import tempfile

from approval_terminal import run_terminal
from host_change import ApprovalGate
from read_server import start_server


def main():
    gate = ApprovalGate()
    server, thread, config = start_server(gate)
    try:
        with tempfile.TemporaryDirectory(prefix="opencode-approval-test-") as tmp:
            marker = Path(tmp) / "approved"
            code = """
import json, os, urllib.request
cfg = json.loads(os.environ['TEST_MCP'])
request = urllib.request.Request(cfg['url'], headers={**cfg['headers'], 'Content-Type':'application/json'}, data=json.dumps({
 'jsonrpc':'2.0','id':1,'method':'tools/call','params':{'name':'execute_change','arguments':{
 'argv':['/usr/bin/touch',os.environ['TEST_MARKER']], 'cwd':'/tmp', 'reason':'Freigabetest: nur temporaere Testdatei'}}}).encode())
with urllib.request.urlopen(request,timeout=190) as response:
 print(json.load(response)['result'], flush=True)
"""
            env = {**os.environ, "TEST_MCP": json.dumps(config), "TEST_MARKER": str(marker)}
            result = run_terminal([sys.executable, "-c", code], env, gate)
            print("TEST_RESULT: marker_exists=" + str(marker.exists()) + " child_exit=" + str(result), flush=True)
    finally:
        gate.close()
        server.shutdown()
        server.server_close()
        thread.join()


if __name__ == "__main__":
    main()
