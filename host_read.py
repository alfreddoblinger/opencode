"""Bounded host reads for OpenCode; no shell, arbitrary SQL or Docker exec tool."""
import json
import os
from pathlib import Path
import re
import sqlite3
import stat
import subprocess
import time

MAX_OUTPUT = 131072


def command(argv, include_stderr=False):
    result = subprocess.run(argv, capture_output=True, text=True, timeout=20,
                            env={**os.environ, "GIT_OPTIONAL_LOCKS": "0"})
    if result.returncode:
        raise ValueError(result.stderr[:4000] or "Befehl fehlgeschlagen")
    output = result.stdout + (result.stderr if include_stderr else "")
    if len(output) > MAX_OUTPUT:
        raise ValueError("Ergebnis zu gross. Abfrage eingrenzen.")
    return output


def identifier(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,62}", value):
        raise ValueError("Ungueltiger Tabellen-/Spaltenname")
    return '"' + value + '"'


def integer(value, low, high):
    if type(value) is not int or not low <= value <= high:
        raise ValueError(f"Zahl muss zwischen {low} und {high} liegen")
    return value


def pg_query(query):
    # Queries are generated below, never supplied by the model. Read-only is extra protection.
    raw = command(["docker", "exec", "-e",
                   "PGOPTIONS=-c default_transaction_read_only=on -c statement_timeout=10000 -c search_path=pg_catalog -c standard_conforming_strings=on",
                   "kiconnect-postgres", "psql", "-X", "-qAt", "-v", "ON_ERROR_STOP=1",
                   "-U", "kiconnect", "-d", "kiconnect", "-c",
                   "SELECT coalesce(json_agg(r),'[]'::json) FROM (" + query + ") r"])
    return json.loads(raw)


def postgres_read(action, table="", columns=None, filters=None, limit=20, offset=0):
    if action == "tables":
        return pg_query("SELECT table_name FROM information_schema.tables WHERE table_schema='public' AND table_type='BASE TABLE' ORDER BY table_name")
    quoted_table = identifier(table)
    allowed = {row["table_name"] for row in postgres_read("tables")}
    if table not in allowed:
        raise ValueError("Keine Basistabelle in public: " + table)
    metadata = pg_query("SELECT column_name,data_type FROM information_schema.columns WHERE table_schema='public' AND table_name='" + table + "' ORDER BY ordinal_position")
    if action == "columns":
        return metadata
    if action != "rows":
        raise ValueError("Erlaubt: tables, columns, rows")
    names = {row["column_name"] for row in metadata}
    selected = columns or [row["column_name"] for row in metadata]
    if not isinstance(selected, list) or not selected or any(name not in names for name in selected):
        raise ValueError("Unbekannte Spalte")
    terms = []
    for item in filters or []:
        if item.get("column") not in names:
            raise ValueError("Unbekannte Filterspalte")
        value = item.get("value")
        if not isinstance(value, str) or len(value) > 1000 or "\x00" in value:
            raise ValueError("Filterwert muss kurzer Text sein")
        op = {"equals": "=", "contains": "ILIKE"}.get(item.get("op", "equals"))
        if op is None:
            raise ValueError("Filter: equals oder contains")
        if op == "ILIKE":
            value = "%" + value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        terms.append(identifier(item["column"]) + "::text " + op + " '" + value.replace("'", "''") + "'")
    query = "SELECT " + ",".join(identifier(name) for name in selected) + " FROM public." + quoted_table
    if terms:
        query += " WHERE " + " AND ".join(terms)
    query += f" LIMIT {integer(limit, 1, 100)} OFFSET {integer(offset, 0, 100000)}"
    return pg_query(query)


def sqlite_read(path, query):
    target = Path(path).resolve(strict=True)
    if not target.is_file() or target.suffix not in {".db", ".sqlite", ".sqlite3"}:
        raise ValueError("Vorhandene SQLite-Datei erforderlich")
    if len(query) > 16000:
        raise ValueError("Abfrage zu lang")
    db = sqlite3.connect(target.as_uri() + "?mode=ro", uri=True, timeout=2)
    try:
        db.execute("PRAGMA query_only=ON")
        db.enable_load_extension(False)
        allowed = {sqlite3.SQLITE_SELECT, sqlite3.SQLITE_READ, sqlite3.SQLITE_RECURSIVE}
        functions = {"count", "min", "max", "sum", "avg", "length", "lower", "upper", "coalesce", "substr", "date", "datetime", "strftime", "json_extract", "json_valid"}

        def authorize(action, arg1, arg2, database, source):
            if action in allowed or (action == sqlite3.SQLITE_FUNCTION and arg2 in functions):
                return sqlite3.SQLITE_OK
            return sqlite3.SQLITE_DENY

        db.set_authorizer(authorize)
        deadline = time.monotonic() + 5
        db.set_progress_handler(lambda: int(time.monotonic() > deadline), 1000)
        cursor = db.execute(query)
        rows = cursor.fetchmany(101)
        return {"columns": [col[0] for col in cursor.description or []], "rows": rows[:100], "truncated": len(rows) > 100}
    finally:
        db.close()


