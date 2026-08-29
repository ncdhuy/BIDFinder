"""Verified TLS compatibility and developer diagnostics for MSC."""

from __future__ import annotations

import platform
import socket
import ssl
from typing import Any
from urllib.parse import urlsplit


DEFAULT_MSC_ENDPOINT = "https://muasamcong.mpi.gov.vn/search_prc"
MSC_TLS_CIPHER_POLICY = "ECDHE+AESGCM:ECDHE+CHACHA20"


def create_msc_ssl_context() -> ssl.SSLContext:
    """Create MSC's verified TLS context without weakening OpenSSL policy."""

    context = ssl.create_default_context()
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.set_ciphers(MSC_TLS_CIPHER_POLICY)
    return context


def is_dh_key_too_small(error: BaseException) -> bool:
    """Identify only the known finite-field DH interoperability failure."""

    pending: list[BaseException] = [error]
    seen: set[int] = set()
    while pending:
        current = pending.pop()
        if id(current) in seen:
            continue
        seen.add(id(current))
        if "DH_KEY_TOO_SMALL" in str(current).upper():
            return True
        for related in (
            getattr(current, "reason", None),
            getattr(current, "__cause__", None),
            getattr(current, "__context__", None),
        ):
            if isinstance(related, BaseException):
                pending.append(related)
    return False


def _handshake(context: ssl.SSLContext, endpoint: str, timeout: float) -> tuple[str | None, str | None]:
    parsed = urlsplit(endpoint)
    if parsed.scheme != "https" or not parsed.hostname:
        raise ValueError("MSC diagnostic endpoint must be an https URL with a hostname")
    with socket.create_connection((parsed.hostname, parsed.port or 443), timeout=timeout) as raw:
        with context.wrap_socket(raw, server_hostname=parsed.hostname) as tls_socket:
            cipher = tls_socket.cipher()
            return tls_socket.version(), cipher[0] if cipher else None


def _safe_error(error: BaseException) -> dict[str, Any]:
    return {
        "type": type(error).__name__,
        "message": str(error),
        "dh_key_too_small": is_dh_key_too_small(error),
    }


def _tls12_cipher_names(context: ssl.SSLContext) -> list[str]:
    return [cipher["name"] for cipher in context.get_ciphers() if cipher["protocol"] != "TLSv1.3"]


def diagnose_msc_tls(endpoint: str = DEFAULT_MSC_ENDPOINT, timeout: float = 15.0) -> dict[str, Any]:
    """Run safe TLS-only diagnostics; never sends cookies or HTTP response data."""

    standard = ssl.create_default_context()
    compatible = create_msc_ssl_context()
    result: dict[str, Any] = {
        "python_version": platform.python_version(),
        "openssl_version": ssl.OPENSSL_VERSION,
        "default_security_level": getattr(standard, "security_level", None),
        "msc_security_level": getattr(compatible, "security_level", None),
        "msc_minimum_version": compatible.minimum_version.name,
        "standard_tls12_finite_field_dhe_ciphers": [
            name for name in _tls12_cipher_names(standard) if name.startswith("DHE-")
        ],
        "msc_tls12_ciphers": _tls12_cipher_names(compatible),
    }
    for label, context in (("standard", standard), ("msc_ecdhe", compatible)):
        try:
            protocol, cipher = _handshake(context, endpoint, timeout)
        except Exception as error:  # diagnostic must report failures without response data
            result[f"{label}_handshake"] = {"status": "FAIL", **_safe_error(error)}
        else:
            result[f"{label}_handshake"] = {
                "status": "PASS",
                "protocol": protocol,
                "cipher": cipher,
            }
    return result
