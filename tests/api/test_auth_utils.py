import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from starlette.requests import Request


sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "apps" / "api"))
import auth_utils  # noqa: E402


def request(*, scheme="https", host="example.test", cookie="", authorization="", client=None, forwarded_proto="", forwarded_for=""):
    headers = []
    if cookie:
        headers.append((b"cookie", cookie.encode()))
    if authorization:
        headers.append((b"authorization", authorization.encode()))
    if forwarded_proto:
        headers.append((b"x-forwarded-proto", forwarded_proto.encode()))
    if forwarded_for:
        headers.append((b"x-forwarded-for", forwarded_for.encode()))
    return Request({
        "type": "http",
        "path": "/",
        "root_path": "",
        "query_string": b"",
        "scheme": scheme,
        "server": (host, 443),
        "client": client,
        "headers": headers,
    })


class AuthUtilsTest(unittest.TestCase):
    def test_normalization(self):
        self.assertEqual("user@example.com", auth_utils.normalize_email(" User@Example.COM "))
        self.assertEqual("Nguyễn Văn A", auth_utils.normalize_text("  Nguyễn Văn A  "))

    def test_cookie_token_precedes_bearer_token(self):
        cookie_name = auth_utils.AUTH_SESSION_COOKIE_NAME
        req = request(cookie=f"{cookie_name}=cookie-token", authorization="Bearer bearer-token")
        self.assertEqual("cookie-token", auth_utils.extract_session_token(req))
        self.assertEqual("bearer-token", auth_utils.extract_session_token(request(authorization="Bearer bearer-token")))

    def test_cookie_policy_modes(self):
        with patch.object(auth_utils, "AUTH_COOKIE_SECURE_MODE", "true"):
            self.assertTrue(auth_utils.resolve_cookie_secure(request(scheme="http")))
        with patch.object(auth_utils, "AUTH_COOKIE_SECURE_MODE", "false"):
            self.assertFalse(auth_utils.resolve_cookie_secure(request()))
        with patch.object(auth_utils, "AUTH_COOKIE_SAMESITE_MODE", "strict"):
            self.assertEqual("strict", auth_utils.resolve_cookie_samesite(request()))

    def test_forwarded_headers_require_loopback_proxy_peer(self):
        with patch.object(auth_utils, "TRUST_PROXY_HEADERS", True), patch.object(
            auth_utils,
            "TRUSTED_PROXY_IPS",
            {auth_utils.ipaddress.ip_address("127.0.0.1")},
        ):
            untrusted = request(
                scheme="http",
                client=("198.51.100.10", 443),
                forwarded_proto="https",
                forwarded_for="203.0.113.20",
            )
            trusted = request(
                scheme="http",
                client=("127.0.0.1", 443),
                forwarded_proto="https",
                forwarded_for="203.0.113.20",
            )
            self.assertEqual("http", auth_utils.get_request_scheme(untrusted))
            self.assertEqual("https", auth_utils.get_request_scheme(trusted))
            self.assertEqual("198.51.100.10", auth_utils.get_client_ip_from_request(untrusted))
            self.assertEqual("203.0.113.20", auth_utils.get_client_ip_from_request(trusted))


if __name__ == "__main__":
    unittest.main()
