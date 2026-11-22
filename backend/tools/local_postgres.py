"""Provision an owned, disposable real PostgreSQL 15 cluster for local verification only."""

from __future__ import annotations

import argparse
import asyncio
import atexit
import concurrent.futures
import contextlib
import ctypes
import hashlib
import importlib
import json
import os
import re
import secrets
import shutil
import socket
import ssl
import stat
import subprocess
import sys
import time
import urllib.request
import uuid
import zipfile
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from types import TracebackType
from typing import TYPE_CHECKING, Any, Iterator
from urllib.parse import quote

if TYPE_CHECKING:
    import psycopg2.extensions

VERSION = "15.19"
BUILD = "5"
ARCHIVE_URL = (
    "https://get.enterprisedb.com/postgresql/"
    "postgresql-15.19-5-windows-x64-binaries.zip"
)
EXPECTED_ARCHIVE_BYTES = 371_120_384
TEMP_PARENT = Path(r"C:\Users\singh\AppData\Local\Temp\kilo")
CACHE_DIRECTORY = TEMP_PARENT / "supplyos-postgresql-15.19-5-windows-x64-v1"
_TOOL_ID = "supplyos.local_postgres"
_CACHE_FORMAT = 1
_REQUIRED_BINARIES = frozenset({"initdb.exe", "pg_ctl.exe", "postgres.exe"})
_SHA256_PATTERN = re.compile(r"[0-9a-f]{64}\Z")
_MAX_EXTRACTED_BYTES = 2 * 1024**3
_CHECKSUM_STATUS = "Local SHA256 only; no independent publisher checksum or signature."


class LocalPostgresError(RuntimeError):
    """A safe diagnostic for a failed isolated installation or cluster operation."""


@dataclass(frozen=True, slots=True)
class Installation:
    """Non-secret receipt; SHA256 is locally observed, not a publisher signature."""

    version: str
    build: str
    cache_directory: Path
    binary_directory: Path
    archive_url: str
    archive_bytes: int
    archive_sha256: str
    extracted_files: int
    extracted_bytes: int
    checksum_verification: str
    license_files: tuple[str, ...]


def _require_windows() -> None:
    if sys.platform != "win32" or sys.maxsize <= 2**32:
        raise LocalPostgresError("This helper supports 64-bit Windows Python only.")


def _reject_link(path: Path) -> None:
    metadata = path.lstat()
    if stat.S_ISLNK(metadata.st_mode) or getattr(metadata, "st_file_attributes", 0) & 0x400:
        raise LocalPostgresError(f"Refusing a symlink or reparse point: {path}")


def _read_json(path: Path) -> dict[str, Any]:
    _reject_link(path)
    if not path.is_file() or path.stat().st_size > 5 * 1024**2:
        raise LocalPostgresError(f"Expected an owned regular file: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise LocalPostgresError(f"Invalid ownership/provenance file: {path}") from error
    if not isinstance(value, dict):
        raise LocalPostgresError(f"Invalid ownership/provenance object: {path}")
    return value


def _write_json(path: Path, value: dict[str, Any], *, replace: bool = False) -> None:
    temporary = path.parent / f".{path.name}-{uuid.uuid4().hex}.tmp"
    with temporary.open("x", encoding="utf-8") as output:
        json.dump(value, output, indent=2, sort_keys=True)
        output.write("\n")
    if replace:
        _reject_link(path)
        temporary.replace(path)
    else:
        temporary.rename(path)


def _check_cache_entries(cache: Path) -> None:
    known = {"ownership.json", "provenance.json", "install.lock", "archive.zip", "runtime"}
    generated = re.compile(
        r"(?:cluster|extract)-[0-9a-f]{32}|download-[0-9a-f]{32}\.part|"
        r"\.(?:ownership|provenance)\.json-[0-9a-f]{32}\.tmp\Z"
    )
    for entry in cache.iterdir():
        _reject_link(entry)
        if entry.name not in known and not generated.fullmatch(entry.name):
            raise LocalPostgresError(f"Unrecognized cache entry was preserved: {entry.name}")


def _owned_cache() -> Path:
    if not TEMP_PARENT.is_dir():
        raise LocalPostgresError(f"The pre-approved temporary parent is absent: {TEMP_PARENT}")
    _reject_link(TEMP_PARENT)
    if CACHE_DIRECTORY.parent != TEMP_PARENT:
        raise LocalPostgresError("The cache must be directly under the pre-approved parent.")
    expected = {
        "tool": _TOOL_ID,
        "cache_format": _CACHE_FORMAT,
        "version": VERSION,
        "build": BUILD,
        "archive_url": ARCHIVE_URL,
    }
    try:
        CACHE_DIRECTORY.mkdir(mode=0o700)
    except FileExistsError:
        _reject_link(CACHE_DIRECTORY)
        marker = CACHE_DIRECTORY / "ownership.json"
        if not marker.is_file() or _read_json(marker) != expected:
            raise LocalPostgresError(
                f"Refusing an existing cache without matching ownership: {CACHE_DIRECTORY}"
            ) from None
    else:
        _write_json(CACHE_DIRECTORY / "ownership.json", expected)
    _check_cache_entries(CACHE_DIRECTORY)
    return CACHE_DIRECTORY


@contextlib.contextmanager
def _installation_lock(cache: Path) -> Iterator[None]:
    import msvcrt

    path = cache / "install.lock"
    if path.exists():
        _reject_link(path)
    with path.open("a+b", buffering=0) as handle:
        deadline = time.monotonic() + 60
        while True:
            handle.seek(0)
            try:
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                break
            except OSError as error:
                if time.monotonic() >= deadline:
                    raise LocalPostgresError("Cache installation lock exceeded 60s.") from error
                time.sleep(0.1)
        try:
            handle.seek(0)
            content = handle.read(2)
            if content not in (b"", b"\0"):
                raise LocalPostgresError("Refusing an unrecognized installation lock file.")
            if not content:
                handle.write(b"\0")
                handle.flush()
            yield
        finally:
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)


def _sha256(path: Path) -> str:
    _reject_link(path)
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024**2), b""):
            digest.update(chunk)
    return digest.hexdigest()


class _OfficialRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(
        self, req: Any, fp: Any, code: int, msg: str, headers: Any, newurl: str,
    ) -> Any:
        raise LocalPostgresError("The verified archive URL redirected; no other source was used.")


