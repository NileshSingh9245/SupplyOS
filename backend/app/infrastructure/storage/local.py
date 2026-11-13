"""Fail-closed local proof storage, without repairing existing permissions.

Windows requires a local ACL-capable volume; new objects grant access only to
the process user, SYSTEM and Builtin Administrators. The POSIX implementation
requires Linux's mode-masked DAC/ACL model, not an NFSv4/macOS extended ACL model.
Symlink/reparse ancestry is refused and directory handles stay open throughout
each operation. A returned Path is NOT an open handle: callers must trust the
ancestry and other processes running as the owner/administrator before reopening
it. This API cannot eliminate that subsequent check-to-open race. Failed writes
may leave a private partial file; nothing is overwritten, removed or adopted by
changing its permissions. Image validation and database receipts belong upstream.
"""
from __future__ import annotations

import ctypes
import os
import re
import stat
import sys
from contextlib import ExitStack, contextmanager
from pathlib import Path
from typing import Iterator

__all__ = ["ensure_private_root", "create_private_file", "checked_private_file", "read_private_file"]

_ERROR = "Private proof storage is unavailable."
_KEY = re.compile(r"[0-9a-f]{32}\.(?:png|jpg)", re.ASCII)


def _root_path(root: Path) -> Path:
    if not isinstance(root, Path) or ".." in root.parts:
        raise RuntimeError(_ERROR)
    root = root.absolute()
    if root == Path(root.anchor):
        raise RuntimeError(_ERROR)
    if os.name == "nt":
        if not re.fullmatch(r"[A-Za-z]:", root.drive):
            raise RuntimeError(_ERROR)  # No UNC, device, alternate stream or extended paths.
        reserved = {"CON", "PRN", "AUX", "NUL", "CONIN$", "CONOUT$"}
        reserved.update(f"{prefix}{number}" for prefix in ("COM", "LPT") for number in "123456789")
        for part in root.parts[1:]:
            if (
                part.endswith((".", " ")) or any(ord(char) < 32 for char in part)
                or any(char in '<>:"|?*' for char in part)
                or part.split(".", 1)[0].upper() in reserved
            ):
                raise RuntimeError(_ERROR)
    return root


def _check_key(object_key: str) -> None:
    if not isinstance(object_key, str) or _KEY.fullmatch(object_key) is None:
        raise RuntimeError(_ERROR)


def _check_posix(metadata: os.stat_result, *, directory: bool) -> None:
    kind = stat.S_ISDIR if directory else stat.S_ISREG
    mode = stat.S_IMODE(metadata.st_mode)
    if (
        not kind(metadata.st_mode) or metadata.st_uid != os.geteuid()
        or mode & 0o7077 or not mode & 0o400
        or (directory and mode & 0o700 != 0o700)
        or (not directory and metadata.st_nlink != 1)
    ):
        raise RuntimeError(_ERROR)


def _check_posix_acl(fd: int) -> None:
    # Linux POSIX ACL named entries are masked by the group mode bits (zero).
    # Refuse known ACL models whose grants need not be represented by those bits.
    import errno

    for name in ("system.nfs4_acl", "system.richacl", "system.cifs_acl"):
        try:
            os.getxattr(fd, name)
        except OSError as error:
            if error.errno not in {errno.ENODATA, errno.ENOTSUP, errno.EOPNOTSUPP}:
                raise
        else:
            raise RuntimeError(_ERROR)


class _SecurityAttributes(ctypes.Structure):
    _fields_ = [
        ("length", ctypes.c_uint32), ("descriptor", ctypes.c_void_p),
        ("inherit_handle", ctypes.c_int32),
    ]


class _FileInformation(ctypes.Structure):
    _fields_ = [
        ("attributes", ctypes.c_uint32), ("times", ctypes.c_uint32 * 6),
        ("volume", ctypes.c_uint32), ("size_high", ctypes.c_uint32),
        ("size_low", ctypes.c_uint32), ("links", ctypes.c_uint32),
        ("index_high", ctypes.c_uint32), ("index_low", ctypes.c_uint32),
    ]


class _AclInformation(ctypes.Structure):
    _fields_ = [
        ("count", ctypes.c_uint32), ("used", ctypes.c_uint32),
        ("free", ctypes.c_uint32),
    ]


