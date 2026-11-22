"""Create a new private backend configuration without printing signing material."""
from __future__ import annotations

import os
import secrets
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]


def initialize(path: Path) -> bool:
    if not path.parent.is_dir():
        raise RuntimeError("The private configuration parent must already exist")
    content = "\n".join([
        "# Private configuration. Never commit or share this file.",
        "APP_ENV=development",
        "FREE_ONLY_MODE=true",
        "APPROVED_FREE_SMTP=false",
        "API_V1_PREFIX=/api/v1",
        "DATABASE_URL=",
        "DATABASE_URL_SYNC=",
        "REDIS_URL=",
        f"JWT_SECRET={secrets.token_urlsafe(48)}",
        "FRONTEND_URL=http://localhost:3000",
        "COOKIE_SAMESITE=lax",
        "ANTHROPIC_API_KEY=",
        "AI_PROVIDER=anthropic",
        "AI_MODEL=claude-sonnet-4-5-20250929",
        "SMTP_ENABLED=false",
        "SMTP_HOST=",
        "SMTP_PORT=587",
        "SMTP_USERNAME=",
        "SMTP_PASSWORD=",
        "SMTP_FROM=",
        "SMTP_FROM_NAME=SupplyOS",
        "SMTP_TLS_MODE=starttls",
        "SMTP_TIMEOUT_SECONDS=10",
        "PASSWORD_RESET_URL=",
        "PASSWORD_RESET_CAPACITY=4",
        "PASSWORD_RESET_WINDOW_SECONDS=3600",
        "PASSWORD_RESET_MAX_REQUESTS_PER_IP=3",
        "PASSWORD_RESET_MAX_REQUESTS_PER_IDENTITY=3",
        "PASSWORD_RESET_COOLDOWN_SECONDS=60",
        "PASSWORD_RESET_RATE_LIMIT_TIMEOUT_SECONDS=0.5",
        "PASSWORD_RESET_WORK_TIMEOUT_SECONDS=10",
        "",
    ])
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        return False
    with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as output:
        output.write(content)
    return True


def main() -> int:
    path = BACKEND_ROOT / ".env"
    if path.exists() or (BACKEND_ROOT.parent / ".env").exists():
        print("Existing private configuration was left unchanged. Edit it locally as needed.")
        return 0
    if initialize(path):
        print("Created backend/.env with private signing material. No secret values are displayed.")
        print("Configure PostgreSQL and Redis in that file before running migrations or the API.")
    else:
        print("Existing private configuration was left unchanged.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
