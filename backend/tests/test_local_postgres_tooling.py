"""Verify portable PostgreSQL tooling safety without importing SupplyOS application code."""

from __future__ import annotations

import concurrent.futures
import contextlib
import hashlib
import io
import json
import os
import stat
import sys
import tempfile
import threading
import unittest
import zipfile
from pathlib import Path
from typing import Any
from unittest import mock
from urllib.parse import urlsplit

from tools import local_postgres as pg


@unittest.skipUnless(
    pg.TEMP_PARENT.is_dir(), "The pre-approved Windows temporary parent is required.",
)
class ToolingSafetyTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temporary = tempfile.TemporaryDirectory(
            prefix="supplyos-postgres-tooling-tests-", dir=pg.TEMP_PARENT,
        )
        self.addCleanup(self._temporary.cleanup)
        self.root = Path(self._temporary.name)
        self.cache = self.root / "owned-cache"

    def _archive_fixture(self) -> dict[str, dict[str, Any]]:
        self.cache.mkdir()
        with zipfile.ZipFile(self.cache / "archive.zip", "w") as archive:
            for name in ("initdb.exe", "postgres.exe", "pg_ctl.exe"):
                archive.writestr(f"pgsql/bin/{name}", b"not executable: test fixture only")
            archive.writestr("pgsql/bin/libpq.dll", b"fixture DLL, never loaded")
            archive.writestr("pgsql/lib/extension.dll", b"fixture extension, never loaded")
            archive.writestr("pgsql/share/postgres.bki", b"fixture bootstrap, never used")
            archive.writestr("pgsql/share/extension/example.sql", b"fixture SQL, never executed")
            archive.writestr("pgsql/doc/postgresql/html/legalnotice.html", b"fixture legal notice")
            archive.writestr("pgsql/bin/psql.exe", b"must not extract or execute")
            archive.writestr("pgsql/pgAdmin 4/python.exe", b"must not extract or execute")
            archive.writestr("pgsql/doc/postgresql/html/index.html", b"not a license")
        return pg._extract_archive(self.cache)

    def _receipt(self) -> pg.Installation:
        return pg.Installation(
            version=pg.VERSION, build=pg.BUILD, cache_directory=self.cache,
            binary_directory=self.cache / "runtime" / "pgsql" / "bin",
            archive_url=pg.ARCHIVE_URL, archive_bytes=pg.EXPECTED_ARCHIVE_BYTES,
            archive_sha256="0" * 64, extracted_files=1, extracted_bytes=1,
            checksum_verification=pg._CHECKSUM_STATUS, license_files=(),
        )

    def test_unowned_cache_is_preserved(self) -> None:
        self.cache.mkdir()
        existing = self.cache / "unknown-user-file"
        existing.write_text("preserve", encoding="ascii")
        with (
            mock.patch.object(pg, "TEMP_PARENT", self.root),
            mock.patch.object(pg, "CACHE_DIRECTORY", self.cache),
            self.assertRaises(pg.LocalPostgresError),
        ):
            pg._owned_cache()
        self.assertEqual(existing.read_text(encoding="ascii"), "preserve")
        self.assertFalse((self.cache / "ownership.json").exists())

    def test_owned_cache_refuses_unknown_contents(self) -> None:
        with (
            mock.patch.object(pg, "TEMP_PARENT", self.root),
            mock.patch.object(pg, "CACHE_DIRECTORY", self.cache),
        ):
            pg._owned_cache()
            existing = self.cache / "unknown-user-file"
            existing.write_text("preserve", encoding="ascii")
            with self.assertRaises(pg.LocalPostgresError):
                pg._owned_cache()
            self.assertEqual(existing.read_text(encoding="ascii"), "preserve")

    def test_cache_outside_approved_parent_is_refused(self) -> None:
        with (
            mock.patch.object(pg, "TEMP_PARENT", self.root),
            mock.patch.object(pg, "CACHE_DIRECTORY", self.root / "nested" / "cache"),
            self.assertRaises(pg.LocalPostgresError),
        ):
            pg._owned_cache()
        self.assertFalse((self.root / "nested").exists())

    @unittest.skipUnless(sys.platform == "win32", "Windows file locking is required.")
    def test_unknown_lock_contents_are_preserved(self) -> None:
        self.cache.mkdir()
        lock = self.cache / "install.lock"
        lock.write_bytes(b"unknown")
        with self.assertRaises(pg.LocalPostgresError), pg._installation_lock(self.cache):
            self.fail("Unrecognized lock was accepted.")
        self.assertEqual(lock.read_bytes(), b"unknown")

    @unittest.skipUnless(sys.platform == "win32", "Windows file locking is required.")
    def test_installation_lock_serializes_concurrent_helpers(self) -> None:
        self.cache.mkdir()
        started, first_active = threading.Event(), threading.Event()
        first_active.set()

        def second_lock() -> bool:
            started.set()
            with pg._installation_lock(self.cache):
                return first_active.is_set()

        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            with pg._installation_lock(self.cache):
                pending = pool.submit(second_lock)
                self.assertTrue(started.wait(timeout=2))
                first_active.clear()
            self.assertFalse(pending.result(timeout=5), "Another helper entered a held lock.")
        self.assertEqual((self.cache / "install.lock").read_bytes(), b"\0")

    def test_unsafe_zip_paths_are_refused(self) -> None:
        paths = (
            "../escape", "/absolute", r"..\escape", "C:/escape", "pgsql//",
            "pgsql/share/../../escape", "pgsql//share/file", "pgsql/./share/file",
            "pgsql/share/file.", "pgsql/share/file ", "pgsql/share/CON.txt",
            "pgsql/share/LPT1", "pgsql/share/CONOUT$", "pgsql/share/a:b",
            "pgsql/share/COM\u00b9.txt", "pgsql/share/LPT\u00b2", "pgsql/share/NUL .txt",
            "pgsql/share/a?b", "pgsql/share/a<b", "pgsql/share/a\nb", "pgsql/share/a\0b",
        )
        for name in paths:
            with self.subTest(name=name), self.assertRaises(pg.LocalPostgresError):
                pg._archive_parts(zipfile.ZipInfo(name))

    def test_zip_symlinks_and_special_files_are_refused(self) -> None:
        for kind in (stat.S_IFLNK, stat.S_IFIFO, stat.S_IFSOCK):
            info = zipfile.ZipInfo("pgsql/share/unsafe")
            info.external_attr = (kind | 0o600) << 16
            with self.subTest(kind=kind), self.assertRaises(pg.LocalPostgresError):
                pg._archive_parts(info)
        info = zipfile.ZipInfo("pgsql/share/reparse")
        info.external_attr = 0x400
        with self.assertRaises(pg.LocalPostgresError):
            pg._archive_parts(info)

    def test_zip_case_collisions_are_refused(self) -> None:
        content = io.BytesIO()
        with zipfile.ZipFile(content, "w") as archive:
            archive.writestr("pgsql/share/A.sql", b"a")
            archive.writestr("pgsql/share/a.sql", b"b")
        with zipfile.ZipFile(content) as archive, self.assertRaises(pg.LocalPostgresError):
            pg._selected_entries(archive)

    def test_extraction_size_is_bounded(self) -> None:
        content = io.BytesIO()
        with zipfile.ZipFile(content, "w") as archive:
            archive.writestr("pgsql/share/large", b"12345")
        with (
            zipfile.ZipFile(content) as archive,
            mock.patch.object(pg, "_MAX_EXTRACTED_BYTES", 4),
            self.assertRaises(pg.LocalPostgresError),
        ):
            pg._selected_entries(archive)

    def test_only_runtime_and_licenses_are_extracted(self) -> None:
        manifest = self._archive_fixture()
        self.assertIn("pgsql/bin/postgres.exe", manifest)
        self.assertIn("pgsql/bin/libpq.dll", manifest)
        self.assertIn("pgsql/share/postgres.bki", manifest)
        self.assertIn("pgsql/doc/postgresql/html/legalnotice.html", manifest)
        self.assertNotIn("pgsql/bin/psql.exe", manifest)
        self.assertNotIn("pgsql/pgAdmin 4/python.exe", manifest)
        self.assertNotIn("pgsql/doc/postgresql/html/index.html", manifest)
        pg._validate_runtime(self.cache, manifest)

    def test_runtime_tampering_is_not_repaired(self) -> None:
        manifest = self._archive_fixture()
        target = self.cache / "runtime" / "pgsql" / "bin" / "postgres.exe"
        target.write_bytes(b"changed")
        with self.assertRaises(pg.LocalPostgresError):
            pg._validate_runtime(self.cache, manifest)
        self.assertEqual(target.read_bytes(), b"changed")

    def test_extra_runtime_dll_is_not_accepted_or_deleted(self) -> None:
        manifest = self._archive_fixture()
        target = self.cache / "runtime" / "pgsql" / "bin" / "extra.dll"
        target.write_bytes(b"unknown")
        with self.assertRaises(pg.LocalPostgresError):
            pg._validate_runtime(self.cache, manifest)
        self.assertEqual(target.read_bytes(), b"unknown")

    def test_provenance_never_claims_an_independent_signature(self) -> None:
        self._archive_fixture()
        archive = self.cache / "archive.zip"
        size = archive.stat().st_size
        record = {
            "tool": pg._TOOL_ID, "cache_format": pg._CACHE_FORMAT, "version": pg.VERSION,
            "build": pg.BUILD, "archive_url": pg.ARCHIVE_URL, "effective_url": pg.ARCHIVE_URL,
            "archive_bytes": size,
            "archive_sha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
            "checksum_verification": "independently signed (false claim)",
        }
        pg._write_json(self.cache / "provenance.json", record)
        with (
            mock.patch.object(pg, "EXPECTED_ARCHIVE_BYTES", size),
            self.assertRaises(pg.LocalPostgresError),
        ):
            pg._validate_provenance(self.cache)
        self.assertEqual(pg._read_json(self.cache / "provenance.json"), record)

    def test_redirects_are_refused_without_contacting_another_source(self) -> None:
        handler = pg._OfficialRedirectHandler()
        with self.assertRaises(pg.LocalPostgresError):
            handler.redirect_request(None, None, 302, "Found", {}, "https://example.invalid")

    def test_install_does_not_start_native_processes_or_load_db_drivers(self) -> None:
        receipt = self._receipt()
        record = {
            "state": "installed", "archive_bytes": receipt.archive_bytes,
            "archive_sha256": receipt.archive_sha256,
            "checksum_verification": pg._CHECKSUM_STATUS,
            "files": {"pgsql/bin/postgres.exe": {"bytes": 1, "sha256": "0" * 64}},
        }
        self.cache.mkdir()
        (self.cache / "provenance.json").write_text("fixture", encoding="ascii")
        with (
            mock.patch.object(pg, "_require_windows"),
            mock.patch.object(pg, "_owned_cache", return_value=self.cache),
            mock.patch.object(pg, "_installation_lock", return_value=contextlib.nullcontext()),
            mock.patch.object(pg, "_validate_provenance", return_value=record),
            mock.patch.object(pg, "_validate_runtime"),
            mock.patch.object(pg, "_complete_licenses"),
            mock.patch.object(pg, "_WindowsJob") as native,
            mock.patch.object(pg.importlib, "import_module") as imports,
        ):
            pg.ensure_installed()
        native.assert_not_called()
        imports.assert_not_called()

    def test_urls_and_object_have_private_repr_and_readonly_identity(self) -> None:
        cluster = pg.LocalPostgres()
        password = cluster._password
        cluster._state = "running"  # URL-only unit test; never starts or pretends to query a DB.
        for name, scheme in (
            ("async_url", "postgresql+asyncpg"), ("sync_url", "postgresql+psycopg2"),
            ("dsn", "postgresql"),
        ):
            url = getattr(cluster, name)
            self.assertTrue(password not in repr(url), "URL repr must redact credentials.")
            self.assertEqual(urlsplit(url).scheme, scheme)
        self.assertTrue(password not in repr(cluster), "Context repr must redact credentials.")
        self.assertTrue(cluster.database.startswith("supplyos_test_"))
        for name in ("host", "port", "database", "installation"):
            with self.subTest(attribute=name), self.assertRaises(AttributeError):
                setattr(cluster, name, "not allowed")
        cluster.close()
        with self.assertRaises(pg.LocalPostgresError):
            _ = cluster.dsn

    def test_child_environment_does_not_expose_inherited_db_configuration(self) -> None:
        cluster = pg.LocalPostgres()
        cluster._installation, cluster._root = self._receipt(), self.root
        original_path = os.environ.get("PATH")
        variables = {"PGDATA": "unrelated", "PGPASSWORD": "generated-fixture"}
        with mock.patch.dict(os.environ, variables):
            environment = cluster._environment()
        self.assertNotIn("PGDATA", environment)
        self.assertNotIn("PGPASSWORD", environment)
        self.assertNotIn("DATABASE_URL", environment)
        self.assertEqual(environment["TEMP"], str(self.root))
        self.assertTrue(original_path == os.environ.get("PATH"))

    @unittest.skipUnless(sys.platform == "win32", "Windows socket exclusivity is required.")
    def test_reserved_port_is_fresh_high_and_loopback_only(self) -> None:
        with pg._reserve_port() as first, pg._reserve_port() as second:
            self.assertEqual(first.getsockname()[0], "127.0.0.1")
            self.assertGreaterEqual(first.getsockname()[1], 49152)
            self.assertLessEqual(first.getsockname()[1], 65535)
            self.assertNotEqual(first.getsockname()[1], second.getsockname()[1])

    def test_changed_cluster_ownership_is_preserved(self) -> None:
        self.cache.mkdir()
        root = self.cache / ("cluster-" + "a" * 32)
        root.mkdir()
        existing = root / "unknown-user-file"
        existing.write_text("preserve", encoding="ascii")
        (root / "ownership.json").write_text(
            json.dumps({"owner": "someone else"}), encoding="ascii",
        )
        cluster = pg.LocalPostgres()
        cluster._installation, cluster._root = self._receipt(), root
        with self.assertRaises(pg.LocalPostgresError):
            cluster.close()
        self.assertEqual(existing.read_text(encoding="ascii"), "preserve")

    @unittest.skipUnless(sys.platform == "win32", "The helper's runtime is Windows-only.")
    def test_failed_native_initialization_removes_only_the_new_cluster(self) -> None:
        self.cache.mkdir()
        sibling = self.cache / "unrelated"
        sibling.write_text("preserve", encoding="ascii")
        job = mock.Mock()
        job.make_private_directory.side_effect = lambda path: path.mkdir()
        job.wait_empty.return_value = True
        cluster = pg.LocalPostgres()
        with (
            mock.patch.object(pg, "ensure_installed", return_value=self._receipt()),
            mock.patch.object(pg, "_WindowsJob", return_value=job),
            mock.patch.object(pg.importlib, "import_module"),
            mock.patch.object(
                pg.LocalPostgres, "_initialize", side_effect=pg.LocalPostgresError("probe"),
            ),
            self.assertRaises(pg.LocalPostgresError),
        ):
            cluster.__enter__()
        self.assertFalse(cluster.data_directory.parent.exists())
        self.assertEqual(sibling.read_text(encoding="ascii"), "preserve")
        job.terminate.assert_called_once()
        job.close.assert_called_once()

    @unittest.skipUnless(sys.platform == "win32", "The helper's runtime is Windows-only.")
    def test_fast_stop_failure_terminates_owned_job_and_still_cleans_up(self) -> None:
        self.cache.mkdir()
        job = mock.Mock()
        job.make_private_directory.side_effect = lambda path: path.mkdir()
        job.contains.return_value, job.wait_empty.return_value = True, True
        cluster = pg.LocalPostgres()
        with (
            mock.patch.object(pg, "ensure_installed", return_value=self._receipt()),
            mock.patch.object(pg, "_WindowsJob", return_value=job),
            mock.patch.object(pg.importlib, "import_module"),
            mock.patch.object(pg.LocalPostgres, "_initialize"),
            mock.patch.object(pg.LocalPostgres, "_configure"),
            mock.patch.object(pg.LocalPostgres, "_create_database"),
            mock.patch.object(pg.LocalPostgres, "_check_postmaster", return_value=123),
            mock.patch.object(
                pg.LocalPostgres, "_run_binary",
                side_effect=["started", pg.LocalPostgresError("stop probe")],
            ),
        ):
            with cluster:
                root = cluster.data_directory.parent
        self.assertFalse(root.exists())
        self.assertEqual(cluster._shutdown_mode, "job-termination")
        job.terminate.assert_called_once()
        job.close.assert_called_once()


