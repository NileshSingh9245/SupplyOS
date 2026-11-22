"""Run scoped Render review commands without publishing connection credentials."""
from __future__ import annotations

import argparse
import json
import os
import secrets
import subprocess
import sys
from ipaddress import IPv4Address
from pathlib import Path

import certifi
import requests
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.pool import NullPool

BACKEND = Path(__file__).resolve().parents[1]
WORKSPACE = BACKEND.parent
sys.path.insert(0, str(BACKEND))

from app.infrastructure.storage import local
from app.infrastructure.db.base import Base
from app.infrastructure.db import models as _models  # noqa: F401
from tools.local_postgres import OwnedProcessGroup

CLI = WORKSPACE / ".runtime" / "render-cli" / "render.exe"
PRIVATE = WORKSPACE / ".private" / "render-review"
OWNER = "tea-d1lb9315pdvs73bpa9sg"
NAME = "supplyos-client-review"
BACKEND_ID = "srv-dbsptgm1egvs73ehkr6g"
WEB_ID = "srv-dbsptgl6e07s73ahkusg"
DATABASE_ID = "dpg-dbs9uqdg1s2s73ejssbg-a"
CORE_COMMIT = "ff50596ee1372ea2e876582d3b9b4bde8902a37e"
SCHEMA_HEAD = "20261112_0006"
API_URL = "https://supplyos-client-review-api.onrender.com"
WEB_URL = "https://supplyos-client-review-web.onrender.com"


def render(arguments: list[str]) -> object:
    result = subprocess.run([str(CLI), *arguments, "--output", "json"], capture_output=True,
                            text=True, timeout=120, check=False)
    if result.returncode != 0:
        raise RuntimeError("Render command failed; private response details were not displayed")
    return json.loads(result.stdout)


def save(name: str, value: object) -> None:
    if name not in {"database.json", "cache.json", "database-connection.json", "cache-connection.json", "backend-service.json", "web-service.json", "review-environment.json", "review-accounts.json", "review-data.json"}:
        raise RuntimeError("Unsupported private configuration name")
    data = json.dumps(value).encode("utf-8")
    root = local.ensure_private_root(PRIVATE)
    with local._private_root(root, create=False) as (windows, handle):
        if windows is None:
            raise RuntimeError("This review configuration helper requires protected Windows storage")
        with windows.open(root / name, directory=False, create=True) as file_handle:
            windows.check_private(file_handle, directory=False)
            windows.write(file_handle, data)
            windows.check_private(file_handle, directory=False)


def load(name: str) -> object:
    if name not in {"database-connection.json", "cache-connection.json", "review-environment.json", "review-accounts.json", "review-data.json"}:
        raise RuntimeError("Unsupported private configuration name")
    with local._private_root(PRIVATE, create=False) as (windows, handle):
        if windows is None:
            raise RuntimeError("Protected Windows storage is required")
        with windows.open(PRIVATE / name, directory=False) as file_handle:
            windows.check_private(file_handle, directory=False)
            data = windows.read(file_handle, 512 * 1024)
            windows.check_private(file_handle, directory=False)
    return json.loads(data)