def _download_archive(cache: Path) -> dict[str, Any]:
    archive = cache / "archive.zip"
    if archive.exists():
        raise LocalPostgresError("An archive without recorded provenance exists; it was preserved.")
    partial = cache / f"download-{uuid.uuid4().hex}.part"
    opener = urllib.request.build_opener(
        _OfficialRedirectHandler(),
        urllib.request.HTTPSHandler(context=ssl.create_default_context()),
    )
    request = urllib.request.Request(
        ARCHIVE_URL, headers={"User-Agent": "SupplyOS-local-postgres/1"}
    )
    started = time.monotonic()
    digest, count = hashlib.sha256(), 0
    with opener.open(request, timeout=60) as response, partial.open("xb") as output:
        if response.status != 200 or response.geturl() != ARCHIVE_URL:
            raise LocalPostgresError("The verified HTTPS source returned an unexpected response.")
        length = response.headers.get("Content-Length")
        if length is not None and int(length) != EXPECTED_ARCHIVE_BYTES:
            raise LocalPostgresError("Archive Content-Length changed; download was not trusted.")
        for chunk in iter(lambda: response.read(1024**2), b""):
            count += len(chunk)
            if count > EXPECTED_ARCHIVE_BYTES or time.monotonic() - started > 1200:
                raise LocalPostgresError("Archive exceeded the verified size or download deadline.")
            output.write(chunk)
            digest.update(chunk)
    if count != EXPECTED_ARCHIVE_BYTES:
        raise LocalPostgresError(f"Incomplete archive: {count} of {EXPECTED_ARCHIVE_BYTES} bytes.")
    record = {
        "tool": _TOOL_ID,
        "cache_format": _CACHE_FORMAT,
        "version": VERSION,
        "build": BUILD,
        "archive_url": ARCHIVE_URL,
        "effective_url": ARCHIVE_URL,
        "downloaded_at_utc": datetime.now(timezone.utc).isoformat(),
        "archive_bytes": count,
        "archive_sha256": digest.hexdigest(),
        "checksum_verification": _CHECKSUM_STATUS,
        "state": "downloaded",
    }
    partial.rename(archive)
    _write_json(cache / "provenance.json", record)
    return record


def _archive_parts(info: zipfile.ZipInfo) -> tuple[str, ...]:
    name = info.orig_filename
    if (
        not name or name.startswith("/") or name != info.filename
        or any(character in name for character in '\\:<>"|?*')
        or any(ord(character) < 32 for character in name)
    ):
        raise LocalPostgresError("Unsafe archive path; extraction was refused.")
    parts = tuple((name[:-1] if name.endswith("/") else name).split("/"))
    reserved = {
        "con", "prn", "aux", "nul", "conin$", "conout$",
        *(f"com{i}" for i in range(1, 10)), *(f"lpt{i}" for i in range(1, 10)),
        *(f"com{i}" for i in ("\u00b9", "\u00b2", "\u00b3")),
        *(f"lpt{i}" for i in ("\u00b9", "\u00b2", "\u00b3")),
    }
    for part in parts:
        if not part or part in (".", "..") or part.endswith((" ", ".")):
            raise LocalPostgresError("Unsafe archive path component; extraction was refused.")
        if part.split(".", 1)[0].rstrip(" ").casefold() in reserved:
            raise LocalPostgresError("Windows device path in archive; extraction was refused.")
    kind = stat.S_IFMT(info.external_attr >> 16)
    if kind not in (0, stat.S_IFREG, stat.S_IFDIR) or info.external_attr & 0x400:
        raise LocalPostgresError("Archive symlink/reparse/special entry; extraction was refused.")
    if kind == stat.S_IFDIR and not info.is_dir() or kind == stat.S_IFREG and info.is_dir():
        raise LocalPostgresError("Inconsistent archive file/directory metadata was refused.")
    return parts


def _is_license_file(parts: tuple[str, ...]) -> bool:
    leaf = parts[-1].casefold()
    license_name = leaf.startswith((
        "license", "licence", "copyright", "legalnotice", "third_party_licenses",
    ))
    suffixes = ("", ".txt", ".html", ".htm", ".md", ".rst", ".rtf")
    if not license_name or Path(leaf).suffix not in suffixes:
        return False
    return len(parts) == 1 or parts[0] == "pgsql" and (
        len(parts) == 2 or parts[1] in ("bin", "lib", "share", "doc", "licenses", "licences")
    )


def _selected_archive_file(parts: tuple[str, ...]) -> bool:
    if len(parts) >= 3 and parts[0] == "pgsql":
        if parts[1] in ("lib", "share"):
            return True
        if parts[1] == "bin" and len(parts) == 3:
            return parts[2].casefold() in _REQUIRED_BINARIES or parts[2].casefold().endswith(".dll")
    return _is_license_file(parts)


def _selected_entries(
    archive: zipfile.ZipFile,
) -> list[tuple[zipfile.ZipInfo, tuple[str, ...]]]:
    entries = archive.infolist()
    if len(entries) > 100_000:
        raise LocalPostgresError("Unexpectedly large archive file list.")
    seen, selected, total = set(), [], 0
    for info in entries:
        parts = _archive_parts(info)
        normalized = "/".join(parts).casefold()
        if normalized in seen:
            raise LocalPostgresError("Duplicate Windows archive path; extraction was refused.")
        seen.add(normalized)
        if not info.is_dir() and _selected_archive_file(parts):
            total += info.file_size
            if total > _MAX_EXTRACTED_BYTES:
                raise LocalPostgresError("Selected archive files exceed the extraction size limit.")
            selected.append((info, parts))
    return selected


def _extract_member(
    archive: zipfile.ZipFile, info: zipfile.ZipInfo, target: Path,
) -> dict[str, Any]:
    target.parent.mkdir(parents=True, exist_ok=True)
    digest, count = hashlib.sha256(), 0
    with archive.open(info) as source, target.open("xb") as output:
        for chunk in iter(lambda: source.read(1024**2), b""):
            count += len(chunk)
            if count > info.file_size:
                raise LocalPostgresError("Archive member exceeded its declared size.")
            output.write(chunk)
            digest.update(chunk)
    if count != info.file_size:
        raise LocalPostgresError("Archive member is incomplete.")
    return {"bytes": count, "sha256": digest.hexdigest()}


