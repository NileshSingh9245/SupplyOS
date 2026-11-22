"""Run the real local web/API preview with an owned temporary PostgreSQL database."""
from __future__ import annotations

import os
import secrets
import shutil
import signal
import socket
import sys
import tempfile
import threading
import time
import uuid
from pathlib import Path

import requests

BACKEND_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = BACKEND_ROOT.parent
FRONTEND_ROOT = PROJECT_ROOT / "frontend"
sys.path.insert(0, str(BACKEND_ROOT))

from app.core.config import Settings  # noqa: E402
from tools.local_postgres import LocalPostgres, OwnedProcessGroup, TEMP_PARENT  # noqa: E402


def wait_ready(origin: str, path: str, process, *, expected_app=None, timeout=90):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError("A preview service exited before becoming ready")
        try:
            response = requests.get(origin + path, timeout=3)
            if response.status_code == 200:
                if expected_app is None or response.json().get("app") == expected_app:
                    return
        except requests.RequestException:
            pass
        time.sleep(0.1)
    raise RuntimeError("Preview service did not become ready within its startup deadline")


def main() -> int:
    for port in (3000, 8001):
        with socket.socket() as check:
            check.bind(("127.0.0.1", port))
    node = shutil.which("node")
    next_cli = FRONTEND_ROOT / "node_modules" / "next" / "dist" / "bin" / "next"
    if not node or not next_cli.is_file():
        raise RuntimeError("Node and installed frontend dependencies are required")
    stop = threading.Event()
    for event in (signal.SIGINT, signal.SIGTERM):
        signal.signal(event, lambda *_: stop.set())
    run_id = uuid.uuid4().hex
    with LocalPostgres() as pg, tempfile.TemporaryDirectory(
        prefix="supplyos-preview-", dir=TEMP_PARENT, ignore_cleanup_errors=True,
    ) as temporary, OwnedProcessGroup() as processes:
        backend_env = dict(os.environ)
        for field in Settings.model_fields.values():
            if isinstance(field.validation_alias, str):
                backend_env.pop(field.validation_alias, None)
        app_name = f"SupplyOS Local Preview {run_id}"
        backend_env.update({
            "APP_ENV": "development", "APP_NAME": app_name,
            "FREE_ONLY_MODE": "true", "APPROVED_FREE_SMTP": "false",
            "DATABASE_URL": pg.async_url, "DATABASE_URL_SYNC": pg.sync_url,
            "JWT_SECRET": secrets.token_urlsafe(48),
            "SUPPLYOS_OWNED_TEST_ENV": "1",
            "SETUP_AUTHORIZATION_TOKEN": os.environ.get("SETUP_AUTHORIZATION_TOKEN", ""),
            "REDIS_URL": "redis://127.0.0.1:6379/0",
            "ANTHROPIC_API_KEY": "",
            "SMTP_ENABLED": "false", "SMTP_HOST": "", "SMTP_PORT": "587",
            "SMTP_USERNAME": "", "SMTP_PASSWORD": "", "SMTP_FROM": "",
            "SMTP_FROM_NAME": "SupplyOS", "SMTP_TLS_MODE": "starttls",
            "SMTP_TIMEOUT_SECONDS": "10", "PASSWORD_RESET_URL": "",
            "PASSWORD_RESET_CAPACITY": "4", "PASSWORD_RESET_WINDOW_SECONDS": "3600",
            "PASSWORD_RESET_MAX_REQUESTS_PER_IP": "3",
            "PASSWORD_RESET_MAX_REQUESTS_PER_IDENTITY": "3",
            "PASSWORD_RESET_COOLDOWN_SECONDS": "60",
            "PASSWORD_RESET_RATE_LIMIT_TIMEOUT_SECONDS": "0.5",
            "PASSWORD_RESET_WORK_TIMEOUT_SECONDS": "10",
            "FRONTEND_URL": "http://localhost:3000,http://127.0.0.1:3000",
            "COOKIE_SECURE": "false", "COOKIE_SAMESITE": "lax",
            "PROOF_STORAGE_DIR": str(Path(temporary) / "proofs"),
            "PROOF_STORAGE_BACKEND": "local", "APPROVED_FREE_STORAGE": "false",
            "SUPABASE_VERSIONING_VERIFIED": "false",
            "SUPABASE_STORAGE_ORIGIN": "", "SUPABASE_STORAGE_BUCKET": "", "SUPABASE_STORAGE_KEY": "",
            "PROOF_STORAGE_TIMEOUT_SECONDS": "10", "PROOF_STORAGE_CAPACITY": "4",
            "PYTHONDONTWRITEBYTECODE": "1",
        })
        processes.run(
            [sys.executable, "-B", "-m", "alembic", "upgrade", "head"],
            environment=backend_env, output=sys.stdout, cwd=BACKEND_ROOT, timeout=120, check=True,
        )
        api = processes.launch(
            [sys.executable, "-B", "-m", "uvicorn", "server:app", "--host", "127.0.0.1", "--port", "8001"],
            environment=backend_env, output=sys.stdout, cwd=BACKEND_ROOT,
        )
        wait_ready("http://127.0.0.1:8001", "/api/health", api, expected_app=app_name)
        frontend_env = dict(os.environ)
        for field in Settings.model_fields.values():
            if isinstance(field.validation_alias, str):
                frontend_env.pop(field.validation_alias, None)
        frontend_env.update({
            "NEXT_DIST_DIR": ".runtime/preview", "NEXT_TELEMETRY_DISABLED": "1",
            "BACKEND_URL": "http://127.0.0.1:8001", "NEXT_PUBLIC_BACKEND_URL": "",
            "REACT_APP_BACKEND_URL": "", "NEXT_PUBLIC_API_BASE": "/api/v1",
        })
        web = processes.launch(
            [node, str(next_cli), "dev", "-p", "3000", "-H", "127.0.0.1"],
            environment=frontend_env, output=sys.stdout, cwd=FRONTEND_ROOT,
        )
        wait_ready("http://127.0.0.1:3000", "/api/health", web, expected_app=app_name)
        wait_ready("http://127.0.0.1:3000", "/", web)
        print("SupplyOS preview ready: http://localhost:3000 (temporary isolated data)", flush=True)
        print("Setup requires privately configured operator authorization; no credentials are generated or displayed.", flush=True)
        for child in (api, web):
            threading.Thread(target=lambda process=child: (process.wait(), stop.set()), daemon=True).start()
        stop.wait()
        return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        print(f"Local preview failed ({type(error).__name__}); private values are not displayed.", file=sys.stderr)
        raise SystemExit(1)