class _AceHeader(ctypes.Structure):
    _fields_ = [("kind", ctypes.c_ubyte), ("flags", ctypes.c_ubyte), ("size", ctypes.c_uint16)]


class _WindowsSecurity:
    def __init__(self) -> None:
        self.kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        self.security = ctypes.WinDLL("advapi32", use_last_error=True)
        pointer, word, boolean = ctypes.c_void_p, ctypes.c_uint32, ctypes.c_int32
        for library, signatures in (
            (self.kernel, {
                "GetCurrentProcess": ([], pointer),
                "CloseHandle": ([pointer], boolean),
                "LocalFree": ([pointer], pointer),
                "GetDriveTypeW": ([ctypes.c_wchar_p], word),
                "GetVolumeInformationW": (
                    [ctypes.c_wchar_p, pointer, word, pointer, pointer, pointer, pointer, word], boolean,
                ),
                "CreateDirectoryW": ([ctypes.c_wchar_p, pointer], boolean),
                "CreateFileW": (
                    [ctypes.c_wchar_p, word, word, pointer, word, word, pointer], pointer,
                ),
                "GetFileType": ([pointer], word),
                "GetFileInformationByHandle": ([pointer, pointer], boolean),
                "WriteFile": ([pointer, pointer, word, pointer, pointer], boolean),
                "ReadFile": ([pointer, pointer, word, pointer, pointer], boolean),
                "FlushFileBuffers": ([pointer], boolean),
            }),
            (self.security, {
                "OpenProcessToken": ([pointer, word, pointer], boolean),
                "GetTokenInformation": ([pointer, ctypes.c_int, pointer, word, pointer], boolean),
                "ConvertSidToStringSidW": ([pointer, pointer], boolean),
                "ConvertStringSecurityDescriptorToSecurityDescriptorW": (
                    [ctypes.c_wchar_p, word, pointer, pointer], boolean,
                ),
                "GetSecurityInfo": (
                    [pointer, ctypes.c_int, word, pointer, pointer, pointer, pointer, pointer], word,
                ),
                "GetSecurityDescriptorControl": ([pointer, pointer, pointer], boolean),
                "GetAclInformation": ([pointer, pointer, word, ctypes.c_int], boolean),
                "IsValidAcl": ([pointer], boolean),
                "GetAce": ([pointer, word, pointer], boolean),
            }),
        ):
            for name, (arguments, result) in signatures.items():
                function = getattr(library, name)
                function.argtypes, function.restype = arguments, result
        token = pointer()
        if not self.security.OpenProcessToken(self.kernel.GetCurrentProcess(), 0x0008, ctypes.byref(token)):
            raise RuntimeError(_ERROR)
        try:
            size = word()
            self.security.GetTokenInformation(token, 1, None, 0, ctypes.byref(size))
            if not size.value:
                raise RuntimeError(_ERROR)
            user = ctypes.create_string_buffer(size.value)
            if not self.security.GetTokenInformation(token, 1, user, size, ctypes.byref(size)):
                raise RuntimeError(_ERROR)
            self.sid = self._sid(ctypes.cast(user, ctypes.POINTER(pointer)).contents.value)
        finally:
            self.kernel.CloseHandle(token)

    def _sid(self, sid: int) -> str:
        text = ctypes.c_void_p()
        if not self.security.ConvertSidToStringSidW(sid, ctypes.byref(text)):
            raise RuntimeError(_ERROR)
        try:
            return ctypes.wstring_at(text)
        finally:
            self.kernel.LocalFree(text)

    def check_volume(self, anchor: str) -> None:
        flags = ctypes.c_uint32()
        if (
            self.kernel.GetDriveTypeW(anchor) not in {2, 3, 6}
            or not self.kernel.GetVolumeInformationW(
                anchor, None, 0, None, None, ctypes.byref(flags), None, 0,
            )
            or not flags.value & 0x00000008  # FILE_PERSISTENT_ACLS
        ):
            raise RuntimeError(_ERROR)

    @contextmanager
    def attributes(self, *, directory: bool) -> Iterator[_SecurityAttributes]:
        inheritance = "OICI" if directory else ""
        dacl = "".join(f"(A;{inheritance};FA;;;{sid})" for sid in (self.sid, "SY", "BA"))
        descriptor = ctypes.c_void_p()
        if not self.security.ConvertStringSecurityDescriptorToSecurityDescriptorW(
            f"O:{self.sid}D:P{dacl}", 1, ctypes.byref(descriptor), None,
        ):
            raise RuntimeError(_ERROR)
        try:
            yield _SecurityAttributes(ctypes.sizeof(_SecurityAttributes), descriptor, False)
        finally:
            self.kernel.LocalFree(descriptor)

    @contextmanager
    def open(self, path: Path, *, directory: bool, create: bool = False) -> Iterator[int]:
        access = 0x00020080 | (0 if directory else 0x80000000)
        if create:
            access = 0x40020080  # GENERIC_WRITE, READ_CONTROL, FILE_READ_ATTRIBUTES
        with ExitStack() as stack:
            attributes = stack.enter_context(self.attributes(directory=False)) if create else None
            handle = self.kernel.CreateFileW(
                str(path), access, 1, ctypes.byref(attributes) if attributes is not None else None,
                1 if create else 3, 0x02200000, None,
            )  # OPEN_REPARSE_POINT | BACKUP_SEMANTICS; share neither writes nor deletes.
            if handle == ctypes.c_void_p(-1).value:
                error = ctypes.get_last_error()
                if error in {2, 3}:
                    raise FileNotFoundError(_ERROR)
                if error in {80, 183}:
                    raise FileExistsError(_ERROR)
                raise RuntimeError(_ERROR)
            try:
                self.check_kind(handle, directory=directory)
                yield handle
            finally:
                self.kernel.CloseHandle(handle)

    def mkdir(self, path: Path) -> bool:
        with self.attributes(directory=True) as attributes:
            if self.kernel.CreateDirectoryW(str(path), ctypes.byref(attributes)):
                return True
            if ctypes.get_last_error() == 183:
                return False
            raise RuntimeError(_ERROR)

    def check_kind(self, handle: int, *, directory: bool) -> None:
        information = _FileInformation()
        if (
            self.kernel.GetFileType(handle) != 1
            or not self.kernel.GetFileInformationByHandle(handle, ctypes.byref(information))
            or information.attributes & 0x400
            or bool(information.attributes & 0x10) != directory
            or (not directory and information.links != 1)
        ):
            raise RuntimeError(_ERROR)

    def check_private(self, handle: int, *, directory: bool) -> None:
        owner, dacl, descriptor = (ctypes.c_void_p() for _ in range(3))
        if self.security.GetSecurityInfo(
            handle, 1, 0x00000005, ctypes.byref(owner), None, ctypes.byref(dacl),
            None, ctypes.byref(descriptor),
        ):
            raise RuntimeError(_ERROR)
        try:
            control, revision = ctypes.c_uint16(), ctypes.c_uint32()
            if (
                not owner or self._sid(owner.value) != self.sid
                or not self.security.GetSecurityDescriptorControl(
                    descriptor, ctypes.byref(control), ctypes.byref(revision),
                )
                or not control.value & 0x0004 or not dacl
                or (directory and not control.value & 0x1000)
                or not self.security.IsValidAcl(dacl)
            ):
                raise RuntimeError(_ERROR)
            information = _AclInformation()
            if not self.security.GetAclInformation(
                dacl, ctypes.byref(information), ctypes.sizeof(information), 2,
            ):
                raise RuntimeError(_ERROR)
            owner_access = inherited_access = 0
            allowed = {self.sid, "S-1-5-18", "S-1-5-32-544"}
            for index in range(information.count):
                ace = ctypes.c_void_p()
                if not self.security.GetAce(dacl, index, ctypes.byref(ace)):
                    raise RuntimeError(_ERROR)
                header = _AceHeader.from_address(ace.value)
                if header.kind == 1:  # Ordinary deny ACEs cannot widen access.
                    continue
                if header.kind != 0 or header.size < 16:
                    raise RuntimeError(_ERROR)  # Unknown/object/callback ACEs fail closed.
                sid = self._sid(ace.value + 8)
                if sid not in allowed:
                    raise RuntimeError(_ERROR)  # Also check inheritance-only grants.
                if sid == self.sid:
                    mask = ctypes.c_uint32.from_address(ace.value + 4).value
                    if not header.flags & 0x08:
                        owner_access |= mask
                    if header.flags & 0x03 == 0x03 and not header.flags & 0x04:
                        inherited_access |= mask
            if not owner_access & 0x90000001 or (directory and not inherited_access & 0x90000001):
                raise RuntimeError(_ERROR)
        finally:
            self.kernel.LocalFree(descriptor)

    def write(self, handle: int, data: bytes) -> None:
        offset = 0
        while offset < len(data):
            buffer = ctypes.create_string_buffer(data[offset:offset + 1024 * 1024])
            written = ctypes.c_uint32()
            if (
                not self.kernel.WriteFile(handle, buffer, len(buffer) - 1, ctypes.byref(written), None)
                or not written.value
            ):
                raise RuntimeError(_ERROR)
            offset += written.value
        if not self.kernel.FlushFileBuffers(handle):
            raise RuntimeError(_ERROR)

    def read(self, handle: int, limit: int) -> bytes:
        data = bytearray()
        while len(data) <= limit:
            size = min(1024 * 1024, limit + 1 - len(data))
            buffer = ctypes.create_string_buffer(size)
            received = ctypes.c_uint32()
            if not self.kernel.ReadFile(handle, buffer, size, ctypes.byref(received), None):
                raise RuntimeError(_ERROR)
            if not received.value:
                return bytes(data)
            data.extend(buffer.raw[:received.value])
        raise RuntimeError(_ERROR)