def _extract_archive(cache: Path) -> dict[str, dict[str, Any]]:
    destination = cache / "runtime"
    if destination.exists():
        raise LocalPostgresError("Unrecorded runtime directory exists; it was not overwritten.")
    staging = cache / f"extract-{uuid.uuid4().hex}"
    staging.mkdir(mode=0o700)
    manifest: dict[str, dict[str, Any]] = {}
    with zipfile.ZipFile(cache / "archive.zip") as archive:
        for info, parts in _selected_entries(archive):
            target = staging.joinpath(*parts)
            manifest["/".join(parts)] = _extract_member(archive, info, target)
    for name in _REQUIRED_BINARIES:
        if f"pgsql/bin/{name}" not in manifest:
            raise LocalPostgresError(f"Required native executable is missing: {name}")
    if "pgsql/share/postgres.bki" not in manifest:
        raise LocalPostgresError("Required PostgreSQL bootstrap catalog is missing.")
    staging.rename(destination)
    return manifest


def _validate_provenance(cache: Path) -> dict[str, Any]:
    record = _read_json(cache / "provenance.json")
    expected = (_TOOL_ID, _CACHE_FORMAT, VERSION, BUILD, ARCHIVE_URL, EXPECTED_ARCHIVE_BYTES)
    actual = tuple(record.get(key) for key in (
        "tool", "cache_format", "version", "build", "archive_url", "archive_bytes"
    ))
    if actual != expected or record.get("effective_url") != ARCHIVE_URL:
        raise LocalPostgresError("Cache provenance does not match the verified official archive.")
    if record.get("checksum_verification") != _CHECKSUM_STATUS:
        raise LocalPostgresError("Checksum evidence must remain explicitly local and unsigned.")
    digest = record.get("archive_sha256")
    if not isinstance(digest, str) or not _SHA256_PATTERN.fullmatch(digest):
        raise LocalPostgresError("Recorded archive SHA256 is invalid.")
    archive = cache / "archive.zip"
    _reject_link(archive)
    if archive.stat().st_size != EXPECTED_ARCHIVE_BYTES or _sha256(archive) != digest:
        raise LocalPostgresError("Cached archive differs from local provenance; it was preserved.")
    return record


def _validate_runtime(cache: Path, manifest: dict[str, Any]) -> None:
    runtime = cache / "runtime"
    _reject_link(runtime)
    if not manifest or not isinstance(manifest, dict):
        raise LocalPostgresError("Missing extracted-file integrity manifest.")
    if _tree_files(runtime) != set(manifest):
        raise LocalPostgresError("Unexpected/missing runtime files; no files were replaced.")
    for name, entry in manifest.items():
        parts = _archive_parts(zipfile.ZipInfo(name))
        if not _selected_archive_file(parts) or not isinstance(entry, dict):
            raise LocalPostgresError("Unexpected entry in the runtime manifest.")
        target = runtime.joinpath(*parts)
        for parent in target.parents:
            if parent == cache:
                break
            _reject_link(parent)
        _reject_link(target)
        if target.stat().st_size != entry.get("bytes") or _sha256(target) != entry.get("sha256"):
            raise LocalPostgresError(f"Native file failed local integrity verification: {name}")
    for name in _REQUIRED_BINARIES:
        if f"pgsql/bin/{name}" not in manifest:
            raise LocalPostgresError(f"Runtime manifest lacks {name}.")
    if "pgsql/share/postgres.bki" not in manifest:
        raise LocalPostgresError("Runtime manifest lacks the PostgreSQL bootstrap catalog.")


def _complete_licenses(cache: Path, record: dict[str, Any]) -> None:
    """Complete license extraction from the already verified archive, never replace native files."""
    manifest = record["files"]
    with zipfile.ZipFile(cache / "archive.zip") as archive:
        selected = _selected_entries(archive)
        names = {"/".join(parts) for _, parts in selected}
        if set(manifest) - names:
            raise LocalPostgresError("Runtime manifest includes files outside the whitelist.")
        missing = [(info, parts) for info, parts in selected if "/".join(parts) not in manifest]
        if any(not _is_license_file(parts) for _, parts in missing):
            raise LocalPostgresError("The native file manifest is incomplete; cache was preserved.")
        if missing:
            staging = cache / f"extract-{uuid.uuid4().hex}"
            staging.mkdir(mode=0o700)
            for info, parts in missing:
                name = "/".join(parts)
                temporary = staging.joinpath(*parts)
                entry = _extract_member(archive, info, temporary)
                target = (cache / "runtime").joinpath(*parts)
                target.parent.mkdir(parents=True, exist_ok=True)
                for parent in target.parents:
                    if parent == cache:
                        break
                    _reject_link(parent)
                temporary.rename(target)
                manifest[name] = entry
            _write_json(cache / "provenance.json", record, replace=True)
            _tree_files(staging)
            shutil.rmtree(staging)


def ensure_installed() -> Installation:
    """Download once from the fixed verified source and reuse only an intact owned cache.

    Partial downloads/extractions are retained on failure. Existing unowned paths,
    redirects, and changed source sizes are refused rather than repaired or replaced.
    This function uses only the standard library and never starts a database server.
    """
    _require_windows()
    cache = _owned_cache()
    with _installation_lock(cache):
        provenance = cache / "provenance.json"
        record = _validate_provenance(cache) if provenance.exists() else _download_archive(cache)
        if record.get("state") == "downloaded":
            record["files"] = _extract_archive(cache)
            record["state"] = "installed"
            record["installed_at_utc"] = datetime.now(timezone.utc).isoformat()
            _write_json(provenance, record, replace=True)
        if record.get("state") != "installed":
            raise LocalPostgresError("Unrecognized cache installation state.")
        manifest = record.get("files")
        _validate_runtime(cache, manifest)
        _complete_licenses(cache, record)
    return Installation(
        version=VERSION,
        build=BUILD,
        cache_directory=cache,
        binary_directory=cache / "runtime" / "pgsql" / "bin",
        archive_url=ARCHIVE_URL,
        archive_bytes=record["archive_bytes"],
        archive_sha256=record["archive_sha256"],
        extracted_files=len(manifest),
        extracted_bytes=sum(entry["bytes"] for entry in manifest.values()),
        checksum_verification=record["checksum_verification"],
        license_files=tuple(name for name in manifest if _is_license_file(tuple(name.split("/")))),
    )