@unittest.skipUnless(
    os.environ.get("SUPPLYOS_VERIFY_POSTGRES") == "1" and sys.platform == "win32",
    "Opt in with SUPPLYOS_VERIFY_POSTGRES=1 to start owned real PostgreSQL clusters.",
)
class RealToolingLifecycleTests(unittest.TestCase):
    def test_independent_contexts_have_distinct_real_databases_and_clean_up(self) -> None:
        import psycopg2

        with pg.LocalPostgres() as first, pg.LocalPostgres() as second:
            first_root, second_root = first.data_directory.parent, second.data_directory.parent
            self.assertNotEqual(first.database, second.database)
            self.assertNotEqual(first.port, second.port)
            self.assertNotEqual(first_root, second_root)
            for cluster in (first, second):
                self.assertFalse((cluster.data_directory.parent / "bootstrap-password").exists())
                with contextlib.closing(cluster.connect()) as connection:
                    with connection.cursor() as cursor:
                        cursor.execute(
                            "SELECT current_database(), host(inet_server_addr()), "
                            "inet_server_port()"
                        )
                        expected = (cluster.database, "127.0.0.1", cluster.port)
                        self.assertEqual(cursor.fetchone(), expected)
            with self.assertRaises(psycopg2.OperationalError):
                with contextlib.closing(psycopg2.connect(
                    host=first.host, port=first.port, dbname=first.database,
                    user=first._username, password="not-the-generated-password",
                    sslmode="disable", connect_timeout=3,
                )):
                    pass
            with self.assertRaises(psycopg2.OperationalError):
                with contextlib.closing(psycopg2.connect(
                    host=second.host, port=second.port, dbname=second.database,
                    user=first._username, password=first._password,
                    sslmode="disable", connect_timeout=3,
                )):
                    pass
        self.assertFalse(first_root.exists())
        self.assertFalse(second_root.exists())

    def test_body_exception_still_stops_and_removes_the_real_cluster(self) -> None:
        cluster = pg.LocalPostgres()
        with self.assertRaisesRegex(RuntimeError, "tooling lifecycle probe"):
            with cluster:
                root = cluster.data_directory.parent
                with contextlib.closing(cluster.connect()) as connection:
                    with connection.cursor() as cursor:
                        cursor.execute("SELECT 1")
                        self.assertEqual(cursor.fetchone(), (1,))
                raise RuntimeError("tooling lifecycle probe")
        self.assertFalse(root.exists())
        self.assertTrue(cluster.installation.cache_directory.is_dir())


if __name__ == "__main__":
    unittest.main()
