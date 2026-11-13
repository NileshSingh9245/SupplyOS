"""Export audited source into an empty release clone without touching the caller's index."""
from __future__ import annotations

import argparse
import hashlib
import os
from pathlib import Path
import re
import shutil


WORKSPACE = Path(__file__).resolve().parents[2]
ROOT_FILES = {".gitignore", "README.md", "CHANGELOG.md", "COMMITS.md", "design_guidelines.json"}
ROOTS = {".ai", ".github", "docs", "memory", "backend", "frontend", "mobile"}
DENIED_PARTS = {
    ".git", "node_modules", ".next", ".next-stabilization", ".runtime", ".private", ".venv",
    "__pycache__", ".pytest_cache", ".ruff_cache", ".dart_tool", ".gradle", "build", "runtime",
}
DENIED_NAMES = {"local.properties", "key.properties", "credentials.json", "credentials.dpapi", ".gitconfig", "test_credentials.md", "next-env.d.ts"}
DENIED_SUFFIXES = {".jks", ".p12", ".pfx", ".pem", ".key", ".pyc", ".pyo", ".apk", ".aab", ".tsbuildinfo"}
SOURCE_SUFFIXES = {
    ".py", ".ts", ".tsx", ".js", ".jsx", ".cjs", ".mjs", ".css", ".json", ".yaml", ".yml",
    ".toml", ".md", ".txt", ".ini", ".mako", ".ps1", ".gradle", ".kts", ".properties", ".xml", ".dart",
    ".lock", ".bat", ".sh", ".png", ".jpg", ".jpeg", ".svg", ".ico", ".woff", ".woff2",
}
SOURCE_NAMES = {"Dockerfile", ".dockerignore", ".gitignore", "gradlew", ".env.example"}
TOKEN = re.compile(rb"(?:github_pat_|ghp_|sb_secret_|sk_live_|rnd_)[A-Za-z0-9_-]{24,}|AKIA[A-Z0-9]{16}")
PRIVATE_KEY = re.compile(rb"-----BEGIN (?:RSA |EC |OPENSSH |ENCRYPTED )?PRIVATE KEY-----")


def allowed(path: Path) -> bool:
    parts = path.parts
    if any(part in DENIED_PARTS for part in parts) or path.name in DENIED_NAMES:
        return False
    if path.suffix.lower() in DENIED_SUFFIXES:
        return False
    if path.name.startswith(".env") and path.name != ".env.example":
        return False
    if path.name.endswith(".env"):
        return False
    if len(parts) == 1:
        return path.name in ROOT_FILES
    if parts[0] not in ROOTS:
        return False
    if parts[0] == "backend" and len(parts) > 2 and parts[1] not in {"app", "alembic", "tests", "tools"}:
        return False
    if parts[0] == "frontend" and len(parts) > 2 and parts[1] not in {"src", "tests", "public"}:
        return False
    if path.suffix.lower() in {".png", ".jpg", ".jpeg", ".svg", ".ico", ".woff", ".woff2"} and parts[0] != "frontend":
        return False
    if path.name == "gradle-wrapper.jar":
        return "android" in parts and "wrapper" in parts
    return path.suffix.lower() in SOURCE_SUFFIXES or path.name in SOURCE_NAMES


def export(destination: Path) -> tuple[int, str]:
    parent = WORKSPACE / ".runtime" / "core-publication"
    if destination != parent / "repo" or not (destination / ".git").is_dir():
        raise RuntimeError("Destination must be the owned release clone, not the original worktree.")
    if any(path.name != ".git" for path in destination.iterdir()):
        raise RuntimeError("Release clone must have no checked-out or previously exported files.")
    files: list[tuple[Path, bytes]] = []
    for directory, folders, names in os.walk(WORKSPACE, followlinks=False):
        relative = Path(directory).relative_to(WORKSPACE)
        folders[:] = [name for name in folders if name not in DENIED_PARTS and
                      (relative.parts or name in ROOTS)]
        for name in names:
            source = Path(directory) / name
            path = source.relative_to(WORKSPACE)
            if not allowed(path):
                continue
            if source.is_symlink() or getattr(source.lstat(), "st_file_attributes", 0) & 0x400:
                raise RuntimeError(f"Source reparse point is not exportable: {path.as_posix()}")
            data = source.read_bytes()
            if len(data) > 8 * 1024 * 1024:
                raise RuntimeError(f"Oversized source asset requires review: {path.as_posix()}")
            if PRIVATE_KEY.search(data) or TOKEN.search(data):
                raise RuntimeError(f"Potential secret requires private review: {path.as_posix()}")
            files.append((path, data))
    digest = hashlib.sha256()
    for path, data in sorted(files, key=lambda item: item[0].as_posix()):
        target = destination / path
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("xb") as handle:
            handle.write(data)
        shutil.copystat(WORKSPACE / path, target)
        digest.update(path.as_posix().encode("utf-8") + b"\0" + hashlib.sha256(data).digest())
    return len(files), digest.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    count, digest = export(args.destination.resolve())
    print(f"Exported {count} source files; dependencies, private data and signing material excluded.")
    print(f"Source snapshot SHA256: {digest}")


if __name__ == "__main__":
    main()