class _BasicLimits(ctypes.Structure):
    _fields_ = [
        ("PerProcessUserTimeLimit", ctypes.c_int64),
        ("PerJobUserTimeLimit", ctypes.c_int64),
        ("LimitFlags", ctypes.c_uint32),
        ("MinimumWorkingSetSize", ctypes.c_size_t),
        ("MaximumWorkingSetSize", ctypes.c_size_t),
        ("ActiveProcessLimit", ctypes.c_uint32),
        ("Affinity", ctypes.c_size_t),
        ("PriorityClass", ctypes.c_uint32),
        ("SchedulingClass", ctypes.c_uint32),
    ]


class _IoCounters(ctypes.Structure):
    _fields_ = [(name, ctypes.c_uint64) for name in (
        "ReadOperationCount", "WriteOperationCount", "OtherOperationCount",
        "ReadTransferCount", "WriteTransferCount", "OtherTransferCount",
    )]


class _ExtendedLimits(ctypes.Structure):
    _fields_ = [
        ("BasicLimitInformation", _BasicLimits),
        ("IoInfo", _IoCounters),
        ("ProcessMemoryLimit", ctypes.c_size_t),
        ("JobMemoryLimit", ctypes.c_size_t),
        ("PeakProcessMemoryUsed", ctypes.c_size_t),
        ("PeakJobMemoryUsed", ctypes.c_size_t),
    ]


class _Accounting(ctypes.Structure):
    _fields_ = [
        ("TotalUserTime", ctypes.c_int64),
        ("TotalKernelTime", ctypes.c_int64),
        ("ThisPeriodTotalUserTime", ctypes.c_int64),
        ("ThisPeriodTotalKernelTime", ctypes.c_int64),
        ("TotalPageFaultCount", ctypes.c_uint32),
        ("TotalProcesses", ctypes.c_uint32),
        ("ActiveProcesses", ctypes.c_uint32),
        ("TotalTerminatedProcesses", ctypes.c_uint32),
    ]


class _ThreadEntry(ctypes.Structure):
    _fields_ = [
        ("dwSize", ctypes.c_uint32),
        ("cntUsage", ctypes.c_uint32),
        ("th32ThreadID", ctypes.c_uint32),
        ("th32OwnerProcessID", ctypes.c_uint32),
        ("tpBasePri", ctypes.c_int32),
        ("tpDeltaPri", ctypes.c_int32),
        ("dwFlags", ctypes.c_uint32),
    ]


class _SecurityAttributes(ctypes.Structure):
    _fields_ = [
        ("nLength", ctypes.c_uint32),
        ("lpSecurityDescriptor", ctypes.c_void_p),
        ("bInheritHandle", ctypes.c_int32),
    ]


class _WindowsJob:
    """Own the complete native child tree, including abrupt Python-parent termination."""

    def __init__(self) -> None:
        _require_windows()
        self._kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        self._handle: int | None = None
        self._bind_functions()
        self._handle = self._kernel.CreateJobObjectW(None, None)
        if not self._handle:
            raise ctypes.WinError(ctypes.get_last_error())
        limits = _ExtendedLimits()
        limits.BasicLimitInformation.LimitFlags = 0x2000  # KILL_ON_JOB_CLOSE, no breakaway.
        if not self._kernel.SetInformationJobObject(
            self._handle, 9, ctypes.byref(limits), ctypes.sizeof(limits)
        ):
            error = ctypes.WinError(ctypes.get_last_error())
            self.close()
            raise error

    def _bind_functions(self) -> None:
        pointer, word, boolean = ctypes.c_void_p, ctypes.c_uint32, ctypes.c_int32
        signatures = {
            "CreateJobObjectW": ([pointer, ctypes.c_wchar_p], pointer),
            "SetInformationJobObject": ([pointer, word, pointer, word], boolean),
            "QueryInformationJobObject": ([pointer, word, pointer, word, pointer], boolean),
            "AssignProcessToJobObject": ([pointer, pointer], boolean),
            "TerminateJobObject": ([pointer, word], boolean),
            "OpenProcess": ([word, boolean, word], pointer),
            "IsProcessInJob": ([pointer, pointer, pointer], boolean),
            "CloseHandle": ([pointer], boolean),
            "CreateToolhelp32Snapshot": ([word, word], pointer),
            "Thread32First": ([pointer, pointer], boolean),
            "Thread32Next": ([pointer, pointer], boolean),
            "OpenThread": ([word, boolean, word], pointer),
            "ResumeThread": ([pointer], word),
            "CreateDirectoryW": ([ctypes.c_wchar_p, pointer], boolean),
            "LocalFree": ([pointer], pointer),
        }
        for name, (arguments, result) in signatures.items():
            function = getattr(self._kernel, name)
            function.argtypes, function.restype = arguments, result

    def _attach(self, pid: int) -> None:
        handle = self._kernel.OpenProcess(0x0101, False, pid)
        if not handle:
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            if not self._kernel.AssignProcessToJobObject(self._handle, handle):
                raise ctypes.WinError(ctypes.get_last_error())
        finally:
            self._kernel.CloseHandle(handle)

    def _resume(self, pid: int) -> None:
        snapshot = self._kernel.CreateToolhelp32Snapshot(0x0004, 0)
        if snapshot == ctypes.c_void_p(-1).value:
            raise ctypes.WinError(ctypes.get_last_error())
        entry = _ThreadEntry()
        entry.dwSize = ctypes.sizeof(entry)
        try:
            available = self._kernel.Thread32First(snapshot, ctypes.byref(entry))
            while available:
                if entry.th32OwnerProcessID == pid:
                    thread = self._kernel.OpenThread(0x0002, False, entry.th32ThreadID)
                    if not thread:
                        raise ctypes.WinError(ctypes.get_last_error())
                    try:
                        if self._kernel.ResumeThread(thread) == 0xFFFFFFFF:
                            raise ctypes.WinError(ctypes.get_last_error())
                        return
                    finally:
                        self._kernel.CloseHandle(thread)
                available = self._kernel.Thread32Next(snapshot, ctypes.byref(entry))
            raise LocalPostgresError("The owned suspended child's primary thread was not found.")
        finally:
            self._kernel.CloseHandle(snapshot)

    def launch(
        self, command: list[str], *, environment: dict[str, str], output: Any,
        cwd: Path | None = None,
    ) -> subprocess.Popen[str]:
        # Assign before resuming so no PostgreSQL descendant can escape ownership at startup.
        process = subprocess.Popen(
            command,
            stdin=subprocess.DEVNULL,
            stdout=output,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=environment,
            cwd=cwd,
            creationflags=0x0004 | subprocess.CREATE_NO_WINDOW,
        )
        try:
            self._attach(process.pid)
            self._resume(process.pid)
        except BaseException:
            process.kill()
            process.wait(timeout=5)
            raise
        return process

    def make_private_directory(self, path: Path) -> None:
        """Set a private DACL at creation only, never change an existing path's permissions."""
        security = ctypes.WinDLL("advapi32", use_last_error=True)
        convert = security.ConvertStringSecurityDescriptorToSecurityDescriptorW
        convert.argtypes = [ctypes.c_wchar_p, ctypes.c_uint32, ctypes.c_void_p, ctypes.c_void_p]
        convert.restype = ctypes.c_int32
        descriptor = ctypes.c_void_p()
        if not convert("D:P(A;OICI;FA;;;OW)(A;OICI;FA;;;SY)", 1, ctypes.byref(descriptor), None):
            raise ctypes.WinError(ctypes.get_last_error())
        attributes = _SecurityAttributes(ctypes.sizeof(_SecurityAttributes), descriptor, False)
        try:
            if not self._kernel.CreateDirectoryW(str(path), ctypes.byref(attributes)):
                raise ctypes.WinError(ctypes.get_last_error())
        finally:
            self._kernel.LocalFree(descriptor)

    def contains(self, pid: int) -> bool:
        handle = self._kernel.OpenProcess(0x1000, False, pid)
        if not handle:
            return False
        result = ctypes.c_int32()
        try:
            if not self._kernel.IsProcessInJob(handle, self._handle, ctypes.byref(result)):
                raise ctypes.WinError(ctypes.get_last_error())
            return bool(result.value)
        finally:
            self._kernel.CloseHandle(handle)

    def terminate(self) -> None:
        if self._handle and not self._kernel.TerminateJobObject(self._handle, 1):
            raise ctypes.WinError(ctypes.get_last_error())

    def wait_empty(self, *, timeout: float) -> bool:
        deadline = time.monotonic() + timeout
        while True:
            accounting = _Accounting()
            if not self._kernel.QueryInformationJobObject(
                self._handle, 1, ctypes.byref(accounting), ctypes.sizeof(accounting), None
            ):
                raise ctypes.WinError(ctypes.get_last_error())
            if accounting.ActiveProcesses == 0:
                return True
            if time.monotonic() >= deadline:
                return False
            time.sleep(0.05)

    def close(self) -> None:
        if self._handle:
            self._kernel.CloseHandle(self._handle)
            self._handle = None


