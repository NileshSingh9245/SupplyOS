"""Private filesystem checks confined to newly owned approved-temp fixtures."""
from __future__ import annotations

import concurrent.futures
import ctypes
import json
import os
import shutil
import stat
import subprocess
import threading
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.infrastructure.storage import local as storage

_TEMP_PARENT = (
    Path(r"C:\Users\singh\AppData\Local\Temp\kilo") if os.name == "nt"
    else Path("/mnt/c/Users/singh/AppData/Local/Temp/kilo")
)
_KEY = "a" * 32 + ".png"
_DATA = b"private fixture bytes\x00\xff"


@pytest.fixture
def owned_directory():
    if not _TEMP_PARENT.is_dir():
        pytest.skip("The approved temporary parent is unavailable on this platform")
    root = _TEMP_PARENT / ("supplyos-private-storage-tests-" + uuid.uuid4().hex)
    storage.ensure_private_root(root)
    try:
        yield root
    finally:
        shutil.rmtree(root)


def _native_acl(path: Path) -> dict:
    executable = shutil.which("powershell.exe")
    if executable is None:
        pytest.skip("Independent native Windows ACL inspection is unavailable")
    literal = str(path).replace("'", "''")
    command = (
        "$ErrorActionPreference='Stop';"
        f"$acl=Get-Acl -LiteralPath '{literal}';"
        "$sidType=[System.Security.Principal.SecurityIdentifier];"
        "$rules=@($acl.Access | ForEach-Object { @{"
        "sid=$_.IdentityReference.Translate($sidType).Value;"
        "kind=$_.AccessControlType.ToString();"
        "rights=[int]$_.FileSystemRights;"
        "inheritance=[int]$_.InheritanceFlags;"
        "inherited=$_.IsInherited } });"
        "@{owner=$acl.GetOwner($sidType).Value;"
        "user=[System.Security.Principal.WindowsIdentity]::GetCurrent().User.Value;"
        "protected=$acl.AreAccessRulesProtected;sddl=$acl.Sddl;rules=$rules}"
        "| ConvertTo-Json -Depth 4 -Compress"
    )
    result = subprocess.run(
        [executable, "-NoProfile", "-NonInteractive", "-Command", command],
        capture_output=True, text=True, timeout=20,
    )
    assert result.returncode == 0, "Native ACL inspection failed"
    return json.loads(result.stdout)


def _snapshot(path: Path):
    return _native_acl(path)["sddl"] if os.name == "nt" else path.lstat()


def _existing_fixture(path: Path, *, directory: bool, grant: str | None = "FR", inherit_only: bool = False):
    """Create an intentionally unsafe NEW fixture, never change existing permissions."""
    if os.name != "nt":
        previous = os.umask(0)
        try:
            if directory:
                os.mkdir(path, 0o755)
            else:
                fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
                try:
                    os.write(fd, _DATA)
                finally:
                    os.close(fd)
        finally:
            os.umask(previous)
        return
    windows = storage._WindowsSecurity()
    flags = "OICI" if directory else ""
    stranger_flags = flags + ("IO" if inherit_only else "")
    sddl = f"O:{windows.sid}D:P(A;{flags};FA;;;{windows.sid})(A;{stranger_flags};{grant};;;WD)"
    if grant is None:
        sddl = f"O:{windows.sid}D:NO_ACCESS_CONTROL"
    descriptor = ctypes.c_void_p()
    assert windows.security.ConvertStringSecurityDescriptorToSecurityDescriptorW(
        sddl, 1, ctypes.byref(descriptor), None,
    ), "Native fixture descriptor creation failed"
    attributes = storage._SecurityAttributes(ctypes.sizeof(storage._SecurityAttributes), descriptor, False)
    try:
        if directory:
            assert windows.kernel.CreateDirectoryW(str(path), ctypes.byref(attributes)), "Fixture creation failed"
        else:
            handle = windows.kernel.CreateFileW(str(path), 0x40000000, 1, ctypes.byref(attributes), 1, 0x80, None)
            assert handle != ctypes.c_void_p(-1).value, "Fixture creation failed"
            try:
                windows.write(handle, _DATA)
            finally:
                windows.kernel.CloseHandle(handle)
    finally:
        windows.kernel.LocalFree(descriptor)


@pytest.mark.parametrize("extension", ["png", "jpg"])
def test_private_create_and_read(owned_directory, extension):
    root = owned_directory / "nested" / "proofs"
    key = "0" * 32 + "." + extension
    path = storage.create_private_file(root, key, _DATA)
    assert path == root / key
    assert storage.ensure_private_root(root) == root
    assert storage.checked_private_file(root, key) == path
    assert path.read_bytes() == _DATA
    if os.name == "posix":
        assert stat.S_IMODE(root.stat().st_mode) == 0o700
        assert stat.S_IMODE(path.stat().st_mode) == 0o600


