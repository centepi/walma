# pipeline_scripts/storekit_verifier.py
from __future__ import annotations

import base64
import json
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union


# NOTE:
# This verifier is designed for StoreKit 2 JWS blobs like:
# - signedTransactionInfo (App Store Server API / Notifications V2)
# - signedRenewalInfo
#
# It verifies:
#   1) JWS signature using the leaf cert in the x5c chain
#   2) (optional but recommended) cert chain validation to a trusted Apple root you provide
#   3) payload expectations (bundleId, environment, productId, etc.)
#
# Why "optional chain validation"?
# - Proper trust requires pinning to Apple roots.
# - The safest approach is to supply Apple root(s) PEM via your own config.
# - This file works without roots (signature still verified), but that is weaker trust.


# ----------------------------
# Utilities
# ----------------------------

def _b64url_decode(data: str) -> bytes:
    s = data.encode("utf-8")
    rem = len(s) % 4
    if rem:
        s += b"=" * (4 - rem)
    return base64.urlsafe_b64decode(s)


def _b64std_decode(data: str) -> bytes:
    s = data.encode("utf-8")
    rem = len(s) % 4
    if rem:
        s += b"=" * (4 - rem)
    return base64.b64decode(s)


def _json_loads(b: bytes) -> Dict[str, Any]:
    return json.loads(b.decode("utf-8"))


def _now_ms() -> int:
    return int(time.time() * 1000)


def _read_any(payload: Dict[str, Any], *keys: str) -> Any:
    for k in keys:
        if k in payload:
            return payload.get(k)
    return None


# ----------------------------
# Crypto / X509
# ----------------------------

class StoreKitVerificationError(Exception):
    pass


try:
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import ec, rsa, padding
except Exception as e:  # pragma: no cover
    raise StoreKitVerificationError(
        "cryptography is required for storekit_verifier.py (pip install cryptography)"
    ) from e


def _load_x509_from_der(der: bytes) -> "x509.Certificate":
    try:
        return x509.load_der_x509_certificate(der)
    except Exception as e:
        raise StoreKitVerificationError(f"Failed to parse x5c certificate DER: {e}") from e


def _verify_jws_signature_es256(public_key, signing_input: bytes, signature: bytes) -> None:
    """
    JWS ES256 signatures are raw R|S (64 bytes), whereas cryptography expects DER.
    """
    if len(signature) != 64:
        raise StoreKitVerificationError(f"ES256 signature length invalid: {len(signature)} (expected 64)")

    r = int.from_bytes(signature[:32], "big")
    s = int.from_bytes(signature[32:], "big")

    try:
        der_sig = utils_encode_dss_signature(r, s)
    except Exception as e:
        raise StoreKitVerificationError(f"Failed to DER-encode ECDSA signature: {e}") from e

    try:
        public_key.verify(der_sig, signing_input, ec.ECDSA(hashes.SHA256()))
    except Exception as e:
        raise StoreKitVerificationError(f"JWS signature verify failed (ES256): {e}") from e


def _verify_jws_signature_rs256(public_key, signing_input: bytes, signature: bytes) -> None:
    try:
        public_key.verify(signature, signing_input, padding.PKCS1v15(), hashes.SHA256())
    except Exception as e:
        raise StoreKitVerificationError(f"JWS signature verify failed (RS256): {e}") from e


def _verify_cert_signed_by(child: "x509.Certificate", issuer: "x509.Certificate") -> None:
    """
    Verifies that `child` was signed by `issuer` (signature check only).
    """
    pub = issuer.public_key()
    try:
        if isinstance(pub, rsa.RSAPublicKey):
            pub.verify(
                child.signature,
                child.tbs_certificate_bytes,
                padding.PKCS1v15(),
                child.signature_hash_algorithm,
            )
        elif isinstance(pub, ec.EllipticCurvePublicKey):
            pub.verify(
                child.signature,
                child.tbs_certificate_bytes,
                ec.ECDSA(child.signature_hash_algorithm),
            )
        else:
            raise StoreKitVerificationError(f"Unsupported issuer public key type: {type(pub)}")
    except Exception as e:
        raise StoreKitVerificationError(f"Certificate chain signature verify failed: {e}") from e


def _check_cert_time_valid(cert: "x509.Certificate", now_ts: Optional[float] = None) -> None:
    now = now_ts or time.time()
    # cryptography uses naive datetimes in UTC for not_valid_before/after
    nvb = cert.not_valid_before.timestamp()
    nva = cert.not_valid_after.timestamp()
    if now < nvb or now > nva:
        raise StoreKitVerificationError("Certificate is not currently time-valid.")