class OwnedProcessGroup:
    """Bounded verification children in a kill-on-close Windows Job."""

    def __init__(self) -> None:
        self._job = _WindowsJob()

    def __enter__(self) -> OwnedProcessGroup:
        return self

    def launch(
        self, command: list[str], *, environment: dict[str, str], output: Any,
        cwd: Path | None = None,
    ) -> subprocess.Popen[str]:
        return self._job.launch(command, environment=environment, output=output, cwd=cwd)

    def run(
        self, command: list[str], *, environment: dict[str, str], output: Any,
        cwd: Path | None = None, timeout: float, check: bool = False,
    ) -> subprocess.CompletedProcess[str]:
        process = self.launch(command, environment=environment, output=output, cwd=cwd)
        try:
            returncode = process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            self.terminate()
            raise LocalPostgresError("Owned verification subprocess exceeded its deadline") from None
        if check and returncode:
            raise LocalPostgresError(f"Owned verification subprocess failed (exit {returncode})")
        return subprocess.CompletedProcess(command, returncode)

    def terminate(self) -> None:
        self._job.terminate()
        if not self._job.wait_empty(timeout=10):
            raise LocalPostgresError("Owned verification process tree did not stop")

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        try:
            self.terminate()
        finally:
            self._job.close()


def _tree_files(root: Path) -> set[str]:
    """Enumerate without following reparse points before trusting or deleting an owned tree."""
    _reject_link(root)
    pending, files = [root], set()
    while pending:
        with os.scandir(pending.pop()) as entries:
            for entry in entries:
                path = Path(entry.path)
                _reject_link(path)
                if entry.is_dir(follow_symlinks=False):
                    pending.append(path)
                elif entry.is_file(follow_symlinks=False):
                    files.add(path.relative_to(root).as_posix())
                else:
                    raise LocalPostgresError(f"Unexpected special file in an owned tree: {path}")
    return files


def _reserve_port() -> socket.socket:
    for _ in range(64):
        reservation = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        reservation.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        try:
            reservation.bind(("127.0.0.1", 49152 + secrets.randbelow(16384)))
        except OSError:
            reservation.close()
            continue
        return reservation
    raise LocalPostgresError("No free loopback port in the high ephemeral range was found.")


class _PrivateUrl(str):
    def __repr__(self) -> str:
        return "<private PostgreSQL connection URL>"