@pytest.mark.parametrize("data", [b"", _DATA * 70000], ids=["empty", "multichunk"])
def test_empty_and_multichunk_binary_files_round_trip(owned_directory, data):
    root = owned_directory / "proofs"
    path = storage.create_private_file(root, _KEY, data)
    assert storage.checked_private_file(root, _KEY) == path
    assert path.read_bytes() == data


@pytest.mark.skipif(os.name != "nt", reason="Real Windows DACL inspection requires Windows")
def test_native_windows_owner_acl_and_directory_inheritance(owned_directory):
    root = storage.ensure_private_root(owned_directory / "proofs")
    path = storage.create_private_file(root, _KEY, _DATA)
    for target in (root, path):
        acl = _native_acl(target)
        assert acl["owner"] == acl["user"]
        assert acl["protected"] is True
        allowed = {acl["user"], "S-1-5-18", "S-1-5-32-544"}
        assert {rule["sid"] for rule in acl["rules"]} == allowed
        assert all(rule["kind"] == "Allow" and rule["rights"] == 0x1F01FF for rule in acl["rules"])
        if target == root:
            assert all(rule["inheritance"] == 3 for rule in acl["rules"])
    inherited = root / ("b" * 32 + ".jpg")
    with inherited.open("xb") as target:
        target.write(_DATA)
    acl = _native_acl(inherited)
    assert {rule["sid"] for rule in acl["rules"]} == {acl["user"], "S-1-5-18", "S-1-5-32-544"}
    assert all(rule["inherited"] for rule in acl["rules"])


@pytest.mark.parametrize("grant", ["FR", "FW"])
def test_unsafe_existing_store_is_refused_without_permission_changes(owned_directory, grant):
    root = owned_directory / "unrelated-store"
    _existing_fixture(root, directory=True, grant=grant)
    sentinel = root / "unrelated-file"
    with sentinel.open("xb") as target:
        target.write(_DATA)
    before = _snapshot(root)
    for operation in (
        lambda: storage.ensure_private_root(root),
        lambda: storage.create_private_file(root, _KEY, b"not written"),
        lambda: storage.checked_private_file(root, _KEY),
    ):
        with pytest.raises(RuntimeError):
            operation()
    assert _snapshot(root) == before
    assert sentinel.read_bytes() == _DATA
    assert not (root / _KEY).exists()


@pytest.mark.skipif(os.name != "nt", reason="Inheritance-only ACEs are a Windows ACL feature")
def test_existing_store_with_public_inheritance_only_grant_is_refused(owned_directory):
    root = owned_directory / "unsafe-inheritance"
    _existing_fixture(root, directory=True, inherit_only=True)
    before = _snapshot(root)
    with pytest.raises(RuntimeError):
        storage.ensure_private_root(root)
    assert _snapshot(root) == before


@pytest.mark.parametrize("grant", ["FR", "FW"])
def test_unsafe_existing_file_is_refused_and_preserved(owned_directory, grant):
    root = storage.ensure_private_root(owned_directory / "proofs")
    path = root / _KEY
    _existing_fixture(path, directory=False, grant=grant)
    before = _snapshot(path)
    with pytest.raises(RuntimeError):
        storage.checked_private_file(root, _KEY)
    with pytest.raises(RuntimeError):
        storage.create_private_file(root, _KEY, b"not written")
    assert _snapshot(path) == before
    assert path.read_bytes() == _DATA


@pytest.mark.skipif(os.name != "nt", reason="Null Windows DACLs grant unrestricted access")
def test_null_windows_file_dacl_is_refused_without_repair(owned_directory):
    root = storage.ensure_private_root(owned_directory / "proofs")
    path = root / _KEY
    _existing_fixture(path, directory=False, grant=None)
    before = _snapshot(path)
    with pytest.raises(RuntimeError):
        storage.checked_private_file(root, _KEY)
    assert _snapshot(path) == before
    assert path.read_bytes() == _DATA


def test_exclusive_create_never_overwrites_an_existing_private_file(owned_directory):
    root = owned_directory / "proofs"
    path = storage.create_private_file(root, _KEY, _DATA)
    with pytest.raises(RuntimeError):
        storage.create_private_file(root, _KEY, b"replacement")
    assert path.read_bytes() == _DATA


def test_concurrent_exclusive_create_has_one_winner(owned_directory):
    root = storage.ensure_private_root(owned_directory / "proofs")
    barrier = threading.Barrier(2)

    def create(data):
        barrier.wait(timeout=5)
        try:
            storage.create_private_file(root, _KEY, data)
            return data
        except RuntimeError:
            return None

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(create, (b"first", b"second")))
    winners = [result for result in results if result is not None]
    assert len(winners) == 1
    assert storage.checked_private_file(root, _KEY).read_bytes() == winners[0]


