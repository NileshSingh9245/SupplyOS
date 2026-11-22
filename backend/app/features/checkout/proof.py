"""Purpose-bound accepted terms, not an authentication token or client price authority."""
from __future__ import annotations

import base64
import hashlib
import hmac
import re

from pydantic import ValidationError

from app.core.exceptions import DomainError
from app.features.checkout.schemas import QuoteClaim


def _key(secret: str) -> bytes:
    return hmac.new(secret.encode("utf-8"), b"supplyos.order-quote.v1", hashlib.sha256).digest()


def encode_quote(claim: QuoteClaim, *, secret: str) -> str:
    encoded = base64.urlsafe_b64encode(claim.model_dump_json().encode("utf-8")).rstrip(b"=")
    signature = hmac.new(_key(secret), encoded, hashlib.sha256).digest()
    result = encoded.decode("ascii") + "." + base64.urlsafe_b64encode(signature).rstrip(b"=").decode("ascii")
    if len(result) > 32768:
        raise DomainError("The quote is too large; reduce the number of items")
    return result


def decode_quote(proof: str, *, secret: str) -> QuoteClaim:
    try:
        if len(proof) > 32768 or not re.fullmatch(r"[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+", proof):
            raise ValueError()
        encoded, signature = proof.split(".")
        actual = base64.b64decode(signature + "=" * (-len(signature) % 4), altchars=b"-_", validate=True)
        if base64.urlsafe_b64encode(actual).rstrip(b"=").decode("ascii") != signature:
            raise ValueError()
        expected = hmac.new(_key(secret), encoded.encode("ascii"), hashlib.sha256).digest()
        if not hmac.compare_digest(actual, expected):
            raise ValueError()
        data = base64.b64decode(encoded + "=" * (-len(encoded) % 4), altchars=b"-_", validate=True)
        if base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii") != encoded:
            raise ValueError()
        claim = QuoteClaim.model_validate_json(data)
        if claim.expires_at.tzinfo is None:
            raise ValueError()
        return claim
    except (ValueError, UnicodeError, ValidationError):
        raise DomainError("The accepted quote could not be validated") from None