@contextmanager
def _private_root(root: Path, *, create: bool) -> Iterator[tuple[_WindowsSecurity | None, int]]:
    if os.name == "nt":
        windows = _WindowsSecurity()
        windows.check_volume(root.anchor)
        with ExitStack() as stack:
            path = Path(root.anchor)
            handle = stack.enter_context(windows.open(path, directory=True))
            for part in root.parts[1:]:
                path /= part
                created = False
                try:
                    handle = stack.enter_context(windows.open(path, directory=True))
                except FileNotFoundError:
                    if not create:
                        raise
                    created = windows.mkdir(path)
                    handle = stack.enter_context(windows.open(path, directory=True))
                if created or path == root:
                    windows.check_private(handle, directory=True)
            yield windows, handle
        return
    if (
        os.name != "posix" or sys.platform != "linux"
        or not hasattr(os, "O_NOFOLLOW") or not hasattr(os, "getxattr")
        or not {os.open, os.mkdir, os.stat} <= os.supports_dir_fd
    ):
        raise RuntimeError(_ERROR)
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
    with ExitStack() as stack:
        handle = os.open(root.anchor, flags)
        stack.callback(os.close, handle)
        ancestry = []
        for part in root.parts[1:]:
            created = False
            try:
                child = os.open(part, flags, dir_fd=handle)
            except FileNotFoundError:
                if not create:
                    raise
                try:
                    os.mkdir(part, 0o700, dir_fd=handle)
                    created = True
                except FileExistsError:
                    pass
                child = os.open(part, flags, dir_fd=handle)
            stack.callback(os.close, child)
            ancestry.append((handle, part, child))
            if created or len(ancestry) == len(root.parts) - 1:
                _check_posix(os.fstat(child), directory=True)
                _check_posix_acl(child)
            handle = child
        yield None, handle
        _check_posix(os.fstat(handle), directory=True)
        for parent, name, child in ancestry:
            named = os.stat(name, dir_fd=parent, follow_symlinks=False)
            if not os.path.samestat(named, os.fstat(child)):
                raise RuntimeError(_ERROR)


