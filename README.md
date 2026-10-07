# OpenCode mit lokalem Qwen

Offizielle Installation von https://github.com/anomalyco/opencode
Version: 1.18.34 (package.json und package-lock.json).
Kein Fork, kein Codex-Adapter. Verbindung ueber Chat Completions.

Dieses Repository versioniert unsere Konfiguration und den Host-Starter, nicht
den OpenCode-Quellcode. Upstream: https://github.com/anomalyco/opencode.
Repository dieser Konfiguration: https://github.com/alfreddoblinger/opencode.

## Auf einem anderen Server installieren

Getestete Basis: Ubuntu 24.04, Python 3.12, Node.js 22.22.2, npm 10.9.7,
Bubblewrap 0.9.0 und ein aktives AppArmor-Profil. Diese Starter sind fuer Linux,
nicht fuer eine direkte Windows-/macOS-Installation gedacht.

```sh
git clone git@github.com:alfreddoblinger/opencode.git "$HOME/opencode"
npm ci --prefix "$HOME/opencode"
```

Auf Ubuntu die Systemvoraussetzungen einrichten (nicht aus dem Agenten heraus):

```sh
sudo apt install bubblewrap apparmor-profiles sqlite3
```

Hier wird unveraendert das von Ubuntu gelieferte Profil
`/usr/share/apparmor/extra-profiles/bwrap-userns-restrict` verwendet. Auf dem
Zielserver erst bestehende Profile pruefen, nicht blind ueberschreiben. Wenn es
noch nicht installiert ist:

```sh
sudo install -m 0644 /usr/share/apparmor/extra-profiles/bwrap-userns-restrict /etc/apparmor.d/bwrap-userns-restrict
sudo apparmor_parser -r /etc/apparmor.d/bwrap-userns-restrict
```

Keine globale AppArmor-/Usernamespace-Sicherheitsfunktion abschalten.
Danach Pfade und Zielsystem pruefen:

- `opencode.json`: instructions-Pfad an den Installationsordner anpassen;
  Qwen-baseURL und Modell-ID an den eigenen LLM-Server anpassen. Hier ist
  `http://100.72.231.65:8004/v1` mit `qwen3-coder-30b` eingetragen, ohne API-Key.
  Der Endpunkt muss vom Zielserver erreichbar sein. Werkzeugdaten werden an
  diesen konfigurierten LLM-Server uebermittelt, nicht nur lokal angezeigt.
- `reading-rules.md`: Projektpfade und betriebsspezifisches Wissen anpassen.
- `host_read.py`: PostgreSQL-Lesezugang ist auf Container `kiconnect-postgres`,
  DB/Benutzer `kiconnect` und Schema `public` eingestellt. Vor Verwendung auf
  einem anderen Server bewusst pruefen/anpassen. Keine DB-Passwoerter im Repo.
- Docker muss installiert sein und fuer den startenden Benutzer erreichbar
  sein, falls die Docker-/PostgreSQL-Werkzeuge benoetigt werden. Docker-Zugriff
  ist hochprivilegiert; der Agent bekommt den Socket nicht direkt durchgereicht.

Pruefen, bevor produktive Arbeiten gestartet werden:

```sh
cd "$HOME/opencode"
python3 -m unittest test_host_read test_host_change
bash start.sh --sandbox-check
```

Start danach aus dem gewuenschten Projekt-Unterverzeichnis:

```sh
cd "$HOME/kiconnect"
bash "$HOME/opencode/start.sh"
```

Der lokale Kurzbefehl `/home/alfred/.local/bin/opencode` hat auf diesem Server
folgenden Inhalt (auf anderen Servern den Installationspfad anpassen):

```sh
#!/usr/bin/env bash
set -euo pipefail
exec bash /home/alfred/opencode/start.sh "$@"
```

Die Datei muss ausfuehrbar sein und `~/.local/bin` im PATH liegen. Nicht mit
dem ungeschuetzten Upstream-Binary in node_modules verwechseln.