class LocalPostgres:
    """Synchronous context manager for one new, privately authenticated test cluster.

    Use ``with LocalPostgres() as pg:`` around migration/test work (including
    ``asyncio.run``). ``pg.async_url`` and ``pg.sync_url`` are SQLAlchemy URLs;
    ``pg.dsn`` is a driver/libpq URL. All contain GENERATED credentials and must
    stay private. No environment, application schema, or existing DB is changed.
    Close caller-owned connections/engines before leaving the context. Native
    descendants are owned by a non-inherited Windows kill-on-close Job Object.
    """

    __slots__ = (
        "_port", "_database", "_installation", "_username", "_password", "_root",
        "_owner", "_job", "_server_pid", "_state", "_shutdown_mode",
    )

    def __init__(self) -> None:
        self._port = 0
        self._database = f"supplyos_test_{uuid.uuid4().hex}"
        self._installation: Installation | None = None
        self._username = f"supplyos_test_admin_{secrets.token_hex(8)}"
        self._password = secrets.token_urlsafe(32)
        self._root: Path | None = None
        self._owner = uuid.uuid4().hex
        self._job: _WindowsJob | None = None
        self._server_pid: int | None = None
        self._state = "new"
        self._shutdown_mode = "not-started"

    @property
    def host(self) -> str:
        """Loopback-only address; never configurable."""
        return "127.0.0.1"

    @property
    def port(self) -> int:
        """Fresh high TCP port reserved for this context."""
        return self._port

    @property
    def database(self) -> str:
        """Generated, explicitly prefixed test database name."""
        return self._database

    @property
    def installation(self) -> Installation | None:
        """Non-secret installation receipt after initialization."""
        return self._installation

    def __repr__(self) -> str:
        return (
            f"<LocalPostgres state={self._state!r} host={self.host!r} "
            f"port={self.port} database={self.database!r} credentials=<private>>"
        )

    @property
    def data_directory(self) -> Path:
        if self._root is None:
            raise LocalPostgresError("The cluster has not been initialized.")
        return self._root / "data"

    def _redact(self, message: str) -> str:
        if self._password:
            message = message.replace(self._password, "<private>")
            message = message.replace(quote(self._password, safe=""), "<private>")
        return re.sub(r"(postgresql(?:\+\w+)?://)[^/@\s]+@", r"\1<private>@", message)

    def _environment(self) -> dict[str, str]:
        assert self.installation is not None and self._root is not None
        allowed = ("SystemRoot", "WINDIR", "COMSPEC", "SystemDrive", "USERPROFILE", "LOCALAPPDATA")
        environment = {key: os.environ[key] for key in allowed if key in os.environ}
        system_directory = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32"
        binary_directory = self.installation.binary_directory
        environment["PATH"] = os.pathsep.join(map(str, (
            binary_directory, binary_directory.parent / "lib", system_directory,
        )))
        environment.update(TEMP=str(self._root), TMP=str(self._root), TZ="UTC", LC_ALL="C")
        return environment

    def _run_binary(self, name: str, arguments: list[str], *, timeout: float) -> str:
        assert self._job is not None and self.installation is not None and self._root is not None
        command = [str(self.installation.binary_directory / name), *arguments]
        capture = self._root / f"native-{Path(name).stem}-{uuid.uuid4().hex}.log"
        # pg_ctl descendants can inherit pipe writers; waiting on pipe EOF can outlive pg_ctl.
        with capture.open("x", encoding="utf-8") as output_file:
            process = self._job.launch(command, environment=self._environment(), output=output_file)
            try:
                process.wait(timeout=timeout)
            except subprocess.TimeoutExpired as error:
                self._job.terminate()
                process.wait(timeout=5)
                detail = self._redact(capture.read_text(encoding="utf-8", errors="replace")[-2500:])
                raise LocalPostgresError(f"{name} exceeded {timeout}s: {detail.strip()}") from error
            except BaseException:
                self._job.terminate()
                process.wait(timeout=5)
                raise
        output = capture.read_text(encoding="utf-8", errors="replace")
        if process.returncode:
            code = process.returncode & 0xFFFFFFFF
            hints = {
                0xC0000135: "A native runtime DLL is unavailable; no system runtime was installed.",
                0xC000007B: "The native executable/runtime has an incompatible architecture.",
                0xC0000142: "Native DLL initialization failed; no system permissions were changed.",
            }
            raise LocalPostgresError(
                f"{name} exited 0x{code:08x}. {hints.get(code, '')} "
                f"{self._redact(output[-2500:]).strip()}"
            )
        return output

    def _initialize(self) -> None:
        assert self._root is not None
        password_file = self._root / "bootstrap-password"
        with password_file.open("x", encoding="ascii") as output:
            output.write(self._password + "\n")
        try:
            # Skip initial catalog fsync only; the disposable server retains durable settings.
            self._run_binary("initdb.exe", [
                "-D", str(self.data_directory), "--username", self._username,
                "--pwfile", str(password_file), "--auth=scram-sha-256",
                "--encoding=UTF8", "--locale=C", "--no-instructions", "--no-sync",
            ], timeout=120)
        finally:
            password_file.unlink(missing_ok=True)

    def _configure(self) -> None:
        configuration = (
            "\n# Owned disposable verification cluster, never a production configuration.\n"
            f"listen_addresses = '127.0.0.1'\nport = {self.port}\n"
            "unix_socket_directories = ''\nssl = off\npassword_encryption = 'scram-sha-256'\n"
            "shared_buffers = '32MB'\nmax_connections = 40\ntimezone = 'UTC'\n"
            "fsync = on\nsynchronous_commit = on\nfull_page_writes = on\n"
            "logging_collector = off\nlog_statement = 'none'\n"
            "log_min_error_statement = 'panic'\nlog_connections = off\nlog_disconnections = off\n"
        )
        with (self.data_directory / "postgresql.conf").open("a", encoding="utf-8") as output:
            output.write(configuration)
        (self.data_directory / "pg_hba.conf").write_text(
            f"host all {self._username} 127.0.0.1/32 scram-sha-256\n"
            "host all all 0.0.0.0/0 reject\nhost all all ::/0 reject\n",
            encoding="ascii",
        )

    def _check_cluster_owner(self) -> None:
        assert self.installation is not None and self._root is not None
        if (
            self._root.parent != self.installation.cache_directory
            or not re.fullmatch(r"cluster-[0-9a-f]{32}", self._root.name)
        ):
            raise LocalPostgresError("Refusing a cluster outside the owned cache.")
        _reject_link(self._root)
        expected = {"tool": _TOOL_ID, "owner": self._owner, "database": self.database}
        if _read_json(self._root / "ownership.json") != expected:
            raise LocalPostgresError("Cluster ownership changed; no cluster files were removed.")

    def _check_postmaster(self) -> int:
        self._check_cluster_owner()
        assert self._job is not None
        pid_file = self.data_directory / "postmaster.pid"
        _reject_link(pid_file)
        lines = pid_file.read_text(encoding="utf-8").splitlines()
        if len(lines) < 8:
            raise LocalPostgresError("Incomplete owned PostgreSQL PID file.")
        pid = int(lines[0])
        if (
            Path(lines[1]).resolve() != self.data_directory.resolve()
            or int(lines[3]) != self.port
            or lines[5] != self.host
            or lines[7].strip() != "ready"
            or not self._job.contains(pid)
        ):
            raise LocalPostgresError("The ready PostgreSQL process does not match this cluster.")
        return pid

    def _connect(
        self, database: str, *, autocommit: bool = False,
    ) -> psycopg2.extensions.connection:
        driver = importlib.import_module("psycopg2")
        self._check_postmaster()
        if database not in ("postgres", self.database):
            raise LocalPostgresError("Only the owned bootstrap and prefixed test DB are usable.")
        connection = driver.connect(
            host=self.host, port=self.port, user=self._username, password=self._password,
            dbname=database, sslmode="disable", connect_timeout=5,
            application_name="supplyos_local_postgres",
        )
        connection.autocommit = autocommit
        return connection

    def _create_database(self) -> None:
        from psycopg2 import sql

        with contextlib.closing(self._connect("postgres", autocommit=True)) as connection:
            with connection.cursor() as cursor:
                cursor.execute("SET statement_timeout = '10s'")
                cursor.execute("SELECT current_setting('data_directory'), inet_server_port()")
                directory, port = cursor.fetchone()
                if Path(directory).resolve() != self.data_directory.resolve() or port != self.port:
                    raise LocalPostgresError("Refusing to mutate a server outside this cluster.")
                cursor.execute(sql.SQL("CREATE DATABASE {} TEMPLATE template0").format(
                    sql.Identifier(self.database)
                ))

    def __enter__(self) -> LocalPostgres:
        if self._state != "new":
            raise LocalPostgresError("Each LocalPostgres instance can be entered only once.")
        _require_windows()
        try:
            importlib.import_module("psycopg2")
        except ModuleNotFoundError as error:
            raise LocalPostgresError(
                "Use backend/.venv after the core psycopg2 driver installation."
            ) from error
        self._state = "starting"
        try:
            self._installation = ensure_installed()
            self._job = _WindowsJob()
            root = self.installation.cache_directory / f"cluster-{uuid.uuid4().hex}"
            self._job.make_private_directory(root)
            self._root = root
            _write_json(root / "ownership.json", {
                "tool": _TOOL_ID, "owner": self._owner, "database": self.database,
            })
            atexit.register(self.close)
            with _reserve_port() as reservation:
                self._port = reservation.getsockname()[1]
                self._initialize()
                self._configure()
            self._run_binary("pg_ctl.exe", [
                "-D", str(self.data_directory), "-l", str(root / "server.log"),
                "-w", "-t", "45", "start",
            ], timeout=60)
            self._server_pid = self._check_postmaster()
            self._create_database()
            self._state = "running"
            return self
        except BaseException as error:
            try:
                self.close()
            except (LocalPostgresError, OSError) as cleanup_error:
                error.add_note(self._redact(f"Owned-cluster cleanup: {cleanup_error}"))
            raise

    def _url(self, scheme: str) -> str:
        if self._state != "running":
            raise LocalPostgresError("Connection URLs are available only inside the context.")
        return _PrivateUrl(
            f"{scheme}://{quote(self._username, safe='')}:{quote(self._password, safe='')}"
            f"@{self.host}:{self.port}/{self.database}"
        )

    @property
    def async_url(self) -> str:
        """Private SQLAlchemy/asyncpg URL; do not print or persist it."""
        return self._url("postgresql+asyncpg")

    @property
    def sync_url(self) -> str:
        """Private SQLAlchemy/psycopg2 URL; do not print or persist it."""
        return self._url("postgresql+psycopg2")

    @property
    def dsn(self) -> str:
        """Private libpq/driver URL; do not print or persist it."""
        return self._url("postgresql")

    def connect(self, *, autocommit: bool = False) -> psycopg2.extensions.connection:
        """Open a caller-owned synchronous connection to this test DB only."""
        if self._state != "running":
            raise LocalPostgresError("The isolated test cluster is not running.")
        return self._connect(self.database, autocommit=autocommit)

    def _stop_processes(self) -> None:
        if self._job is None:
            return
        try:
            if self._server_pid is not None and self._job.contains(self._server_pid):
                try:
                    self._check_postmaster()
                    self._run_binary("pg_ctl.exe", [
                        "-D", str(self.data_directory), "-w", "-t", "15", "-m", "fast", "stop",
                    ], timeout=20)
                    self._shutdown_mode = "fast"
                except (LocalPostgresError, OSError):
                    self._shutdown_mode = "job-termination"
                    self._job.terminate()
            else:
                self._shutdown_mode = "job-termination"
                self._job.terminate()
            if not self._job.wait_empty(timeout=10):
                self._shutdown_mode = "job-termination"
                self._job.terminate()
                if not self._job.wait_empty(timeout=10):
                    raise LocalPostgresError("Owned processes did not exit; cluster was preserved.")
        except BaseException:
            self._job.terminate()
            self._job.wait_empty(timeout=10)
            raise
        finally:
            self._job.close()
            self._job = None

    def close(self) -> None:
        """Stop only this job/cluster and remove only its marker-verified temporary tree."""
        if self._state == "closed":
            return
        try:
            self._stop_processes()
            if self._root is not None:
                self._check_cluster_owner()
                _tree_files(self._root)
                shutil.rmtree(self._root)
        finally:
            self._state = "closed"
            self._password = ""
            atexit.unregister(self.close)

    def __exit__(
        self, exception_type: type[BaseException] | None,
        exception: BaseException | None, traceback: TracebackType | None,
    ) -> None:
        try:
            self.close()
        except (LocalPostgresError, OSError) as cleanup_error:
            if exception is None:
                raise
            exception.add_note(self._redact(f"Owned-cluster cleanup: {cleanup_error}"))