@pytest.mark.parametrize("key", [
    "../" + _KEY, "nested/" + _KEY, "nested\\" + _KEY, "/" + _KEY,
    "A" * 32 + ".png", "a" * 31 + ".png", "a" * 33 + ".png",
    "a" * 32 + ".jpeg", "a" * 32 + ".PNG", _KEY + ":stream", _KEY + "\n",
    _KEY + " ", _KEY + "\x00", "", None,
])
def test_noncanonical_keys_are_rejected_before_creating_a_store(owned_directory, key):
    root = owned_directory / "must-not-be-created"
    for operation in (
        lambda: storage.create_private_file(root, key, _DATA),
        lambda: storage.checked_private_file(root, key),
    ):
        with pytest.raises(RuntimeError) as error:
            operation()
        assert str(error.value) == "Private proof storage is unavailable."
        assert error.value.__cause__ is None
        assert error.value.__suppress_context__
    assert not root.exists()


def test_missing_read_and_invalid_data_do_not_create_directories(owned_directory):
    root = owned_directory / "must-not-be-created"
    with pytest.raises(RuntimeError):
        storage.checked_private_file(root, _KEY)
    with pytest.raises(RuntimeError):
        storage.create_private_file(root, _KEY, bytearray(_DATA))
    with pytest.raises(RuntimeError):
        storage.ensure_private_root(root / "unrelated" / ".." / "proofs")
    assert not root.exists()


