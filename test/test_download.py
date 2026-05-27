"""Unit tests for download module (no network or Ventoy hardware required)."""

import sys
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.download import (
    download_iso,
    fetch_html,
    load_config,
    process_scraping_strategy,
)


def _section(title: str) -> None:
    print(f"\n  {'=' * 60}")
    print(f"  {title}")
    print(f"  {'=' * 60}")


def _ok(msg: str) -> None:
    print(f"  [✓] {msg}")


def _info(msg: str) -> None:
    print(f"  [*] {msg}")


class TestFetchHtml(unittest.TestCase):
    @patch("src.download.urllib.request.urlopen")
    @patch("src.download.urllib.request.Request")
    def test_fetch_html_success(self, mock_request: MagicMock, mock_urlopen: MagicMock):
        _section("fetch_html: Successful Request")
        mock_response = MagicMock()
        mock_response.read.return_value = b"<html>content</html>"
        mock_response.__enter__.return_value = mock_response
        mock_urlopen.return_value = mock_response

        result = fetch_html("https://example.com")
        self.assertEqual(result, "<html>content</html>")
        _ok("HTML content returned as string")

    @patch("src.download.urllib.request.urlopen")
    @patch("src.download.urllib.request.Request")
    def test_fetch_html_failure(self, mock_request: MagicMock, mock_urlopen: MagicMock):
        _section("fetch_html: Network Failure")
        mock_urlopen.side_effect = Exception("timeout")
        result = fetch_html("https://example.com")
        self.assertEqual(result, "")
        _ok("Empty string returned on timeout")

    @patch("src.download.urllib.request.urlopen")
    @patch("src.download.urllib.request.Request")
    def test_bot_challenge_detected(self, mock_request: MagicMock, mock_urlopen: MagicMock):
        _section("fetch_html: Bot Challenge Detection")
        mock_response = MagicMock()
        mock_response.read.return_value = b"<html>Anubis challenge page</html>"
        mock_response.__enter__.return_value = mock_response
        mock_urlopen.return_value = mock_response
        result = fetch_html("https://example.com")
        self.assertEqual(result, "")
        _ok("Anubis challenge detected, empty string returned")

    @patch("builtins.input", return_value="n")
    @patch("src.download.urllib.request.urlopen")
    @patch("src.download.urllib.request.Request")
    def test_ssl_error_user_declines(
        self, mock_request: MagicMock, mock_urlopen: MagicMock, mock_input: MagicMock
    ):
        _section("fetch_html: SSL Error — Declined")
        mock_urlopen.side_effect = urllib.error.URLError(
            "SSL: CERTIFICATE_VERIFY_FAILED"
        )
        result = fetch_html("https://example.com")
        self.assertEqual(result, "")
        _ok("SSL declined, empty string returned")

    @patch("builtins.input", return_value="y")
    @patch("src.download.urllib.request.urlopen")
    @patch("src.download.urllib.request.Request")
    def test_ssl_error_user_accepts(
        self, mock_request: MagicMock, mock_urlopen: MagicMock, mock_input: MagicMock
    ):
        _section("fetch_html: SSL Error — Accepted")
        mock_response = MagicMock()
        mock_response.read.return_value = b"<html>content</html>"
        mock_response.__enter__.return_value = mock_response

        ssl_error = urllib.error.URLError("SSL: CERTIFICATE_VERIFY_FAILED")
        mock_urlopen.side_effect = [ssl_error, mock_response]
        result = fetch_html("https://example.com")
        self.assertEqual(result, "<html>content</html>")
        _ok("SSL bypassed, content returned on retry")


class TestLoadConfig(unittest.TestCase):
    def test_load_config_returns_dict(self):
        _section("load_config: Structure Check")
        config = load_config()
        self.assertIsInstance(config, dict)
        self.assertIn("distros", config)
        self.assertIn("iso", config)
        _ok("Config loaded as dict with [distros] and [iso] sections")


