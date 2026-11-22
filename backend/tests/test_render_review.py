"""Offline guards for the scoped review migration operator; never contacts Render."""
from __future__ import annotations

from copy import deepcopy
from types import SimpleNamespace

import pytest

from tools import render_review as review


@pytest.fixture
def migration(monkeypatch):
    database = {
        "id": review.DATABASE_ID, "databaseName": "supplyos_review",
        "databaseUser": "supplyos_review_user", "plan": "free", "region": "singapore",
        "ownerId": review.OWNER, "ipAllowList": [],
        "connectionInfo": {
            "externalConnectionString": "postgresql://supplyos_review_user@review-test.singapore-postgres.render.com/supplyos_review",
        },
    }
    state = {"database": database, "calls": [], "urls": []}
    monkeypatch.setattr(review.subprocess, "run", lambda arguments, **kwargs: SimpleNamespace(
        stdout=review.CORE_COMMIT if "rev-parse" in arguments else "",
    ))
    monkeypatch.setattr(review, "load", lambda name: {"data": deepcopy(database)})

    def request(method, path, payload=None):
        state["calls"].append((method, path, payload))
        if method == "PATCH":
            state["database"]["ipAllowList"] = deepcopy(payload["ipAllowList"])
        return deepcopy(state["database"])

    monkeypatch.setattr(review, "api_request", request)
    monkeypatch.setattr(review.requests, "get", lambda *args, **kwargs: SimpleNamespace(
        raise_for_status=lambda: None, json=lambda: {"ip": "8.8.8.8"},
    ))
    monkeypatch.setattr(review, "migrate_database", lambda url: state["urls"].append(url))
    return state


def test_migration_uses_verified_tls_and_closes_external_access(migration, capsys):
    review.migrate_review()
    patches = [call[2] for call in migration["calls"] if call[0] == "PATCH"]
    assert patches[0]["ipAllowList"][0]["cidrBlock"] == "8.8.8.8/32"
    assert patches[-1] == {"ipAllowList": []}
    assert migration["database"]["ipAllowList"] == []
    assert len(migration["urls"]) == 1
    url = migration["urls"][0]
    assert url.drivername == "postgresql+psycopg2"
    assert url.query["sslmode"] == "verify-full"
    assert url.query["sslrootcert"]
    output = capsys.readouterr().out
    assert "8.8.8.8" not in output
    assert "review-test.singapore-postgres.render.com" not in output
    assert review.SCHEMA_HEAD in output


def test_failed_migration_still_closes_external_access(migration, monkeypatch, capsys):
    def fail(url):
        raise RuntimeError("Synthetic migration failure")

    monkeypatch.setattr(review, "migrate_database", fail)
    with pytest.raises(RuntimeError, match="Synthetic migration failure"):
        review.migrate_review()
    assert migration["database"]["ipAllowList"] == []
    assert migration["calls"][-1][0] == "GET"
    assert "restored to deny-all" in capsys.readouterr().out


@pytest.mark.parametrize("field,value", [
    ("id", "dpg-unrelated"), ("ownerId", "tea-unrelated"), ("plan", "starter"),
    ("databaseName", "unrelated"), ("region", "oregon"),
    ("ipAllowList", [{"cidrBlock": "0.0.0.0/0"}]),
])
def test_changed_database_is_rejected_before_mutation(migration, field, value):
    migration["database"][field] = value
    with pytest.raises(RuntimeError, match="database validation failed"):
        review.migrate_review()
    assert all(call[0] == "GET" for call in migration["calls"])
    assert migration["urls"] == []


@pytest.mark.parametrize("revision,status", [
    ("0" * 40, ""), (review.CORE_COMMIT, " M backend/alembic/env.py"),
])
def test_dirty_or_unpinned_source_is_rejected(migration, monkeypatch, revision, status):
    monkeypatch.setattr(review.subprocess, "run", lambda arguments, **kwargs: SimpleNamespace(
        stdout=revision if "rev-parse" in arguments else status,
    ))
    with pytest.raises(RuntimeError, match="clean, pinned publication clone"):
        review.migrate_review()
    assert migration["calls"] == []


def test_external_endpoint_mismatch_is_rejected(migration):
    migration["database"]["connectionInfo"]["externalConnectionString"] = (
        "postgresql://supplyos_review_user@example.com/supplyos_review"
    )
    with pytest.raises(RuntimeError, match="Unexpected external"):
        review.migrate_review()
    assert all(call[0] == "GET" for call in migration["calls"])


@pytest.mark.parametrize("method,path,payload", [
    ("PUT", "/services/srv-unrelated/env-vars", []),
    ("PATCH", f"/postgres/{review.DATABASE_ID}", {"plan": "starter"}),
    ("PATCH", f"/services/{review.BACKEND_ID}", {"serviceDetails": {"plan": "starter"}}),
    ("POST", f"/services/{review.BACKEND_ID}/deploys", {}),
])
def test_unrelated_or_billing_api_writes_fail_before_credentials(monkeypatch, method, path, payload):
    def unexpected(arguments):
        pytest.fail("Rejected operation reached authorization", pytrace=False)

    monkeypatch.setattr(review, "render", unexpected)
    with pytest.raises(RuntimeError):
        review.api_request(method, path, payload)


def test_missing_operator_yaml_does_not_contact_render(monkeypatch):
    monkeypatch.setitem(review.sys.modules, "yaml", None)
    monkeypatch.setattr(review, "render", lambda arguments: pytest.fail("Missing parser reached authorization"))
    with pytest.raises(RuntimeError, match="operator-only PyYAML"):
        review.api_request("GET", f"/services/{review.BACKEND_ID}")


def test_malformed_yaml_does_not_echo_private_parser_details(monkeypatch):
    class ParserFailure(Exception):
        pass

    def fail(value):
        raise ParserFailure("private fixture snippet")

    monkeypatch.setitem(review.sys.modules, "yaml", SimpleNamespace(YAMLError=ParserFailure, safe_load=fail))
    monkeypatch.setattr(review, "render", lambda arguments: {})
    monkeypatch.setattr(review.Path, "read_text", lambda *args, **kwargs: "private fixture input")
    with pytest.raises(RuntimeError, match="configuration is malformed") as failure:
        review.api_request("GET", f"/services/{review.BACKEND_ID}")
    assert "private fixture" not in str(failure.value)
    assert failure.value.__suppress_context__


def test_unverified_migration_window_is_closed_without_connecting(migration, monkeypatch):
    request = review.api_request

    def mismatch(method, path, payload=None):
        result = request(method, path, payload)
        if method == "GET" and result["ipAllowList"]:
            result["ipAllowList"] = []
        return result

    monkeypatch.setattr(review, "api_request", mismatch)
    with pytest.raises(RuntimeError, match="single-source migration access"):
        review.migrate_review()
    assert migration["urls"] == []
    assert migration["database"]["ipAllowList"] == []