def api_request(method: str, path: str, payload: object = None) -> object:
    services = {f"/services/{identifier}" for identifier in (BACKEND_ID, WEB_ID)}
    environments = {path + "/env-vars" for path in services}
    allowed = {
        "GET": services | environments | {f"/postgres/{DATABASE_ID}"},
        "PUT": environments,
        "PATCH": services | {f"/postgres/{DATABASE_ID}"},
    }
    if path not in allowed.get(method, set()):
        raise RuntimeError("Only discovered review resources may be accessed")
    if method == "PATCH":
        if path == f"/postgres/{DATABASE_ID}":
            if not isinstance(payload, dict) or set(payload) != {"ipAllowList"}:
                raise RuntimeError("Review database updates may only change inbound access")
        elif (not isinstance(payload, dict) or set(payload) != {"serviceDetails"}
              or set(payload["serviceDetails"]) != {"healthCheckPath"}):
            raise RuntimeError("Review service updates may only change health checks")
    try:
        import yaml
    except ImportError:
        raise RuntimeError("Render review operations require operator-only PyYAML") from None
    render(["whoami"])
    configuration_path = Path(os.environ.get("RENDER_CLI_CONFIG_PATH", Path.home() / ".render" / "cli.yaml"))
    try:
        configuration = yaml.safe_load(configuration_path.read_text(encoding="utf-8"))
    except yaml.YAMLError:
        raise RuntimeError("Private Render authorization configuration is malformed") from None
    if not isinstance(configuration, dict) or configuration.get("workspace") != OWNER:
        raise RuntimeError("Review workspace authorization changed")
    api_configuration = configuration.get("api")
    key = os.environ.get("RENDER_API_KEY") or (
        api_configuration.get("key") if isinstance(api_configuration, dict) else None
    )
    if not isinstance(key, str) or not key:
        raise RuntimeError("Render authorization is unavailable")
    response = requests.request(method, "https://api.render.com/v1" + path,
                                headers={"Authorization": "Bearer " + key}, json=payload, timeout=30)
    if response.status_code != 200:
        raise RuntimeError("Review API request failed; private response not displayed")
    return response.json()


def api_put(service_id: str, values: dict[str, str]) -> None:
    api_request("PUT", f"/services/{service_id}/env-vars",
                [{"key": name, "value": value} for name, value in values.items()])


def inspect_services() -> None:
    for identifier, origin, root in ((BACKEND_ID, API_URL, "backend"), (WEB_ID, WEB_URL, "frontend")):
        service = api_request("GET", f"/services/{identifier}")
        details = service["serviceDetails"]
        if (service["id"] != identifier or service["ownerId"] != OWNER
                or details["plan"] != "free" or details["region"] != "singapore"
                or service["rootDir"] != root or details["url"] != origin):
            raise RuntimeError("Review service identity or free plan changed")
        print(json.dumps({"id": identifier, "plan": details["plan"], "url": origin,
                          "root_directory": root, "health_check": details["healthCheckPath"],
                          "docker_command_override": bool(details["envSpecificDetails"].get("dockerCommand"))}))


def migrate_database(url) -> None:
    engine = create_engine(url, poolclass=NullPool, hide_parameters=True)
    try:
        with engine.connect() as connection:
            identity = connection.execute(text(
                "SELECT current_database(), current_user, ssl FROM pg_stat_ssl WHERE pid = pg_backend_pid()"
            )).one()
            if identity != ("supplyos_review", "supplyos_review_user", True):
                raise RuntimeError("Dedicated review database identity or TLS validation failed")
            tables = set(inspect(connection).get_table_names())
            heads = set(MigrationContext.configure(connection).get_current_heads())
            if tables and heads != {SCHEMA_HEAD}:
                raise RuntimeError("Nonempty review database requires explicit schema review")
        if not tables:
            environment = dict(os.environ)
            environment.update({
                "APP_ENV": "staging", "SUPPLYOS_OWNED_TEST_ENV": "1",
                "DATABASE_URL_SYNC": url.render_as_string(hide_password=False),
                "PYTHONDONTWRITEBYTECODE": "1",
            })
            source = WORKSPACE / ".runtime" / "core-publication" / "repo" / "backend"
            environment["PYTHONPATH"] = str(source)
            with OwnedProcessGroup() as processes:
                processes.run([sys.executable, "-B", "-m", "alembic", "upgrade", "head"],
                              cwd=source, environment=environment, output=subprocess.DEVNULL,
                              timeout=180, check=True)
        with engine.connect() as connection:
            if (set(MigrationContext.configure(connection).get_current_heads()) != {SCHEMA_HEAD}
                    or compare_metadata(MigrationContext.configure(connection), Base.metadata)):
                raise RuntimeError("Review migration schema does not match the application")
    finally:
        engine.dispose()