`/new` startet einen neuen Chat, `/sessions` waehlt einen gespeicherten Chat.
`opencode -s SESSION_ID` setzt eine bestimmte Sitzung fort. Chatverlaeufe werden
absichtlich nicht durch Git uebertragen: Auf einem neuen Server beginnt der
Verlauf leer. Fuer eine gesonderte Migration sensible Sitzungsdaten separat sichern.

## Inhalt und Ausschluesse

Enthalten sind Starter, OpenCode-Konfiguration, MCP-Werkzeuge, Freigabeanzeige,
Arbeitsregeln, Tests sowie package.json und package-lock.json mit fester Version.
Ausgeschlossen sind .runtime (Sitzungen, Logs, Cache), node_modules, Python-Cache,
Umgebungsdateien, Datenbanken und Schluessel. Keine Patientendaten mitversionieren.

## Start

Im gewuenschten Arbeitsverzeichnis:

```sh
bash /home/alfred/opencode/start.sh
```

Der Start muss in einem Projekt-Unterverzeichnis des Home-Verzeichnisses erfolgen.
Das aktuelle Arbeitsverzeichnis bleibt erhalten. Konfiguration:
`/home/alfred/opencode/opencode.json`.

Nur Qwen ist als Provider aktiviert; Haupt- und Hilfsmodell sind identisch.
Shell-Befehle und Datei-Aenderungen erfordern eine Bestaetigung.
Der Starter kapselt den gesamten OpenCode-Prozess in /usr/bin/bwrap und prueft
das bereits installierte AppArmor-Profil unpriv_bwrap auf Enforce-Modus.
Bei fehlender Abschirmung wird abgebrochen, ohne ungeschuetzten Neustart.
System und Installation bleiben read-only. Schreibbar sind nur das aktuelle
Projekt und .runtime in dieser Installation sowie private temporaere Verzeichnisse.
Das persoenliche Home wird verdeckt; SSH-Schluessel, SSH-Agent und Docker-Socket
werden nicht durchgereicht. Das Netzwerk bleibt erreichbar, auch lokale TCP-Dienste:
dies ist KEINE Netzwerksandbox und verhindert keine API-/DB-Aenderungen mit
erreichbaren Zugangsdaten. Projektdateien bleiben lesbar. Der Benutzer erlaubt
auch das Lesen lokaler Konfigurationen und die Anzeige eigener Daten.
AppArmor allein ersetzt diese Mount-Abschirmung nicht.
Host-Aenderungen laufen ausschliesslich ueber host_execute_change und eine
separate, einmalige Bestaetigung im Terminal des Starters. Der Agent selbst
bleibt in der Sandbox und erhaelt keinen Docker-Socket.
Chat-Sharing und automatische Versionsupdates sind deaktiviert.
OpenCode speichert Sitzungen und Cache getrennt unter .runtime.
Projektkonfigurationen koennen Einstellungen ergaenzen
oder ueberschreiben; vor Arbeit in fremden Projekten pruefen.

## Host-Lesewerkzeuge

Der Starter startet pro Sitzung einen lokalen MCP-Dienst auf 127.0.0.1 mit
zufaelligem Port und Sitzungstoken. Beim Beenden wird er gestoppt. Kein Dienst
nach aussen, keine neue Datenbankrolle, keine gespeicherten Zugangstokens.
Die MCP-Einbindung folgt https://opencode.ai/docs/mcp-servers/.

- host_postgres_read: Tabellen, Spalten und gefilterte Datensaetze der
  bestehenden zentralen Datenbank. Keine freie SQL-Ausfuehrung.
- host_sqlite_read: SELECT mit SQLite-Authorizer, read-only und Zeitlimit.
- host_docker_read: Liste, Inspect, begrenzte Logs; kein Docker-Socket im Agenten.
- host_file_read: normale Dateien/Verzeichnisse mit Host-Leserechten.
- host_git_read: Status, Diff, Branches, Remotes, Log ohne Git-Aenderungen.

