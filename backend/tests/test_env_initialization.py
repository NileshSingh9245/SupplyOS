"""Private configuration creation is non-destructive and does not expose secrets."""
from pathlib import Path

from tools.init_env import initialize


def test_creates_configuration_with_a_private_signing_secret(tmp_path):
    path = tmp_path / ".env"
    assert initialize(path) is True
    fields = dict(
        line.split("=", 1) for line in path.read_text(encoding="utf-8").splitlines()
        if line and not line.startswith("#")
    )
    if len(fields["JWT_SECRET"]) < 32:
        raise AssertionError("Private signing material is insufficient")
    assert fields["DATABASE_URL"] == ""
    assert fields["DATABASE_URL_SYNC"] == ""
    assert fields["REDIS_URL"] == ""
    assert fields["ANTHROPIC_API_KEY"] == ""


def test_existing_private_configuration_is_never_overwritten(tmp_path):
    path = tmp_path / ".env"
    path.write_text("existing private configuration", encoding="utf-8")
    assert initialize(path) is False
    assert path.read_text(encoding="utf-8") == "existing private configuration"