def _normalize_pem_list(pem_roots: Union[str, Sequence[str], None]) -> List[bytes]:
    if pem_roots is None:
        return []
    if isinstance(pem_roots, str):
        pem_roots = [pem_roots]
    out: List[bytes] = []
    for p in pem_roots:
        b = p.encode("utf-8") if isinstance(p, str) else p
        out.append(b)
    return out


def _load_roots_from_pem(pem_roots: Union[str, Sequence[str], None]) -> List["x509.Certificate"]:
    roots: List["x509.Certificate"] = []
    for pem in _normalize_pem_list(pem_roots):
        try:
            roots.append(x509.load_pem_x509_certificate(pem))
        except Exception as e:
            raise StoreKitVerificationError(f"Failed loading trusted root PEM: {e}") from e
    return roots


def _subject_fingerprint(cert: "x509.Certificate") -> str:
    try:
        return cert.fingerprint(hashes.SHA256()).hex()
    except Exception:
        return ""


def _validate_chain_if_roots_provided(
    chain: List["x509.Certificate"],
    trusted_roots_pem: Union[str, Sequence[str], None],
) -> None:
    """
    Validates x5c chain signatures up to a trusted root, if roots are provided.

    chain is expected leaf->intermediate->... (as provided in x5c).
    """
    roots = _load_roots_from_pem(trusted_roots_pem)
    if not roots:
        return  # chain validation skipped

    # Basic time validity for each cert
    now = time.time()
    for c in chain:
        _check_cert_time_valid(c, now_ts=now)

    # Verify chain signatures for each step
    for i in range(len(chain) - 1):
        child = chain[i]
        issuer = chain[i + 1]
        _verify_cert_signed_by(child, issuer)

    # Last cert in x5c should be signed by one of our trusted roots OR equal to a root
    last = chain[-1]

    for root in roots:
        # If identical to root by fingerprint: accept
        if _subject_fingerprint(last) == _subject_fingerprint(root) and _subject_fingerprint(last):
            return
        # Else verify last signed by root
        try:
            _verify_cert_signed_by(last, root)
            return
        except Exception:
            continue

    raise StoreKitVerificationError("Certificate chain did not validate to a trusted root.")


# cryptography helper (kept local to avoid importing from private modules)
def utils_encode_dss_signature(r: int, s: int) -> bytes:
    # Equivalent to cryptography.hazmat.primitives.asymmetric.utils.encode_dss_signature
    # but we import it lazily to reduce top-level imports.
    from cryptography.hazmat.primitives.asymmetric.utils import encode_dss_signature
    return encode_dss_signature(r, s)


# ----------------------------
# Public API
# ----------------------------

@dataclass(frozen=True)
class VerifiedJWS:
    header: Dict[str, Any]
    payload: Dict[str, Any]
    signing_input: bytes


def verify_and_decode_jws(
    jws_compact: str,
    *,
    trusted_roots_pem: Union[str, Sequence[str], None] = None,
) -> VerifiedJWS:
    """
    Verifies a compact JWS:
      base64url(header).base64url(payload).base64url(signature)

    - Verifies signature using x5c[0] leaf cert public key.
    - Optionally validates x5c chain to provided trusted roots.
    - Returns decoded header + payload.
    """
    raw = (jws_compact or "").strip()
    parts = raw.split(".")
    if len(parts) != 3:
        raise StoreKitVerificationError("Invalid JWS format (expected 3 dot-separated parts).")

    header_b64, payload_b64, sig_b64 = parts
    header = _json_loads(_b64url_decode(header_b64))
    payload = _json_loads(_b64url_decode(payload_b64))
    signature = _b64url_decode(sig_b64)

    alg = (header.get("alg") or "").strip()
    x5c_list = header.get("x5c") or []
    if not isinstance(x5c_list, list) or not x5c_list:
        raise StoreKitVerificationError("Missing x5c certificate chain in JWS header.")

    # Parse certificates (x5c is standard base64 DER, not base64url)
    cert_chain: List["x509.Certificate"] = []
    for idx, c_b64 in enumerate(x5c_list):
        if not isinstance(c_b64, str) or not c_b64.strip():
            raise StoreKitVerificationError(f"Invalid x5c entry at index {idx}.")
        der = _b64std_decode(c_b64.strip())
        cert_chain.append(_load_x509_from_der(der))

    # If roots provided, validate the chain (leaf->...->root)
    _validate_chain_if_roots_provided(cert_chain, trusted_roots_pem)

    # Verify signature with leaf cert public key
    leaf_pub = cert_chain[0].public_key()
    signing_input = f"{header_b64}.{payload_b64}".encode("utf-8")

    if alg == "ES256":
        _verify_jws_signature_es256(leaf_pub, signing_input, signature)
    elif alg == "RS256":
        _verify_jws_signature_rs256(leaf_pub, signing_input, signature)
    else:
        raise StoreKitVerificationError(f"Unsupported JWS alg: {alg}")

    return VerifiedJWS(header=header, payload=payload, signing_input=signing_input)


