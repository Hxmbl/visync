"""Unit tests for download module (no network or Ventoy hardware required)."""

import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.download import (
    download_iso,
    fetch_html,
    load_config,
    process_scraping_strategy,
)


class TestFetchHtml(unittest.TestCase):
    @patch("src.download.urllib.request.urlopen")
    @patch("src.download.urllib.request.Request")
    def test_fetch_html_success(self, mock_request: MagicMock, mock_urlopen: MagicMock):
        mock_response = MagicMock()
        mock_response.read.return_value = b"<html>content</html>"
        mock_response.__enter__.return_value = mock_response
        mock_urlopen.return_value = mock_response

        result = fetch_html("https://example.com")
        self.assertEqual(result, "<html>content</html>")

    @patch("src.download.urllib.request.urlopen")
    @patch("src.download.urllib.request.Request")
    def test_fetch_html_failure(self, mock_request: MagicMock, mock_urlopen: MagicMock):
        mock_urlopen.side_effect = Exception("timeout")
        result = fetch_html("https://example.com")
        self.assertEqual(result, "")


class TestLoadConfig(unittest.TestCase):
    def test_load_config_returns_dict(self):
        config = load_config()
        self.assertIsInstance(config, dict)
        self.assertIn("distros", config)
        self.assertIn("iso", config)


class TestProcessScrapingStrategy(unittest.TestCase):
    @patch("src.download.fetch_html")
    def test_direct_match_found(self, mock_fetch_html: MagicMock):
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

    @patch("src.download.fetch_html")
    def test_direct_match_not_found(self, mock_fetch_html: MagicMock):
        mock_fetch_html.return_value = "<html>no iso here</html>"
        settings = {
            "strategy": "direct_match",
            "base_url": "https://example.com/",
            "iso_regex": 'href="(archlinux-[^"]+\\.iso)"',
        }
        name, url = process_scraping_strategy("Arch Linux", settings)
        self.assertEqual(name, "")
        self.assertEqual(url, "")

    @patch("src.download.fetch_html")
    def test_fedora_nested_found(self, mock_fetch_html: MagicMock):
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

    @patch("src.download.fetch_html")
    def test_ubuntu_nested_found(self, mock_fetch_html: MagicMock):
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

    @patch("src.download.fetch_html")
    def test_fedora_empty_root(self, mock_fetch_html: MagicMock):
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

    @patch("src.download.fetch_html")
    def test_unknown_strategy(self, mock_fetch_html: MagicMock):
        settings = {"strategy": "custom_strategy", "base_url": "https://example.com/"}
        name, url = process_scraping_strategy("Custom", settings)
        self.assertEqual(name, "")
        self.assertEqual(url, "")


class TestDownloadIso(unittest.TestCase):
    @patch("src.download.urllib.request.urlretrieve")
    def test_download_success(self, mock_urlretrieve: MagicMock):
        dest = Path("/tmp/test.iso")
        download_iso("https://example.com/test.iso", dest)
        mock_urlretrieve.assert_called_once_with(
            "https://example.com/test.iso", str(dest), reporthook=mock_urlretrieve.call_args[1]["reporthook"]
        )

    @patch("src.download.urllib.request.urlretrieve")
    def test_download_failure(self, mock_urlretrieve: MagicMock):
        mock_urlretrieve.side_effect = Exception("connection lost")
        dest = Path("/tmp/test.iso")
        download_iso("https://example.com/test.iso", dest)


if __name__ == "__main__":
    unittest.main()
