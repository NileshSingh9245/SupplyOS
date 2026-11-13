"""Private image receipts on the owned real API; no arbitrary external URL proof."""
from __future__ import annotations

import io
import uuid

import requests
import pytest
from PIL import Image


def success(response, code=200):
    if response.status_code != code:
        pytest.fail(f"Owned proof fixture failed (HTTP {response.status_code})", pytrace=False)
    return response.json()


def png():
    buffer = io.BytesIO()
    Image.new("RGB", (8, 8), color="white").save(buffer, format="PNG")
    return buffer.getvalue()


@pytest.fixture(scope="module")
def proof_delivery(admin_session, api_prefix):
    buyer = success(admin_session.post(f"{api_prefix}/customers", json={"name": "Proof fixture", "customer_type": "cash"}, timeout=10), 201)["id"]
    product = success(admin_session.post(f"{api_prefix}/products", json={"sku": f"PROOF-{uuid.uuid4().hex[:8]}", "name": "Proof fixture", "base_price": "10.00"}, timeout=10), 201)["id"]
    warehouse = success(admin_session.get(f"{api_prefix}/warehouses", timeout=10))[0]["id"]
    success(admin_session.post(f"{api_prefix}/inventory/adjust", json={"product_id": product, "warehouse_id": warehouse, "delta_qty": "1"}, timeout=10))
    order = success(admin_session.post(f"{api_prefix}/orders", json={"customer_id": buyer, "warehouse_id": warehouse, "items": [{"product_id": product, "quantity": "1"}]}, timeout=10), 201)["id"]
    for action in ("reserve", "pick", "pack", "dispatch"):
        success(admin_session.post(f"{api_prefix}/orders/{order}/{action}", timeout=10))
    return next(row["id"] for row in success(admin_session.get(f"{api_prefix}/deliveries", timeout=10)) if row["order_id"] == order)


def upload(admin_session, api_prefix, delivery, kind="photo", data=None):
    return admin_session.post(
        f"{api_prefix}/deliveries/{delivery}/proofs", data={"kind": kind},
        files={"file": ("untrusted-name.png", png() if data is None else data, "image/png")},
        headers={"Content-Type": None}, timeout=15,
    )


def test_uploaded_proof_is_private_validated_and_delivery_bound(admin_session, api_prefix, proof_delivery):
    photo = success(upload(admin_session, api_prefix, proof_delivery), 201)
    assert photo["kind"] == "photo"
    assert photo["delivery_id"] == proof_delivery
    assert photo["mime_type"] == "image/png"
    assert photo["url"] == f"/api/v1/delivery-proofs/{photo['id']}"
    signed_in = admin_session.get(f"{api_prefix}/delivery-proofs/{photo['id']}", timeout=10)
    assert signed_in.status_code == 200
    assert signed_in.headers["X-Content-Type-Options"] == "nosniff"
    assert signed_in.headers["Cache-Control"] == "private, no-store"
    assert signed_in.content == png()
    assert requests.get(f"{api_prefix}/delivery-proofs/{photo['id']}", timeout=10).status_code == 401


@pytest.mark.parametrize("content", [b"not an image", b"\x89PNG\r\n\x1a\nmalformed"])
def test_invalid_proof_upload_does_not_create_a_receipt(admin_session, api_prefix, proof_delivery, content):
    assert upload(admin_session, api_prefix, proof_delivery, data=content).status_code == 400


def test_arbitrary_kind_and_unknown_delivery_are_rejected(admin_session, api_prefix, proof_delivery):
    assert upload(admin_session, api_prefix, proof_delivery, kind="invoice").status_code == 422
    assert upload(admin_session, api_prefix, str(uuid.uuid4())).status_code == 404