def assert_transaction_payload(
    payload: Dict[str, Any],
    *,
    bundle_id: Optional[str] = None,
    environment: Optional[str] = None,
    product_ids: Optional[Sequence[str]] = None,
) -> None:
    """
    Validates common StoreKit 2 transaction payload expectations.
    Keys are typically camelCase in Apple's payloads, but we read a few aliases.
    """
    if bundle_id:
        got = _read_any(payload, "bundleId", "bundle_id")
        if isinstance(got, str) and got != bundle_id:
            raise StoreKitVerificationError(f"bundleId mismatch: {got} != {bundle_id}")

    if environment:
        got_env = _read_any(payload, "environment", "env")
        if isinstance(got_env, str) and got_env.lower() != environment.lower():
            raise StoreKitVerificationError(f"environment mismatch: {got_env} != {environment}")

    if product_ids:
        got_pid = _read_any(payload, "productId", "product_id", "productID")
        if isinstance(got_pid, str) and got_pid not in set(product_ids):
            raise StoreKitVerificationError(f"productId not allowed: {got_pid}")


def assert_not_expired(payload: Dict[str, Any], *, now_ms: Optional[int] = None) -> None:
    """
    Best-effort expiry check:
    - if expiresDate exists, it must be in the future
    - if revocationDate exists, treat as not active
    """
    now = int(now_ms or _now_ms())

    rev = _read_any(payload, "revocationDate", "revocation_date")
    if isinstance(rev, int) and rev > 0 and rev <= now:
        raise StoreKitVerificationError("Transaction is revoked.")

    exp = _read_any(payload, "expiresDate", "expires_date", "expirationDate", "expiration_date")
    if isinstance(exp, int) and exp > 0 and exp <= now:
        raise StoreKitVerificationError("Transaction is expired.")


def verify_storekit2_transaction(
    signed_transaction_info_jws: str,
    *,
    trusted_roots_pem: Union[str, Sequence[str], None] = None,
    bundle_id: Optional[str] = None,
    environment: Optional[str] = None,
    product_ids: Optional[Sequence[str]] = None,
    require_active: bool = True,
) -> Dict[str, Any]:
    """
    Verifies and decodes signedTransactionInfo and returns its payload.
    If require_active=True, checks revocation/expiration when fields exist.
    """
    v = verify_and_decode_jws(signed_transaction_info_jws, trusted_roots_pem=trusted_roots_pem)
    assert_transaction_payload(v.payload, bundle_id=bundle_id, environment=environment, product_ids=product_ids)
    if require_active:
        assert_not_expired(v.payload)
    return v.payload


def verify_storekit2_renewal(
    signed_renewal_info_jws: str,
    *,
    trusted_roots_pem: Union[str, Sequence[str], None] = None,
    bundle_id: Optional[str] = None,
    environment: Optional[str] = None,
    product_ids: Optional[Sequence[str]] = None,
) -> Dict[str, Any]:
    """
    Verifies and decodes signedRenewalInfo and returns its payload.
    """
    v = verify_and_decode_jws(signed_renewal_info_jws, trusted_roots_pem=trusted_roots_pem)
    assert_transaction_payload(v.payload, bundle_id=bundle_id, environment=environment, product_ids=product_ids)
    return v.payload


def extract_subscription_active_from_transaction_payload(payload: Dict[str, Any], *, now_ms: Optional[int] = None) -> bool:
    """
    Returns whether the transaction payload indicates an active subscription *right now*.
    This is a helper (you can enforce your own policy).
    """
    now = int(now_ms or _now_ms())

    rev = _read_any(payload, "revocationDate", "revocation_date")
    if isinstance(rev, int) and rev > 0 and rev <= now:
        return False

    exp = _read_any(payload, "expiresDate", "expires_date", "expirationDate", "expiration_date")
    if isinstance(exp, int) and exp > 0:
        return exp > now

    # If no expiration is provided, we can't assert active from this alone.
    return False