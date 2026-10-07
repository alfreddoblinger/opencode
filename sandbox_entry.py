"""Fail closed unless the installed bwrap AppArmor profile is enforcing."""
import os
from pathlib import Path
import sys

root = Path(__file__).resolve().parent
profile = Path("/proc/self/attr/current").read_text().strip()
if "unpriv_bwrap" not in profile or "(enforce)" not in profile:
    raise SystemExit("Abbruch: erwartetes AppArmor-Profil nicht im Enforce-Modus: " + profile)

if sys.argv[1:] == ["--sandbox-check"]:
    assert not Path("/run/docker.sock").exists(), "Docker-Socket sichtbar"
    assert not (Path.home() / ".ssh").exists(), "SSH-Konfiguration sichtbar"
    assert "SSH_AUTH_SOCK" not in os.environ
    for directory in (Path("/etc"), Path.home(), root):
        probe = directory / (".opencode-sandbox-probe-" + str(os.getpid()))
        try:
            with probe.open("x"):
                pass
        except OSError:
            pass
        else:
            probe.unlink()
            raise SystemExit("FEHLER: Schreiben ausserhalb des Projekts moeglich: " + str(directory))
    probe = Path(os.environ["XDG_STATE_HOME"]) / ("probe-" + str(os.getpid()))
    probe.touch()
    probe.unlink()
    print("Sandbox bestanden: AppArmor enforce; System/Installation schreibgeschuetzt;")
    print("privates Home; Docker-Socket unsichtbar; Laufzeitverzeichnis schreibbar.")
    print("Netzwerk bleibt fuer Qwen erreichbar; kein Netzwerk-Sicherheitsfilter.")
    raise SystemExit(0)

binary = root / "node_modules/.bin/opencode"
os.execv(str(binary), [str(binary), *sys.argv[1:]])