class TestProcessScrapingStrategy(unittest.TestCase):
    @patch("src.download.fetch_html")
    def test_direct_match_found(self, mock_fetch_html: MagicMock):
        _section("Strategy: direct_match — Found")
        mock_fetch_html.return_value = (
            '<a href="archlinux-2025.01.01-x86_64.iso">arch</a>'
        )
        settings = {
            "strategy": "direct_match",
            "base_url": "https://example.com/iso/",
            "iso_regex": 'href="(archlinux-[^"]+\\.iso)"',
        }
        name, url = process_scraping_strategy("Arch Linux", settings)
        self.assertEqual(name, "archlinux-2025.01.01-x86_64.iso")
        self.assertEqual(url, "https://example.com/iso/archlinux-2025.01.01-x86_64.iso")
        _ok(f"Resolved to {name}")

    @patch("src.download.fetch_html")
    def test_direct_match_not_found(self, mock_fetch_html: MagicMock):
        _section("Strategy: direct_match — Not Found")
        mock_fetch_html.return_value = "<html>no iso here</html>"
        settings = {
            "strategy": "direct_match",
            "base_url": "https://example.com/",
            "iso_regex": 'href="(archlinux-[^"]+\\.iso)"',
        }
        name, url = process_scraping_strategy("Arch Linux", settings)
        self.assertEqual(name, "")
        self.assertEqual(url, "")
        _ok("Empty strings returned when no match")

    @patch("src.download.fetch_html")
    def test_fedora_nested_found(self, mock_fetch_html: MagicMock):
        _section("Strategy: fedora_nested — Found")
        mock_fetch_html.side_effect = [
            '<a href="41/">41/</a><a href="42/">42/</a>',
            '<a href="Fedora-Workstation-Live-x86_64-42-1.1.iso">iso</a>',
        ]
        settings = {
            "strategy": "fedora_nested",
            "base_url": "https://example.com/fedora/",
            "version_regex": 'href="([0-9\\.]+)/"',
            "iso_regex": 'href="(Fedora-Workstation-Live-x86_64-[^\"]+\\.iso)"',
        }
        name, url = process_scraping_strategy("Fedora", settings)
        self.assertEqual(name, "Fedora-Workstation-Live-x86_64-42-1.1.iso")
        self.assertIn("42/Workstation/x86_64/iso/", url)
        _ok(f"Resolved to Fedora 42: {name}")

    @patch("src.download.fetch_html")
    def test_ubuntu_nested_found(self, mock_fetch_html: MagicMock):
        _section("Strategy: ubuntu_nested — Found")
        mock_fetch_html.side_effect = [
            '<a href="24.04/">24.04/</a><a href="24.10/">24.10/</a>',
            '<a href="ubuntu-24.10-live-server-amd64.iso">iso</a>',
        ]
        settings = {
            "strategy": "ubuntu_nested",
            "base_url": "https://example.com/ubuntu/",
            "version_regex": 'href="([0-9\\.]+)/"',
            "iso_regex": 'href="(ubuntu-[^\"]+\\.iso)"',
        }
        name, url = process_scraping_strategy("Ubuntu Server", settings)
        self.assertEqual(name, "ubuntu-24.10-live-server-amd64.iso")
        self.assertIn("24.10/", url)
        _ok(f"Resolved to Ubuntu 24.10: {name}")

    @patch("src.download.fetch_html")
    def test_fedora_empty_root(self, mock_fetch_html: MagicMock):
        _section("Strategy: fedora_nested — Empty Root")
        mock_fetch_html.return_value = ""
        settings = {
            "strategy": "fedora_nested",
            "base_url": "https://example.com/",
            "version_regex": 'href="([0-9\\.]+)/"',
            "iso_regex": 'href="(Fedora-[^\"]+\\.iso)"',
        }
        name, url = process_scraping_strategy("Fedora", settings)
        self.assertEqual(name, "")
        self.assertEqual(url, "")
        _ok("Empty strings returned on empty root HTML")

    @patch("src.download.fetch_html")
    def test_unknown_strategy(self, mock_fetch_html: MagicMock):
        _section("Strategy: Unknown / Unrecognized")
        settings = {"strategy": "custom_strategy", "base_url": "https://example.com/"}
        name, url = process_scraping_strategy("Custom", settings)
        self.assertEqual(name, "")
        self.assertEqual(url, "")
        _ok("Empty strings returned for unknown strategy")


class _FakeResponse:
    """A minimal context-manager response for use with mock urlopen."""
    def __init__(self, headers=None, read_data=None):
        self.headers = headers or {}
        self._read_data = read_data or []
        self._read_idx = 0

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def read(self, size=-1):
        if self._read_idx < len(self._read_data):
            data = self._read_data[self._read_idx]
            self._read_idx += 1
            return data
        return b""


class TestDownloadIso(unittest.TestCase):
    def _mock_head_response(self, content_length: str = "1000"):
        return _FakeResponse(headers={"Content-Length": content_length})

    def _mock_get_response(self, data: bytes, content_length: str = "1000"):
        return _FakeResponse(
            headers={"Content-Length": content_length},
            read_data=[data, b""],
        )

    @patch("src.download.urllib.request.urlopen")
    @patch("src.download.urllib.request.Request")
    def test_download_success(
        self, mock_request: MagicMock, mock_urlopen: MagicMock
    ):
        _section("download_iso: Successful Download")
        head_resp = self._mock_head_response()
        get_resp = self._mock_get_response(b"x" * 500)
        mock_urlopen.side_effect = [head_resp, get_resp]

        with tempfile.TemporaryDirectory() as tmpdir:
            dest = Path(tmpdir) / "test.iso"
            download_iso("https://example.com/test.iso", dest)
            self.assertTrue(dest.exists())
            self.assertEqual(dest.read_bytes(), b"x" * 500)
            _ok(f"Wrote {len(dest.read_bytes())} bytes to {dest.name}")

    @patch("src.download.urllib.request.urlopen")
    @patch("src.download.urllib.request.Request")
    def test_download_failure(
        self, mock_request: MagicMock, mock_urlopen: MagicMock
    ):
        _section("download_iso: Connection Failure")
        head_resp = self._mock_head_response()
        mock_urlopen.side_effect = [head_resp, Exception("connection lost")]

        dest = Path("/tmp/test.iso")
        download_iso("https://example.com/test.iso", dest)
        _ok("Exception caught gracefully, script continues")


if __name__ == "__main__":
    print()
    print(f"  {'#' * 62}")
    print(f"  #   DOWNLOAD MODULE — MOCKED NETWORK TESTS")
    print(f"  {'#' * 62}")
    print()
    _info("Testing fetch_html, load_config, process_scraping_strategy, download_iso")
    print()
    unittest.main(verbosity=2)