def ensure_private_root(root: Path) -> Path:
    """Create missing private directories, or verify the existing store unchanged."""
    try:
        root = _root_path(root)
        with _private_root(root, create=True):
            return root
    except (OSError, RuntimeError, ValueError, TypeError, OverflowError, AttributeError, ctypes.ArgumentError):
        raise RuntimeError(_ERROR) from None


def create_private_file(root: Path, object_key: str, data: bytes) -> Path:
    """Exclusively create and flush one private proof; never overwrite or clean up."""
    try:
        _check_key(object_key)
        if not isinstance(data, bytes):
            raise RuntimeError(_ERROR)
        root = _root_path(root)
        with _private_root(root, create=True) as (windows, handle):
            path = root / object_key
            if windows is not None:
                with windows.open(path, directory=False, create=True) as file_handle:
                    windows.check_private(file_handle, directory=False)
                    windows.write(file_handle, data)
                    windows.check_private(file_handle, directory=False)
            else:
                flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC
                fd = os.open(object_key, flags, 0o600, dir_fd=handle)
                try:
                    _check_posix(os.fstat(fd), directory=False)
                    _check_posix_acl(fd)
                    remaining = memoryview(data)
                    while remaining:
                        written = os.write(fd, remaining)
                        if not written:
                            raise RuntimeError(_ERROR)
                        remaining = remaining[written:]
                    os.fsync(fd)
                    _check_posix(os.fstat(fd), directory=False)
                    named = os.stat(object_key, dir_fd=handle, follow_symlinks=False)
                    if not os.path.samestat(os.fstat(fd), named):
                        raise RuntimeError(_ERROR)
                finally:
                    os.close(fd)
                os.fsync(handle)
            return path
    except (OSError, RuntimeError, ValueError, TypeError, OverflowError, AttributeError, ctypes.ArgumentError):
        raise RuntimeError(_ERROR) from None