Diese fuenf Tools sind ohne Rueckfrage erlaubt. Das ist bewusst keine pauschale
Freigabe von Shell-Befehlen wie find, sqlite3 oder docker exec. Ihre Optionen
koennen sonst schreiben oder Programme starten. Aenderungen im Projekt bleiben
freigabepflichtig; Host-Aenderungen verwenden die folgende Terminal-Freigabe.
Die Leserechte sind auf die OS-Rechte des startenden Benutzers begrenzt, kein sudo.
Docker-Inspect kann auf ausdruecklichen Wunsch auch Container-Umgebungswerte lesen.

Pruefung: `python3 /home/alfred/opencode/test_host_read.py`.
Konfigurationsaenderungen werden nach Neustart von OpenCode wirksam.

Entwickler-Smoke-Tests nur mit `OPENCODE_ISOLATED_TEST=1` starten. Dann liegen
Sitzungen unter .runtime/tests statt in den Benutzersitzungen. Dadurch wird
die mit --continue ausgewaehlte letzte Benutzersitzung nicht durch Tests ersetzt.
Bereits vorhandene Sitzungen werden nicht geloescht oder umgeschrieben.

## Aenderungen bestaetigen

Bei einer Datenbank-/Docker-/Git-/Host-Aenderung ruft Qwen host_execute_change auf.
Der Starter zeigt ausserhalb der OpenCode-Oberflaeche den genauen Befehl,
Arbeitsverzeichnis, Standardeingabe und Begruendung. `Allow once` mit der Maus
anklicken oder `J` druecken. `Reject`, `N` oder Enter lehnen ab. Lange Befehle
lassen sich mit Mausrad/Pfeiltasten durchsehen. Die Bestaetigung gilt
einmalig fuer diesen Aufruf, nie fuer spaetere Befehle. Nach 180 Sekunden verfaellt sie.

Die OpenCode-Konfiguration erlaubt den WerkzeugAUFRUF; sie erlaubt NICHT die
Ausfuehrung. Letztere wird im Host-Starter bestaetigt. Weder MCP-Parameter noch
ein Ja-Text des Modells koennen sie freigeben. OpenCode arbeitet auf einem eigenen
PTY; Freigabe-Eingaben werden nicht an OpenCode oder seine Shell weitergeleitet.
Ohne interaktives Terminal wird keine Host-Aenderung ausgefuehrt.
Die klickbare Anzeige gehoert zum Host-Starter, nicht zum nativen OpenCode-
Dialog: OpenCode 1.18.34 bietet hier keine MCP-Elicitation. Es gibt keine zweite
Freigabe. Das Terminal muss SGR-Mausereignisse unterstuetzen.

Ausfuehrung mit den bestehenden Rechten des Benutzers alfred, keine automatische
sudo-Eskalation, kein dauerhafter privilegierter Dienst. Den angezeigten Befehl
immer pruefen. Auch freigegebene Skripte/Programme koennen weitere Aktionen tun.
Nach Fehler oder Timeout Teilwirkungen pruefen, nicht blind erneut ausfuehren.

Tests: `python3 /home/alfred/opencode/test_host_change.py` sowie test_host_read.py.

## Wiederherstellen / Update

`npm ci --prefix /home/alfred/opencode` stellt die gepinnte Version wieder her.
Updates bewusst mit `npm install --prefix /home/alfred/opencode --save-exact
opencode-ai@VERSION` durchfuehren und danach Werkzeugaufrufe testen.
Die bisherige Codex-Installation bleibt unveraendert.

## Sandbox pruefen

```sh
cd /home/alfred/opencode
bash start.sh --sandbox-check
```

Kein neues AppArmor-Profil und keine globalen Kernel-Aenderungen erforderlich.
Auf anderen Servern muessen Bubblewrap und das passende Enforce-Profil zuerst
installiert werden. Installation alleine bedeutet nicht, dass AppArmor geladen ist.
