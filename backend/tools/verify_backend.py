"""Run bounded API verification on an owned disposable PostgreSQL instance."""
from __future__ import annotations

import argparse
import os
import secrets
import socket
import subprocess
import sys
import tempfile
import time
import uuid
from contextlib import contextmanager
from pathlib import Path

import requests

BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))

from app.core.config import Settings  # noqa: E402
from tools.local_postgres import LocalPostgres, OwnedProcessGroup, TEMP_PARENT  # noqa: E402


@contextmanager
def verification_directory():
    owned = tempfile.TemporaryDirectory(prefix="supplyos-api-verify-", dir=TEMP_PARENT)
    try:
        yield Path(owned.name)
    finally:
        deadline = time.monotonic() + 8
        while True:
            try:
                owned.cleanup()
                break
            except (PermissionError, NotADirectoryError):
                if time.monotonic() >= deadline:
                    raise RuntimeError("Owned verification artifacts remained locked after process shutdown") from None
                time.sleep(0.05)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("tests", nargs="*", default=[
        "tests/test_configuration.py", "tests/test_ai_provider.py", "tests/test_service_policy.py",
        "tests/test_env_initialization.py", "tests/test_bootstrap_api.py",
        "tests/test_supplyos_e2e.py",
        "tests/test_owned_processes.py",
        "tests/test_auth_security.py", "tests/test_access_controls.py",
        "tests/test_smtp_recovery.py",
        "tests/test_inventory_invariants.py",
        "tests/test_migrations.py", "tests/test_inventory_migration.py",
        "tests/test_financial_invariants.py", "tests/test_delivery_proofs.py",
        "tests/test_proof_images.py", "tests/test_proof_body_limit.py",
        "tests/test_proof_migration.py", "tests/test_private_storage.py",
        "tests/test_supabase_storage.py",
        "tests/test_proof_upload_journal.py", "tests/test_proof_store.py",
        "tests/test_browser_security.py",
        "tests/test_setup_security.py", "tests/test_staff_onboarding.py",
        "tests/test_customer_onboarding.py",
        "tests/test_password_change.py", "tests/test_pricing_workflow.py",
    ])
    parser.add_argument("--test-timeout", type=int, default=300)
    args = parser.parse_args()
    if args.test_timeout < 1 or args.test_timeout > 1200:
        parser.error("--test-timeout must be between 1 and 1200 seconds")
    run_id = uuid.uuid4().hex
    with socket.socket() as reservation:
        reservation.bind(("127.0.0.1", 0))
        api_port = reservation.getsockname()[1]
    origin = f"http://127.0.0.1:{api_port}"
    with LocalPostgres() as pg, verification_directory() as temporary, OwnedProcessGroup() as processes:
        env = dict(os.environ)
        env.pop("SUPPLYOS_LOCAL_POSTGRES_TESTS", None)
        for field in Settings.model_fields.values():
            if isinstance(field.validation_alias, str):
                env.pop(field.validation_alias, None)
        env.update({
            "APP_ENV": "test", "APP_NAME": f"SupplyOS Verification {run_id}",
            "FREE_ONLY_MODE": "true", "APPROVED_FREE_SMTP": "false",
            "DATABASE_URL": pg.async_url, "DATABASE_URL_SYNC": pg.sync_url,
            "JWT_SECRET": secrets.token_urlsafe(48),
            "SUPPLYOS_OWNED_TEST_ENV": "1",
            "SETUP_AUTHORIZATION_TOKEN": secrets.token_urlsafe(48),
            "REDIS_URL": os.environ.get("TEST_REDIS_URL", "redis://127.0.0.1:6379/0"),
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
            "FRONTEND_URL": "http://localhost:3000",
            "COOKIE_SECURE": "false", "COOKIE_SAMESITE": "lax",
            "PROOF_STORAGE_DIR": str(Path(temporary) / "proofs"),
            "PROOF_STORAGE_BACKEND": "local", "APPROVED_FREE_STORAGE": "false",
            "SUPABASE_VERSIONING_VERIFIED": "false",
            "SUPABASE_STORAGE_ORIGIN": "", "SUPABASE_STORAGE_BUCKET": "", "SUPABASE_STORAGE_KEY": "",
            "PROOF_STORAGE_TIMEOUT_SECONDS": "10", "PROOF_STORAGE_CAPACITY": "4",
            "TEST_API_URL": origin, "TEST_RUN_ID": run_id,
            "SUPPLYOS_ALLOW_API_WRITE_TESTS": "1",
            "SUPPLYOS_POSTGRES_MIGRATION_TESTS": "1", "TEST_DATABASE_URL_SYNC": pg.sync_url,
            "TEST_ADMIN_EMAIL": "verification-owner@example.com",
            "TEST_ADMIN_PASSWORD": secrets.token_urlsafe(24),
            "PYTHONDONTWRITEBYTECODE": "1",
        })
        processes.run(
            [sys.executable, "-B", "-m", "alembic", "upgrade", "head"],
            cwd=BACKEND_ROOT, environment=env, output=sys.stdout, timeout=120, check=True,
        )
        log_path = Path(temporary) / "server.log"
        with log_path.open("wb") as server_log:
            server = processes.launch(
                [sys.executable, "-B", "-m", "uvicorn", "server:app", "--host", "127.0.0.1", "--port", str(api_port)],
                cwd=BACKEND_ROOT, environment=env, output=server_log,
            )
            try:
                deadline = time.monotonic() + 30
                while time.monotonic() < deadline:
                    if server.poll() is not None:
                        raise RuntimeError("Isolated API startup failed; no live server was used")
                    try:
                        response = requests.get(f"{origin}/api/health", timeout=1)
                        if response.status_code == 200 and response.json().get("app") == env["APP_NAME"]:
                            break
                    except requests.RequestException:
                        pass
                    time.sleep(0.1)
                else:
                    raise RuntimeError("Isolated API did not become ready within 30 seconds")
                setup = requests.post(f"{origin}/api/v1/setup/initialize", json={
                    "company_name": "SupplyOS verification business",
                    "admin_email": env["TEST_ADMIN_EMAIL"],
                    "admin_password": env["TEST_ADMIN_PASSWORD"],
                    "admin_full_name": "Verification owner",
                    "warehouses": [{"code": "VERIFY-WH", "name": "Verification warehouse"}],
                }, headers={"X-Setup-Authorization": env["SETUP_AUTHORIZATION_TOKEN"]}, timeout=15)
                if setup.status_code != 201:
                    raise RuntimeError(f"Isolated setup failed (HTTP {setup.status_code})")
                print("Owned PostgreSQL and isolated API are ready; credentials are not displayed.", flush=True)
                result = processes.run(
                    [
                        sys.executable, "-B", "-m", "pytest", *args.tests, "-q",
                        "-p", "no:cacheprovider", "--basetemp", str(Path(temporary) / "pytest"),
                    ],
                    cwd=BACKEND_ROOT, environment=env, output=sys.stdout,
                    timeout=args.test_timeout, check=False,
                )
                return result.returncode
            finally:
                processes.terminate()
                server.wait(timeout=10)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (RuntimeError, subprocess.SubprocessError, requests.RequestException) as error:
        print(f"Backend verification failed ({type(error).__name__}). No credentials are displayed.", file=sys.stderr)
        raise SystemExit(1)