def checked_private_file(root: Path, object_key: str) -> Path:
    """Verify a private regular single-link file without creating or altering it."""
    try:
        _check_key(object_key)
        root = _root_path(root)
        with _private_root(root, create=False) as (windows, handle):
            path = root / object_key
            if windows is not None:
                with windows.open(path, directory=False) as file_handle:
                    windows.check_private(file_handle, directory=False)
            else:
                flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC
                fd = os.open(object_key, flags, dir_fd=handle)
                try:
                    metadata = os.fstat(fd)
                    _check_posix(metadata, directory=False)
                    _check_posix_acl(fd)
                    named = os.stat(object_key, dir_fd=handle, follow_symlinks=False)
                    if not os.path.samestat(metadata, named):
                        raise RuntimeError(_ERROR)
                finally:
                    os.close(fd)
            return path
    except (OSError, RuntimeError, ValueError, TypeError, OverflowError, AttributeError, ctypes.ArgumentError):
        raise RuntimeError(_ERROR) from None


def read_private_file(root: Path, object_key: str, *, limit: int) -> bytes:
    """Read bounded bytes from the same held handle whose privacy was checked."""
    try:
        _check_key(object_key)
        if type(limit) is not int or not 1 <= limit <= 5 * 1024 * 1024:
            raise RuntimeError(_ERROR)
        root = _root_path(root)
        with _private_root(root, create=False) as (windows, handle):
            if windows is not None:
                with windows.open(root / object_key, directory=False) as file_handle:
                    windows.check_private(file_handle, directory=False)
                    data = windows.read(file_handle, limit)
                    windows.check_private(file_handle, directory=False)
            else:
                flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC
                fd = os.open(object_key, flags, dir_fd=handle)
                try:
                    metadata = os.fstat(fd)
                    _check_posix(metadata, directory=False)
                    _check_posix_acl(fd)
                    if metadata.st_size > limit:
                        raise RuntimeError(_ERROR)
                    data = bytearray()
                    while len(data) <= limit:
                        chunk = os.read(fd, min(1024 * 1024, limit + 1 - len(data)))
                        if not chunk:
                            break
                        data.extend(chunk)
                    after = os.fstat(fd)
                    _check_posix(after, directory=False)
                    _check_posix_acl(fd)
                    named = os.stat(object_key, dir_fd=handle, follow_symlinks=False)
                    if not os.path.samestat(after, named) or len(data) > limit:
                        raise RuntimeError(_ERROR)
                    data = bytes(data)
                finally:
                    os.close(fd)
        return data
    except (OSError, RuntimeError, ValueError, TypeError, OverflowError, AttributeError, ctypes.ArgumentError):
        raise RuntimeError(_ERROR) from None