def migrate_review() -> None:
    source = WORKSPACE / ".runtime" / "core-publication" / "repo"
    revision = subprocess.run(["git", "--no-optional-locks", "rev-parse", "HEAD"], cwd=source, capture_output=True,
                              text=True, timeout=15, check=True).stdout.strip()
    status = subprocess.run(["git", "--no-optional-locks", "status", "--porcelain"], cwd=source, capture_output=True,
                            text=True, timeout=15, check=True).stdout.strip()
    if revision != CORE_COMMIT or status:
        raise RuntimeError("Migration requires the clean, pinned publication clone")
    database = load("database-connection.json")["data"]
    live = api_request("GET", f"/postgres/{DATABASE_ID}")
    for value in (database, live):
        owner = value.get("ownerId") or value.get("owner", {}).get("id")
        if (value.get("id") != DATABASE_ID or value.get("databaseName") != "supplyos_review"
                or value.get("databaseUser") != "supplyos_review_user" or value.get("plan") != "free"
                or value.get("region") != "singapore" or owner != OWNER
                or value.get("ipAllowList") != []):
            raise RuntimeError("Dedicated private review database validation failed")
    url = make_url(database["connectionInfo"]["externalConnectionString"])
    if (url.database != "supplyos_review" or url.username != "supplyos_review_user"
            or not (url.host or "").endswith(".singapore-postgres.render.com")):
        raise RuntimeError("Unexpected external review database endpoint")
    url = url.set(drivername="postgresql+psycopg2", query={
        "sslmode": "verify-full", "sslrootcert": certifi.where(), "connect_timeout": "15",
        "application_name": "supplyos_review_migration",
        "options": "-c statement_timeout=120000 -c lock_timeout=10000",
    })
    response = requests.get("https://api.ipify.org", params={"format": "json"}, timeout=15)
    response.raise_for_status()
    address = str(IPv4Address(response.json()["ip"]))
    if not IPv4Address(address).is_global:
        raise RuntimeError("Migration egress must be a public IPv4 address")
    window = [{"cidrBlock": address + "/32", "description": "SupplyOS explicit review migration"}]
    try:
        api_request("PATCH", f"/postgres/{DATABASE_ID}", {"ipAllowList": window})
        if api_request("GET", f"/postgres/{DATABASE_ID}").get("ipAllowList") != window:
            raise RuntimeError("Exact single-source migration access could not be verified")
        print("Dedicated single-source TLS migration window opened; credentials are not displayed.", flush=True)
        migrate_database(url)
    finally:
        api_request("PATCH", f"/postgres/{DATABASE_ID}", {"ipAllowList": []})
        if api_request("GET", f"/postgres/{DATABASE_ID}").get("ipAllowList") != []:
            raise RuntimeError("Review database external-access closure could not be verified")
        print("Review database external access restored to deny-all.", flush=True)
    print(json.dumps({"migrated": DATABASE_ID, "revision": SCHEMA_HEAD,
                      "certificate_and_hostname_verified": True, "external_access": "disabled"}))


