import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from starlette.requests import Request


sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "apps" / "api"))
import auth_utils  # noqa: E402


def request(*, scheme="https", host="example.test", cookie="", authorization=""):
    headers = []
    if cookie:
        headers.append((b"cookie", cookie.encode()))
    if authorization:
        headers.append((b"authorization", authorization.encode()))
    return Request({"type": "http", "scheme": scheme, "server": (host, 443), "headers": headers})


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


if __name__ == "__main__":
    unittest.main()
