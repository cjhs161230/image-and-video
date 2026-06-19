import tempfile
import unittest
from pathlib import Path

from scripts.security.scan_secrets import scan_paths


class SecretScannerTests(unittest.TestCase):
    def test_scan_paths_detects_api_keys_and_ignores_placeholders(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            safe = root / ".env.example"
            unsafe = root / "config.json"
            safe.write_text(
                "MATSCA_DIRECT_API_KEY=sk-YOUR_MATSCA_DIRECT_KEY\n"
                "MATSCA_APP_SECRET=as-YOUR_APP_SECRET\n",
                encoding="utf-8",
            )
            secret = "sk-live-" + "sensitive-secret-value"
            unsafe.write_text(f'{{"api_key":"{secret}"}}', encoding="utf-8")

            findings = scan_paths([root])

            self.assertEqual(len(findings), 1)
            self.assertEqual(findings[0].path, unsafe)
            self.assertEqual(findings[0].line_number, 1)
            self.assertEqual(findings[0].kind, "api_key")
            self.assertNotIn("sensitive-secret", findings[0].redacted)

    def test_scan_paths_skips_runtime_dependency_and_vcs_directories(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            secret = "sk-live-" + "runtime-sensitive-value"
            for directory_name in ("data", ".uv-cache", ".git", "node_modules"):
                ignored = root / directory_name / "settings.json"
                ignored.parent.mkdir()
                ignored.write_text(f'{{"api_key":"{secret}"}}', encoding="utf-8")

            self.assertEqual(scan_paths([root]), [])


if __name__ == "__main__":
    unittest.main()
