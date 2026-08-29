import ssl
import unittest
from unittest.mock import patch
from urllib.error import URLError
from urllib.request import Request

from crawler_engine.msc.client import MSCClient
from crawler_engine.msc.config import MSCConfig
from crawler_engine.msc.tls import (
    create_msc_ssl_context,
    diagnose_msc_tls,
    is_dh_key_too_small,
)


class MSCTLSContextTest(unittest.TestCase):
    def test_context_stays_verified_and_tls12_or_newer(self):
        context = create_msc_ssl_context()

        self.assertEqual(ssl.CERT_REQUIRED, context.verify_mode)
        self.assertTrue(context.check_hostname)
        self.assertGreaterEqual(context.minimum_version, ssl.TLSVersion.TLSv1_2)
        self.assertEqual(ssl.create_default_context().security_level, context.security_level)

    def test_effective_cipher_policy_excludes_finite_field_dhe(self):
        context = create_msc_ssl_context()
        tls12_names = [
            cipher["name"] for cipher in context.get_ciphers() if cipher["protocol"] != "TLSv1.3"
        ]

        self.assertTrue(tls12_names)
        self.assertTrue(all(not name.startswith("DHE-") for name in tls12_names))
        self.assertTrue(all("ANON" not in name and "NULL" not in name for name in tls12_names))

    def test_context_does_not_mutate_default_ssl_behavior(self):
        before = ssl.create_default_context()
        before_names = [cipher["name"] for cipher in before.get_ciphers()]

        create_msc_ssl_context()

        after = ssl.create_default_context()
        self.assertEqual(before_names, [cipher["name"] for cipher in after.get_ciphers()])
        self.assertEqual(before.minimum_version, after.minimum_version)
        self.assertEqual(before.verify_mode, after.verify_mode)
        self.assertTrue(after.check_hostname)

    def test_default_client_opener_receives_only_msc_context(self):
        client = MSCClient(MSCConfig(request_delay_seconds=0))
        with patch("crawler_engine.msc.client.urlopen") as mocked_urlopen:
            client._opener(Request("https://example.invalid/search_prc"), timeout=1)

        request, kwargs = mocked_urlopen.call_args
        self.assertEqual(1, kwargs["timeout"])
        context = kwargs["context"]
        self.assertIsInstance(context, ssl.SSLContext)
        self.assertEqual(ssl.CERT_REQUIRED, context.verify_mode)
        self.assertTrue(context.check_hostname)


class MSCTLSClassificationTest(unittest.TestCase):
    def test_classifies_only_dh_key_too_small(self):
        weak_dh = ssl.SSLError("[SSL: DH_KEY_TOO_SMALL] dh key too small (_ssl.c:1000)")
        self.assertTrue(is_dh_key_too_small(weak_dh))
        self.assertTrue(is_dh_key_too_small(URLError(weak_dh)))
        self.assertFalse(is_dh_key_too_small(ssl.SSLError("[SSL: CERTIFICATE_VERIFY_FAILED] verify failed")))
        self.assertFalse(is_dh_key_too_small(URLError(TimeoutError("timed out"))))

    def test_diagnostic_reports_standard_failure_and_ecdhe_success(self):
        weak_dh = ssl.SSLError("[SSL: DH_KEY_TOO_SMALL] dh key too small")
        with patch(
            "crawler_engine.msc.tls._handshake",
            side_effect=[weak_dh, ("TLSv1.2", "ECDHE-RSA-AES128-GCM-SHA256")],
        ):
            result = diagnose_msc_tls("https://example.invalid/search_prc")

        self.assertEqual("FAIL", result["standard_handshake"]["status"])
        self.assertTrue(result["standard_handshake"]["dh_key_too_small"])
        self.assertEqual("PASS", result["msc_ecdhe_handshake"]["status"])
        self.assertEqual("TLSv1.2", result["msc_ecdhe_handshake"]["protocol"])
        self.assertTrue(result["standard_tls12_finite_field_dhe_ciphers"])
        self.assertFalse(any(name.startswith("DHE-") for name in result["msc_tls12_ciphers"]))


if __name__ == "__main__":
    unittest.main()