@dataclass(frozen=True, slots=True)
class SelfCheckResult:
    """Real engine/lock smoke evidence, explicitly not application invariant coverage."""

    postgres_version: str
    database_prefix: str
    basic_query: int
    scram_authenticated: bool
    sync_url_query: int
    async_url_query: int
    lock_wait_event: str
    lock_timeout_sqlstate: str
    lock_timeout_seconds: float
    lock_acquired_after_rollback: bool
    cluster_stopped: bool
    cluster_removed: bool
    shutdown_mode: str
    application_invariants_verified: bool = False


def _waiter_timeout(connection: psycopg2.extensions.connection) -> tuple[str, float]:
    driver = importlib.import_module("psycopg2")
    started = time.monotonic()
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT id FROM supplyos_tooling_lock_probe WHERE id = 1 FOR UPDATE")
    except driver.Error as error:
        if error.pgcode != "55P03":
            raise LocalPostgresError(
                f"Expected a row-lock timeout, got SQLSTATE {error.pgcode}."
            ) from error
        return error.pgcode, time.monotonic() - started
    raise LocalPostgresError("A conflicting row lock did not block the second connection.")


def _observe_blocking(
    connection: psycopg2.extensions.connection, *, holder_pid: int, waiter_pid: int,
) -> None:
    deadline = time.monotonic() + 0.8
    with connection.cursor() as cursor:
        while time.monotonic() < deadline:
            cursor.execute(
                "SELECT pg_blocking_pids(pid), wait_event_type "
                "FROM pg_stat_activity WHERE pid = %s",
                (waiter_pid,),
            )
            row = cursor.fetchone()
            if row and holder_pid in row[0] and row[1] == "Lock":
                return
            time.sleep(0.02)
    raise LocalPostgresError("PostgreSQL did not report the expected live blocking relationship.")