def docker_read(action, container="", lines=50):
    if action == "list":
        return command(["docker", "ps", "-a", "--format", "{{json .}}"])
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", container):
        raise ValueError("Containername erforderlich")
    if action == "logs":
        return command(["docker", "logs", "--tail", str(integer(lines, 1, 200)), container], include_stderr=True)
    if action == "inspect":
        return json.loads(command(["docker", "inspect", "--type", "container", container]))
    raise ValueError("Erlaubt: list, logs, inspect")


def file_read(path, action="read", offset=0, size=32768):
    target = Path(path).resolve(strict=True)
    if action == "list":
        with os.scandir(target) as entries:
            result = []
            for entry in entries:
                result.append({"name": entry.name, "directory": entry.is_dir(follow_symlinks=False)})
                if len(result) >= 1000:
                    return {"entries": result, "truncated": True}
        return {"entries": result, "truncated": False}
    if action != "read":
        raise ValueError("Erlaubt: list, read")
    fd = os.open(target, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW)
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise ValueError("Nur normale Dateien, keine Geraete/Sockets")
        data = os.pread(fd, integer(size, 1, 65536), integer(offset, 0, 2**40))
        return data.decode("utf-8", errors="replace")
    finally:
        os.close(fd)


def git_read(path, action="status"):
    args = {"status": ["status", "--short", "--branch"],
            "log": ["log", "-10", "--oneline"], "remotes": ["remote", "-v"],
            "diff": ["diff", "--no-ext-diff", "--no-textconv"],
            "branches": ["branch", "-avv"]}.get(action)
    if args is None:
        raise ValueError("Erlaubt: status, log, remotes, diff, branches")
    return command(["git", "--no-pager", "-c", "core.fsmonitor=false", "-C", str(Path(path).resolve(strict=True)), *args])


FUNCTIONS = {f.__name__: f for f in (postgres_read, sqlite_read, docker_read, file_read, git_read)}


def tool(name, description, properties, required):
    return {"name": name, "description": description,
            "annotations": {"readOnlyHint": True, "destructiveHint": False},
            "inputSchema": {"type": "object", "properties": properties, "required": required, "additionalProperties": False}}


STRING = {"type": "string"}
TOOLS = [
    tool("postgres_read", "Zentrale KIconnect PostgreSQL im Container, keine .db-Datei. Erst tables, dann columns, dann rows. Keine freie SQL-Abfrage.",
         {"action": {"enum": ["tables", "columns", "rows"]}, "table": STRING,
          "columns": {"type": "array", "items": STRING},
          "filters": {"type": "array", "items": {"type": "object", "properties": {"column": STRING, "op": {"enum": ["equals", "contains"]}, "value": STRING}, "required": ["column", "op", "value"], "additionalProperties": False}},
          "limit": {"type": "integer"}, "offset": {"type": "integer"}}, ["action"]),
    tool("sqlite_read", "Lesende SQLite-SELECT-Abfrage. Tabellen: SELECT name FROM sqlite_master WHERE type='table'. Keine Schreibbefehle oder PRAGMA.", {"path": STRING, "query": STRING}, ["path", "query"]),
    tool("docker_read", "Docker-Container auflisten, inspect oder begrenzte Logs lesen. Kein exec/start/stop.", {"action": {"enum": ["list", "inspect", "logs"]}, "container": STRING, "lines": {"type": "integer"}}, ["action"]),
    tool("file_read", "Host-Datei lesen oder Verzeichnis auflisten, auch ausserhalb des Projekts. offset/size in Bytes. Keine Aenderungen.", {"path": STRING, "action": {"enum": ["read", "list"]}, "offset": {"type": "integer"}, "size": {"type": "integer"}}, ["path"]),
    tool("git_read", "Git nur lesen: status/log/remotes/diff/branches. Kein fetch, pull, commit oder push.", {"path": STRING, "action": {"enum": ["status", "log", "remotes", "diff", "branches"]}}, ["path"]),
]
