import re
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SECRET_PATTERNS = {
    "OpenAI-style key": re.compile(rb"\bsk-[A-Za-z0-9_-]{20,}\b"),
    "AWS access key": re.compile(rb"\bAKIA[A-Z0-9]{16}\b"),
    "credentialed Postgres URL": re.compile(rb"postgres(?:ql)?://[^\s/:]+:[^\s/@]+@[^\s]+", re.I),
}


class TrackedSecretScanTest(unittest.TestCase):
    def test_tracked_files_do_not_contain_secret_patterns(self):
        files = subprocess.check_output(["git", "ls-files", "-z"], cwd=ROOT).split(b"\0")
        findings = []
        for raw_path in filter(None, files):
            path = ROOT / raw_path.decode()
            relative = path.relative_to(ROOT)
            if relative.parts[0] == "docs" or path.name.endswith(".example"):
                continue
            data = path.read_bytes()
            if b"\0" in data:
                continue
            for name, pattern in SECRET_PATTERNS.items():
                if pattern.search(data):
                    findings.append(f"{path.relative_to(ROOT)}: {name}")
        self.assertEqual([], findings)


if __name__ == "__main__":
    unittest.main()