def _check_row_lock(pg: LocalPostgres) -> tuple[str, float]:
    with contextlib.ExitStack() as stack:
        observer = stack.enter_context(contextlib.closing(pg.connect(autocommit=True)))
        holder = stack.enter_context(contextlib.closing(pg.connect()))
        waiter = stack.enter_context(contextlib.closing(pg.connect()))
        with observer.cursor() as cursor:
            cursor.execute("SET statement_timeout = '5s'")
            cursor.execute("CREATE TABLE supplyos_tooling_lock_probe (id int PRIMARY KEY)")
            cursor.execute("INSERT INTO supplyos_tooling_lock_probe VALUES (1)")
        with holder.cursor() as cursor:
            cursor.execute("SET LOCAL statement_timeout = '5s'")
            cursor.execute("SELECT pg_backend_pid()")
            holder_pid = cursor.fetchone()[0]
            cursor.execute("SELECT id FROM supplyos_tooling_lock_probe WHERE id = 1 FOR UPDATE")
        with waiter.cursor() as cursor:
            cursor.execute("SET LOCAL lock_timeout = '1s'")
            cursor.execute("SET LOCAL statement_timeout = '4s'")
            cursor.execute("SELECT pg_backend_pid()")
            waiter_pid = cursor.fetchone()[0]
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            pending = pool.submit(_waiter_timeout, waiter)
            _observe_blocking(observer, holder_pid=holder_pid, waiter_pid=waiter_pid)
            sqlstate, elapsed = pending.result(timeout=5)
        if elapsed < 0.5 or elapsed > 5:
            raise LocalPostgresError("The row-lock wait did not match a bounded timeout.")
        holder.rollback()
        waiter.rollback()
        with waiter.cursor() as cursor:
            cursor.execute("SET LOCAL lock_timeout = '1s'")
            cursor.execute("SELECT id FROM supplyos_tooling_lock_probe WHERE id = 1 FOR UPDATE")
            if cursor.fetchone() != (1,):
                raise LocalPostgresError("The released row lock could not be acquired.")
        waiter.rollback()
        return sqlstate, elapsed


async def _check_async_url(pg: LocalPostgres) -> int:
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine
    from sqlalchemy.pool import NullPool

    engine = create_async_engine(
        pg.async_url, hide_parameters=True, poolclass=NullPool,
        connect_args={"timeout": 5, "ssl": False, "server_settings": {"statement_timeout": "5000"}},
    )
    try:
        async with engine.connect() as connection:
            return int(await connection.scalar(text("SELECT 1")))
    finally:
        await engine.dispose()


def _check_sync_url(pg: LocalPostgres) -> int:
    from sqlalchemy import create_engine, text
    from sqlalchemy.pool import NullPool

    engine = create_engine(
        pg.sync_url, hide_parameters=True, poolclass=NullPool,
        connect_args={
            "connect_timeout": 5, "sslmode": "disable", "options": "-c statement_timeout=5000",
        },
    )
    try:
        with engine.connect() as connection:
            return int(connection.scalar(text("SELECT 1")))
    finally:
        engine.dispose()


def self_check() -> SelfCheckResult:
    """Prove a real query, SCRAM, URL drivers, blocking/timeout/recovery, and shutdown."""
    pg = LocalPostgres()
    password = pg._password
    try:
        with pg:
            with contextlib.closing(pg.connect(autocommit=True)) as connection:
                with connection.cursor() as cursor:
                    cursor.execute("SET statement_timeout = '5s'")
                    cursor.execute(
                        "SELECT version(), current_database(), current_setting('server_version'), 1"
                    )
                    version, database, server_version, query = cursor.fetchone()
                    cursor.execute(
                        "SELECT rolpassword LIKE 'SCRAM-SHA-256$%' "
                        "FROM pg_authid WHERE rolname = current_user"
                    )
                    scram = cursor.fetchone()[0]
            if server_version != VERSION or database != pg.database or not scram:
                raise LocalPostgresError(
                    f"Engine identity mismatch: version={server_version}, "
                    f"owned_database={database == pg.database}, scram_hash={bool(scram)}."
                )
            sync_query = _check_sync_url(pg)
            async_query = asyncio.run(_check_async_url(pg))
            sqlstate, elapsed = _check_row_lock(pg)
            root = pg.data_directory.parent
        if root.exists():
            raise LocalPostgresError("The owned temporary cluster was not removed after shutdown.")
        return SelfCheckResult(
            postgres_version=version, database_prefix="supplyos_test_", basic_query=query,
            scram_authenticated=scram, sync_url_query=sync_query, async_url_query=async_query,
            lock_wait_event="Lock", lock_timeout_sqlstate=sqlstate,
            lock_timeout_seconds=round(elapsed, 3), lock_acquired_after_rollback=True,
            cluster_stopped=True, cluster_removed=True,
            shutdown_mode=pg._shutdown_mode,
        )
    except Exception as error:
        message = pg._redact(f"Isolated PostgreSQL self-check failed: {error}")
        raise LocalPostgresError(message.replace(password, "<private>")) from error


def main() -> int:
    """Run finite installation or verification without outputting connection credentials."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("install", "self-check"))
    arguments = parser.parse_args()
    try:
        if arguments.command == "install":
            print(json.dumps(asdict(ensure_installed()), indent=2, default=str))
        else:
            print(json.dumps(asdict(self_check()), indent=2))
    except (LocalPostgresError, OSError, ValueError, zipfile.BadZipFile) as error:
        print(f"local-postgres: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