@pytest.mark.skipif(os.name != "nt", reason="Windows namespace paths must not reach native file APIs")
@pytest.mark.parametrize("root", [
    r"\\invalid-fixture-host\share\proofs", r"\\?\C:\proofs", r"\\.\C:\proofs",
    r"C:\proofs:stream", r"C:\proofs.", r"C:\NUL\proofs", "C:\\",
])
def test_windows_ambiguous_and_nonlocal_paths_are_rejected_without_io(root, monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("A rejected namespace reached native filesystem APIs")

    monkeypatch.setattr(storage, "_WindowsSecurity", forbidden)
    with pytest.raises(RuntimeError):
        storage.ensure_private_root(Path(root))


def test_directories_and_hardlinked_files_are_not_accepted_as_proofs(owned_directory):
    root = storage.ensure_private_root(owned_directory / "proofs")
    storage.ensure_private_root(root / _KEY)
    with pytest.raises(RuntimeError):
        storage.checked_private_file(root, _KEY)
    key = "b" * 32 + ".jpg"
    path = storage.create_private_file(root, key, _DATA)
    try:
        os.link(path, owned_directory / "owned-alias")
    except OSError:
        pytest.skip("Creating owned fixture hardlinks is not permitted")
    with pytest.raises(RuntimeError):
        storage.checked_private_file(root, key)
    assert path.read_bytes() == _DATA


def test_symlink_store_ancestry_and_file_are_refused_if_permitted(owned_directory):
    target = storage.ensure_private_root(owned_directory / "target")
    path = storage.create_private_file(target, _KEY, _DATA)
    alias = owned_directory / "alias"
    try:
        alias.symlink_to(target, target_is_directory=True)
    except OSError:
        pytest.skip("Creating owned fixture symlinks is not permitted")
    with pytest.raises(RuntimeError):
        storage.ensure_private_root(alias)
    with pytest.raises(RuntimeError):
        storage.create_private_file(alias / "nested", _KEY, b"not written")
    assert not (target / "nested").exists()
    root = storage.ensure_private_root(owned_directory / "proofs")
    link = root / _KEY
    link.symlink_to(path)
    with pytest.raises(RuntimeError):
        storage.checked_private_file(root, _KEY)
    with pytest.raises(RuntimeError):
        storage.create_private_file(root, _KEY, b"not written")
    assert path.read_bytes() == _DATA


@pytest.mark.skipif(os.name != "nt", reason="Junctions are a Windows reparse feature")
def test_windows_junction_ancestry_is_refused(owned_directory):
    target = storage.ensure_private_root(owned_directory / "target")
    alias = owned_directory / "owned-junction"
    result = subprocess.run(
        ["cmd.exe", "/c", "mklink", "/J", str(alias), str(target)],
        capture_output=True, timeout=10,
    )
    if result.returncode:
        pytest.skip("Creating an owned fixture junction is not permitted")
    try:
        with pytest.raises(RuntimeError):
            storage.ensure_private_root(alias / "proofs")
        assert not (target / "proofs").exists()
    finally:
        alias.rmdir()


@pytest.mark.skipif(os.name != "nt", reason="Windows directory handles prevent rename during writes")
def test_windows_root_is_pinned_during_creation(owned_directory, monkeypatch):
    root = storage.ensure_private_root(owned_directory / "proofs")
    original = storage._WindowsSecurity.write
    attempts = []

    def write(windows, handle, data):
        try:
            root.rename(owned_directory / "moved")
        except OSError:
            attempts.append("refused")
        else:
            attempts.append("renamed")
        original(windows, handle, data)

    monkeypatch.setattr(storage._WindowsSecurity, "write", write)
    assert storage.create_private_file(root, _KEY, _DATA).read_bytes() == _DATA
    assert attempts == ["refused"]


@pytest.mark.skipif(os.name != "nt", reason="Windows owner verification uses a native token SID")
def test_mismatched_windows_owner_is_refused_without_adoption(owned_directory, monkeypatch):
    root = storage.ensure_private_root(owned_directory / "proofs")
    original = storage._WindowsSecurity.__init__

    def different_user(windows):
        original(windows)
        windows.sid = "S-1-5-18"

    monkeypatch.setattr(storage._WindowsSecurity, "__init__", different_user)
    with pytest.raises(RuntimeError):
        storage.ensure_private_root(root)
    assert not (root / _KEY).exists()


@pytest.mark.skipif(os.name != "nt", reason="Native Windows write failure injection")
def test_failed_write_is_sanitized_and_never_deletes_or_overwrites(owned_directory, monkeypatch):
    root = storage.ensure_private_root(owned_directory / "proofs")
    original = storage._WindowsSecurity.write

    def fail(windows, handle, data):
        original(windows, handle, b"partial")
        raise OSError("untrusted native diagnostic " + str(root) + " " + _KEY)

    monkeypatch.setattr(storage._WindowsSecurity, "write", fail)
    with pytest.raises(RuntimeError) as error:
        storage.create_private_file(root, _KEY, _DATA)
    assert error.value.args == ("Private proof storage is unavailable.",)
    assert error.value.__cause__ is None
    assert error.value.__suppress_context__
    assert storage.checked_private_file(root, _KEY).read_bytes() == b"partial"
    with pytest.raises(RuntimeError):
        storage.create_private_file(root, _KEY, b"replacement")
    assert (root / _KEY).read_bytes() == b"partial"


@pytest.mark.skipif(os.name != "posix", reason="Native POSIX creation modes require a POSIX host")
def test_posix_permissive_umask_cannot_broaden_new_permissions(owned_directory):
    previous = os.umask(0)
    try:
        root = owned_directory / "proofs"
        path = storage.create_private_file(root, _KEY, _DATA)
    finally:
        os.umask(previous)
    assert stat.S_IMODE(root.stat().st_mode) == 0o700
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


@pytest.mark.skipif(os.name != "posix", reason="Native POSIX descriptor-relative race check")
def test_posix_renamed_root_is_detected_without_removing_private_file(owned_directory, monkeypatch):
    root = storage.ensure_private_root(owned_directory / "proofs")
    moved = owned_directory / "owned-moved-root"
    original = os.write

    def write(fd, data):
        root.rename(moved)
        return original(fd, data)

    monkeypatch.setattr(os, "write", write)
    with pytest.raises(RuntimeError):
        storage.create_private_file(root, _KEY, _DATA)
    assert storage.checked_private_file(moved, _KEY).read_bytes() == _DATA


@pytest.mark.parametrize("directory,mode,uid,links", [
    (True, stat.S_IFDIR | 0o755, 37, 2),
    (True, stat.S_IFDIR | 0o770, 37, 2),
    (True, stat.S_IFDIR | 0o700, 38, 2),
    (True, stat.S_IFLNK | 0o700, 37, 1),
    (False, stat.S_IFREG | 0o644, 37, 1),
    (False, stat.S_IFREG | 0o660, 37, 1),
    (False, stat.S_IFREG | 0o600, 38, 1),
    (False, stat.S_IFREG | 0o600, 37, 2),
    (False, stat.S_IFIFO | 0o600, 37, 1),
    (False, stat.S_IFREG | 0o4600, 37, 1),
])
def test_posix_guard_rejects_unsafe_metadata_without_filesystem_mutation(monkeypatch, directory, mode, uid, links):
    monkeypatch.setattr(os, "geteuid", lambda: 37, raising=False)
    metadata = SimpleNamespace(st_mode=mode, st_uid=uid, st_nlink=links)
    with pytest.raises(RuntimeError):
        storage._check_posix(metadata, directory=directory)


@pytest.mark.parametrize("directory,mode,links", [
    (True, stat.S_IFDIR | 0o700, 2), (False, stat.S_IFREG | 0o600, 1),
    (False, stat.S_IFREG | 0o400, 1),
])
def test_posix_guard_accepts_owner_only_metadata(monkeypatch, directory, mode, links):
    monkeypatch.setattr(os, "geteuid", lambda: 37, raising=False)
    storage._check_posix(SimpleNamespace(st_mode=mode, st_uid=37, st_nlink=links), directory=directory)