def review_environment() -> dict[str, str]:
    if (PRIVATE / "review-environment.json").exists():
        return load("review-environment.json")
    database = load("database-connection.json")["data"]
    cache = load("cache-connection.json")["data"]
    if database["id"] != "dpg-dbs9uqdg1s2s73ejssbg-a" or database["plan"] != "free" or database["databaseName"] != "supplyos_review":
        raise RuntimeError("Dedicated review database validation failed")
    if cache["id"] != "red-dbs9uq3m8hqs73c62jp0" or cache["plan"] != "free":
        raise RuntimeError("Dedicated review cache validation failed")
    url = make_url(database["connectionInfo"]["internalConnectionString"])
    values = {
        "APP_ENV": "staging", "API_V1_PREFIX": "/api/v1", "FREE_ONLY_MODE": "true",
        "APPROVED_FREE_SMTP": "false", "SMTP_ENABLED": "false", "PROOF_STORAGE_BACKEND": "local",
        "PROOF_STORAGE_DIR": "/app/.runtime/review-proofs", "FRONTEND_URL": WEB_URL,
        "PASSWORD_RESET_URL": WEB_URL + "/reset-password", "COOKIE_SECURE": "true", "COOKIE_SAMESITE": "lax",
        "JWT_SECRET": secrets.token_urlsafe(48), "SETUP_AUTHORIZATION_TOKEN": secrets.token_urlsafe(48),
        "DATABASE_URL": url.set(drivername="postgresql+asyncpg", query={"ssl": "require"}).render_as_string(hide_password=False),
        "DATABASE_URL_SYNC": url.set(drivername="postgresql+psycopg2", query={"sslmode": "require"}).render_as_string(hide_password=False),
        "REDIS_URL": cache["connectionInfo"]["internalConnectionString"],
    }
    save("review-environment.json", values)
    return values


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["create-db", "create-cache", "db-private", "cache-private", "inspect-private-schema", "create-backend", "create-web", "configure-backend", "configure-web", "inspect-services", "migrate-db", "configure-health"])
    parser.add_argument("--id")
    args = parser.parse_args()
    if args.action == "inspect-services":
        inspect_services()
        return
    if args.action == "migrate-db":
        migrate_review()
        return
    if args.action == "configure-health":
        inspect_services()
        for identifier, path in ((BACKEND_ID, "/api/health/deep"), (WEB_ID, "/login")):
            api_request("PATCH", f"/services/{identifier}", {"serviceDetails": {"healthCheckPath": path}})
        print("Dedicated review health checks configured; free plans and startup commands unchanged.")
        return
    if args.action in {"configure-backend", "configure-web"}:
        backend = args.action == "configure-backend"
        values = review_environment() if backend else {
            "NODE_ENV": "production", "BACKEND_URL": API_URL, "NEXT_TELEMETRY_DISABLED": "1", "PORT": "3000",
        }
        api_put(BACKEND_ID if backend else WEB_ID, values)
        print(json.dumps({"configured": BACKEND_ID if backend else WEB_ID, "private_values_not_displayed": True}))
        return
    if args.action == "inspect-private-schema":
        def shape(value):
            if isinstance(value, dict):
                return {key: shape(item) for key, item in value.items()}
            if isinstance(value, list):
                return [shape(value[0])] if value else []
            return type(value).__name__
        print(json.dumps({"database": shape(load("database-connection.json")),
                          "cache": shape(load("cache-connection.json"))}))
        return
    if args.action in {"create-backend", "create-web"}:
        backend = args.action == "create-backend"
        data = render(["services", "create", "--confirm", "--name", NAME + ("-api" if backend else "-web"),
                       "--type", "web_service", "--runtime", "docker", "--plan", "free", "--region", "singapore",
                       "--repo", "https://github.com/NileshSingh9245/SupplyOS", "--branch", "main",
                       "--root-directory", "backend" if backend else "frontend", "--auto-deploy=false"])
        save("backend-service.json" if backend else "web-service.json", data)
    elif args.action == "create-db":
        data = render(["postgres", "create", "--confirm", "--workspace", OWNER, "--name", NAME,
                       "--plan", "free", "--version", "15", "--region", "singapore",
                       "--database-name", "supplyos_review", "--connection-pool", "none"])
        save("database.json", data)
    elif args.action == "create-cache":
        data = render(["keyvalues", "create", "--confirm", "--workspace", OWNER, "--name", NAME,
                       "--plan", "free", "--region", "singapore", "--memory-policy", "noeviction"])
        save("cache.json", data)
    else:
        prefix = "dpg-" if args.action == "db-private" else "red-"
        if not args.id or not args.id.startswith(prefix):
            raise RuntimeError("A discovered scoped datastore ID is required")
        command = "postgres" if args.action == "db-private" else "keyvalues"
        data = render([command, "get", args.id, "--include-sensitive-connection-info"])
        save("database-connection.json" if command == "postgres" else "cache-connection.json", data)
    candidate = data.get("data", data) if isinstance(data, dict) else {}
    resource = candidate.get("postgres", candidate.get("keyValue", candidate.get("service", candidate)))
    public = {key: resource.get(key) for key in ("id", "name", "plan", "status", "region", "dashboardUrl") if key in resource}
    details = resource.get("serviceDetails", {})
    if details:
        public["url"] = details.get("url")
        public["plan"] = details.get("plan")
    print(json.dumps({"resource": public, "private_configuration_saved": True}))


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, ValueError, OSError, KeyError, TypeError, subprocess.SubprocessError,
            requests.RequestException, SQLAlchemyError):
        print("Review provisioning failed; no connection credentials displayed.", file=sys.stderr)
        raise SystemExit(1)
