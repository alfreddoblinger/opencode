import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
import urllib.request
import urllib.error

import host_read as h
from read_server import start_server


class ReadTests(unittest.TestCase):
    def test_identifiers(self):
        for value in ['patients;DELETE FROM patients', 'a"b', '-x', '\\! touch x']:
            with self.assertRaises(ValueError):
                h.identifier(value)

    def test_bounds(self):
        for value in [True, "20", -1, 1001]:
            with self.assertRaises(ValueError):
                h.integer(value, 1, 100)

    def test_postgres_generated_query(self):
        responses = [[{"table_name": "patients"}], [{"column_name": "last_name", "data_type": "text"}], []]
        with patch.object(h, "pg_query", side_effect=responses) as query:
            h.postgres_read("rows", "patients", ["last_name"], [{"column": "last_name", "value": "x'; DELETE FROM patients; --", "op": "equals"}])
            sql = query.call_args.args[0]
            self.assertIn("'x''; DELETE FROM patients; --'", sql)
            self.assertTrue(sql.endswith("LIMIT 20 OFFSET 0"))

    def test_sqlite(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "test.db"
            with sqlite3.connect(path) as db:
                db.execute("CREATE TABLE sample (id INTEGER)")
                db.execute("INSERT INTO sample VALUES (1)")
            self.assertEqual(h.sqlite_read(str(path), "SELECT id FROM sample")["rows"], [(1,)])
            for sql in ["DELETE FROM sample", "UPDATE sample SET id=2", "DROP TABLE sample", "PRAGMA user_version=3", "ATTACH ':memory:' AS other", "SELECT load_extension('x')", "SELECT 1; DELETE FROM sample"]:
                with self.subTest(sql=sql), self.assertRaises(sqlite3.Error):
                    h.sqlite_read(str(path), sql)
            self.assertEqual(h.sqlite_read(str(path), "SELECT count(*) FROM sample")["rows"], [(1,)])

    def test_docker_reject_mutations(self):
        with patch.object(h, "command") as command:
            for action in ["exec", "restart", "stop", "rm"]:
                with self.assertRaises(ValueError):
                    h.docker_read(action, "kiconnect-postgres")
            command.assert_not_called()

    def test_file_read_and_no_devices(self):
        self.assertIn("ReadTests", h.file_read(__file__))
        with self.assertRaises(ValueError):
            h.file_read("/dev/null")

    def test_git_reject_changes(self):
        with self.assertRaises(ValueError):
            h.git_read("/tmp", "pull")

    def test_authenticated_mcp(self):
        server, thread, cfg = start_server()
        try:
            payload = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/list"}).encode()
            request = urllib.request.Request(cfg["url"], data=payload, headers={"Content-Type": "application/json"})
            with self.assertRaises(urllib.error.HTTPError) as error:
                urllib.request.urlopen(request)
            self.assertEqual(error.exception.code, 403)
            request.add_header("Authorization", cfg["headers"]["Authorization"])
            with urllib.request.urlopen(request) as response:
                self.assertEqual(len(json.load(response)["result"]["tools"]), 5)
            request.add_header("Origin", "https://example.com")
            with self.assertRaises(urllib.error.HTTPError) as error:
                urllib.request.urlopen(request)
            self.assertEqual(error.exception.code, 403)
        finally:
            server.shutdown()
            server.server_close()
            thread.join()


if __name__ == "__main__":
    unittest.main()
