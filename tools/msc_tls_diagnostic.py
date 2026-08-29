"""Developer-only MSC TLS interoperability diagnostic."""

from __future__ import annotations

import json

from crawler_engine.msc.tls import diagnose_msc_tls


if __name__ == "__main__":
    result = diagnose_msc_tls()
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    raise SystemExit(0 if result["msc_ecdhe_handshake"]["status"] == "PASS" else 1)
