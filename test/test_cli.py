"""Strict CLI tests — every command, every flag, every edge case."""

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from typer.testing import CliRunner

from src.main import app

runner = CliRunner()

MOCK_CONFIG = {
    "distros": {
        "ArchLinux": {
            "clean_name": "Arch Linux",
            "strategy": "direct_match",
            "base_url": "https://example.com/arch/",
            "keyword": "archlinux",
            "checksum_format": "sha256sums",
        },
        "UbuntuServer": {
            "clean_name": "Ubuntu Server",
            "strategy": "ubuntu_nested",
            "base_url": "https://example.com/ubuntu/",
            "keyword": "live-server",
            "checksum_format": "sha256sums",
        },
    }
}


def _mock_find_installed(iso_dir: Path) -> list[Path]:
    return sorted(iso_dir.glob("*.iso"))


def _mock_get_vid(iso_path: Path) -> str:
    return ""


def _mock_identify_distro(vid: str, filename: str) -> str:
    fn = filename.lower()
    if "archlinux" in fn or "arch" in fn:
        return "Arch Linux"
    if "ubuntu" in fn and "server" in fn:
        return "Ubuntu Server"
    if "ubuntu" in fn:
        return "Ubuntu"
    return "Unknown OS"


# ── install ──────────────────────────────────────────────────────────────────


class TestInstall(unittest.TestCase):
    @patch("src.main.find_ventoy_drives", return_value=[])
    @patch("src.main.load_config")
    def test_install_requires_name_or_file(self, *_: MagicMock) -> None:
        result = runner.invoke(app, ["install"])
        self.assertNotEqual(result.exit_code, 0)

    @patch("src.main.identify_distro", side_effect=_mock_identify_distro)
    @patch("src.main.get_iso_volume_id", side_effect=_mock_get_vid)
    @patch("src.main.find_installed_isos", side_effect=_mock_find_installed)
    @patch("src.main.load_config")
    def test_install_unknown_distro_fails(self, mock_cfg: MagicMock, *_: MagicMock) -> None:
        mock_cfg.return_value = MOCK_CONFIG
        with tempfile.TemporaryDirectory() as tmpdir:
            result = runner.invoke(app, ["install", "bogus-distro", "--drive", tmpdir])
            self.assertNotEqual(result.exit_code, 0)
            self.assertIn("Unknown distro", result.stdout)

    @patch("src.main.find_installed_isos", side_effect=_mock_find_installed)
    def test_install_dry_run_does_not_download(self, _mock: MagicMock) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch("src.main.load_config", return_value=MOCK_CONFIG):
                result = runner.invoke(
                    app, ["install", "archlinux", "--drive", tmpdir, "--dry-run"]
                )
                self.assertEqual(result.exit_code, 0)
                self.assertIn("Would download", result.stdout)
                self.assertEqual(list(Path(tmpdir).glob("*.iso")), [])

    @patch("src.pm.mark_installed")
    @patch("src.main.identify_distro", side_effect=_mock_identify_distro)
    @patch("src.main.get_iso_volume_id", side_effect=_mock_get_vid)
    @patch("src.main.find_installed_isos", side_effect=_mock_find_installed)
    @patch("src.main.load_config")
    def test_install_already_on_drive(
        self, mock_cfg: MagicMock, *_: MagicMock
    ) -> None:
        mock_cfg.return_value = MOCK_CONFIG
        with tempfile.TemporaryDirectory() as tmpdir:
            iso = Path(tmpdir) / "archlinux-2026.iso"
            iso.write_bytes(b"\x00" * 1024)
            result = runner.invoke(app, ["install", "archlinux", "--drive", tmpdir])
            self.assertEqual(result.exit_code, 0)
            self.assertIn("already on the drive", result.stdout)

    def test_install_file_not_found(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            result = runner.invoke(
                app, ["install", "-f", "/nonexistent/packages.txt", "--drive", tmpdir]
            )
            self.assertNotEqual(result.exit_code, 0)
            self.assertIn("File not found", result.stdout)

    @patch("src.main.find_installed_isos", side_effect=_mock_find_installed)
    def test_install_file_with_comments_and_blanks(self, _mock: MagicMock) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            pkg_file = Path(tmpdir) / "packages.txt"
            pkg_file.write_text("# comment\n\narchlinux\n\n# another comment\n")
            with patch("src.main.load_config", return_value=MOCK_CONFIG):
                result = runner.invoke(
                    app, ["install", "-f", str(pkg_file), "--drive", tmpdir, "--dry-run"]
                )
                self.assertEqual(result.exit_code, 0)
                self.assertIn("Would download 1 distro(s)", result.stdout)

    @patch("src.main.find_installed_isos", side_effect=_mock_find_installed)
    def test_install_file_multiple_distros(self, _mock: MagicMock) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            pkg_file = Path(tmpdir) / "packages.txt"
            pkg_file.write_text("archlinux\nubuntuserver\n")
            with patch("src.main.load_config", return_value=MOCK_CONFIG):
                result = runner.invoke(
                    app, ["install", "-f", str(pkg_file), "--drive", tmpdir, "--dry-run"]
                )
                self.assertEqual(result.exit_code, 0)
                self.assertIn("Would download 2 distro(s)", result.stdout)

    @patch("src.main.find_installed_isos", side_effect=_mock_find_installed)
    def test_install_file_no_valid_distros(self, _mock: MagicMock) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            pkg_file = Path(tmpdir) / "packages.txt"
            pkg_file.write_text("bogus1\nbogus2\n")
            with patch("src.main.load_config", return_value=MOCK_CONFIG):
                result = runner.invoke(
                    app, ["install", "-f", str(pkg_file), "--drive", tmpdir]
                )
                self.assertNotEqual(result.exit_code, 0)
                self.assertIn("No valid distros", result.stdout)

    def test_install_has_all_flags(self) -> None:
        result = runner.invoke(app, ["install", "--help"])
        for flag in ["--config", "--drive", "--dry-run", "--file"]:
            self.assertIn(flag, result.stdout, f"install missing {flag}")


# ── remove ───────────────────────────────────────────────────────────────────


class TestRemove(unittest.TestCase):
    @patch("src.main.identify_distro", side_effect=_mock_identify_distro)
    @patch("src.main.get_iso_volume_id", side_effect=_mock_get_vid)
    @patch("src.main.find_installed_isos", side_effect=_mock_find_installed)
    @patch("src.main.load_config")
    def test_remove_unknown_distro_fails(self, mock_cfg: MagicMock, *_: MagicMock) -> None:
        mock_cfg.return_value = MOCK_CONFIG
        with tempfile.TemporaryDirectory() as tmpdir:
            result = runner.invoke(app, ["remove", "bogus-distro", "--drive", tmpdir])
            self.assertNotEqual(result.exit_code, 0)
            self.assertIn("Unknown distro", result.stdout)

    @patch("src.main.identify_distro", side_effect=_mock_identify_distro)
    @patch("src.main.get_iso_volume_id", side_effect=_mock_get_vid)
    @patch("src.main.find_installed_isos", side_effect=_mock_find_installed)
    @patch("src.main.load_config")
    def test_remove_no_files_warns(self, mock_cfg: MagicMock, *_: MagicMock) -> None:
        mock_cfg.return_value = MOCK_CONFIG
        with tempfile.TemporaryDirectory() as tmpdir:
            result = runner.invoke(app, ["remove", "archlinux", "--drive", tmpdir])
            self.assertEqual(result.exit_code, 0)
            self.assertIn("No files found", result.stdout)

    @patch("src.main.identify_distro", side_effect=_mock_identify_distro)
    @patch("src.main.get_iso_volume_id", side_effect=_mock_get_vid)
    @patch("src.main.find_installed_isos", side_effect=_mock_find_installed)
    @patch("src.main.load_config")
    def test_remove_dry_run_does_not_delete(self, mock_cfg: MagicMock, *_: MagicMock) -> None:
        mock_cfg.return_value = MOCK_CONFIG
        with tempfile.TemporaryDirectory() as tmpdir:
            iso = Path(tmpdir) / "archlinux-2026.iso"
            iso.write_bytes(b"\x00" * 1024)
            result = runner.invoke(
                app, ["remove", "archlinux", "--drive", tmpdir, "--dry-run"]
            )
            self.assertEqual(result.exit_code, 0)
            self.assertIn("Would remove", result.stdout)
            self.assertTrue(iso.exists(), "File should still exist after dry-run")

    @patch("src.finder.remove_iso_metadata")
    @patch("src.pm.mark_removed")
    @patch("src.main.identify_distro", side_effect=_mock_identify_distro)
    @patch("src.main.get_iso_volume_id", side_effect=_mock_get_vid)
    @patch("src.main.find_installed_isos", side_effect=_mock_find_installed)
    @patch("src.main.load_config")
    def test_remove_deletes_file(self, mock_cfg: MagicMock, *_: MagicMock) -> None:
        mock_cfg.return_value = MOCK_CONFIG
        with tempfile.TemporaryDirectory() as tmpdir:
            iso = Path(tmpdir) / "archlinux-2026.iso"
            iso.write_bytes(b"\x00" * 1024)
            result = runner.invoke(app, ["remove", "archlinux", "--drive", tmpdir])
            self.assertEqual(result.exit_code, 0)
            self.assertFalse(iso.exists(), "File should be deleted")
            self.assertIn("removed", result.stdout)

    def test_remove_has_flags(self) -> None:
        result = runner.invoke(app, ["remove", "--help"])
        for flag in ["--config", "--drive", "--dry-run"]:
            self.assertIn(flag, result.stdout, f"remove missing {flag}")


# ── update ───────────────────────────────────────────────────────────────────


class TestUpdate(unittest.TestCase):
    @patch("src.main.find_ventoy_drives", return_value=[Path("/tmp")])
    @patch("src.main.load_config")
    def test_update_no_installed(self, *_: MagicMock) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch("src.main.find_ventoy_drives", return_value=[Path(tmpdir)]):
                result = runner.invoke(app, ["update"])
                self.assertEqual(result.exit_code, 0)
                self.assertIn("No distros installed", result.stdout)

    def test_update_has_flags(self) -> None:
        result = runner.invoke(app, ["update", "--help"])
        for flag in ["--config", "--drive", "--force", "--clean", "--dry-run"]:
            self.assertIn(flag, result.stdout, f"update missing {flag}")

    @patch("src.main.load_config")
    def test_update_unknown_distro_fails(self, mock_cfg: MagicMock) -> None:
        mock_cfg.return_value = MOCK_CONFIG
        with tempfile.TemporaryDirectory() as tmpdir:
            result = runner.invoke(app, ["update", "bogus-distro", "--drive", tmpdir])
            self.assertNotEqual(result.exit_code, 0)
            self.assertIn("Unknown distro", result.stdout)


# ── search ───────────────────────────────────────────────────────────────────


class TestSearch(unittest.TestCase):
    @patch("src.pm.get_installed_ids", return_value=[])
    @patch("src.main.find_ventoy_drives", return_value=[Path("/tmp")])
    @patch("src.main.load_config", return_value=MOCK_CONFIG)
    def test_search_lists_distros(self, *_: MagicMock) -> None:
        result = runner.invoke(app, ["search"])
        self.assertEqual(result.exit_code, 0)
        self.assertIn("Arch Linux", result.stdout)
        self.assertIn("Ubuntu Server", result.stdout)

    @patch("src.pm.get_installed_ids", return_value=[])
    @patch("src.main.find_ventoy_drives", return_value=[Path("/tmp")])
    @patch("src.main.load_config", return_value=MOCK_CONFIG)
    def test_search_by_query(self, *_: MagicMock) -> None:
        result = runner.invoke(app, ["search", "archlinux"])
        self.assertEqual(result.exit_code, 0)
        self.assertIn("Arch Linux", result.stdout)

    @patch("src.pm.get_installed_ids", return_value=[])
    @patch("src.main.find_ventoy_drives", return_value=[Path("/tmp")])
    @patch("src.main.load_config", return_value=MOCK_CONFIG)
    def test_search_no_match(self, *_: MagicMock) -> None:
        result = runner.invoke(app, ["search", "bogus"])
        self.assertIn("No match", result.stdout)

    def test_search_has_config_and_drive(self) -> None:
        result = runner.invoke(app, ["search", "--help"])
        self.assertIn("--config", result.stdout)
        self.assertIn("--drive", result.stdout)

    @patch("src.main.load_config", return_value={"distros": {}})
    def test_search_no_distros_configured(self, _mock: MagicMock) -> None:
        result = runner.invoke(app, ["search"])
        self.assertEqual(result.exit_code, 0)
        self.assertIn("No distros configured", result.stdout)

    def test_search_does_not_have_dry_run(self) -> None:
        result = runner.invoke(app, ["search", "--help"])
        self.assertNotIn("--dry-run", result.stdout)


# ── info ─────────────────────────────────────────────────────────────────────


class TestInfo(unittest.TestCase):
    @patch("src.pm.get_installed_ids", return_value=[])
    @patch("src.main.find_ventoy_drives", return_value=[Path("/tmp")])
    @patch("src.main.load_config", return_value=MOCK_CONFIG)
    def test_info_shows_details(self, *_: MagicMock) -> None:
        result = runner.invoke(app, ["info", "archlinux"])
        self.assertEqual(result.exit_code, 0)
        self.assertIn("Arch Linux", result.stdout)
        self.assertIn("strategy:", result.stdout)

    @patch("src.main.find_ventoy_drives", return_value=[Path("/tmp")])
    @patch("src.main.load_config", return_value=MOCK_CONFIG)
    def test_info_unknown_distro_fails(self, *_: MagicMock) -> None:
        result = runner.invoke(app, ["info", "bogus-distro"])
        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("Unknown distro", result.stdout)

    def test_info_has_flags(self) -> None:
        result = runner.invoke(app, ["info", "--help"])
        self.assertIn("--config", result.stdout)
        self.assertIn("--drive", result.stdout)

    def test_info_does_not_have_dry_run(self) -> None:
        result = runner.invoke(app, ["info", "--help"])
        self.assertNotIn("--dry-run", result.stdout)


# ── autodetect ───────────────────────────────────────────────────────────────


class TestAutodetect(unittest.TestCase):
    @patch("src.pm.get_installed_ids", return_value=[])
    @patch("src.main.load_config")
    def test_autodetect_no_files(self, mock_cfg: MagicMock, *_: MagicMock) -> None:
        mock_cfg.return_value = MOCK_CONFIG
        with tempfile.TemporaryDirectory() as tmpdir:
            result = runner.invoke(app, ["autodetect", "--drive", tmpdir])
            self.assertEqual(result.exit_code, 0)
            self.assertIn("No new distros detected", result.stdout)

    @patch("src.pm.get_installed_ids", return_value=[])
    @patch("src.pm.mark_installed")
    @patch("src.main.load_config")
    def test_autodetect_dry_run(self, mock_cfg: MagicMock, *_: MagicMock) -> None:
        mock_cfg.return_value = MOCK_CONFIG
        with tempfile.TemporaryDirectory() as tmpdir:
            iso = Path(tmpdir) / "archlinux-2026.iso"
            iso.write_bytes(b"\x00" * 1024)
            with patch("src.main.identify_distro", side_effect=_mock_identify_distro):
                result = runner.invoke(
                    app, ["autodetect", "--drive", tmpdir, "--dry-run"]
                )
                self.assertEqual(result.exit_code, 0)
                self.assertIn("Would detect", result.stdout)

    @patch("src.pm.get_installed_ids", return_value=[])
    @patch("src.pm.mark_installed")
    @patch("src.main.extract_version_from_filename", return_value="2026")
    @patch("src.main.identify_distro", side_effect=_mock_identify_distro)
    @patch("src.main.load_config")
    def test_autodetect_registers_iso(
        self, mock_cfg: MagicMock, *_: MagicMock
    ) -> None:
        mock_cfg.return_value = MOCK_CONFIG
        with tempfile.TemporaryDirectory() as tmpdir:
            iso = Path(tmpdir) / "archlinux-2026.iso"
            iso.write_bytes(b"\x00" * 1024)
            result = runner.invoke(app, ["autodetect", "--drive", tmpdir])
            self.assertEqual(result.exit_code, 0)
            self.assertIn("Detected", result.stdout)

    @patch("src.pm.get_installed_ids", return_value=["ArchLinux"])
    @patch("src.pm.mark_installed")
    @patch("src.main.load_config")
    def test_autodetect_skips_already_registered(self, mock_cfg: MagicMock, *_: MagicMock) -> None:
        """autodetect does not re-register already tracked distros."""
        mock_cfg.return_value = MOCK_CONFIG
        with tempfile.TemporaryDirectory() as tmpdir:
            iso = Path(tmpdir) / "archlinux-2026.iso"
            iso.write_bytes(b"\x00" * 1024)
            with patch("src.main.identify_distro", side_effect=_mock_identify_distro):
                result = runner.invoke(app, ["autodetect", "--drive", tmpdir])
                self.assertEqual(result.exit_code, 0)
                self.assertIn("No new distros detected", result.stdout)

    def test_autodetect_has_flags(self) -> None:
        result = runner.invoke(app, ["autodetect", "--help"])
        for flag in ["--config", "--drive", "--dry-run"]:
            self.assertIn(flag, result.stdout, f"autodetect missing {flag}")


# ── list ─────────────────────────────────────────────────────────────────────


class TestList(unittest.TestCase):
    def test_list_empty_drive(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            result = runner.invoke(app, ["list", "--drive", tmpdir])
            self.assertEqual(result.exit_code, 0)
            self.assertIn("No ISO files found", result.stdout)

    def test_list_shows_isos(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            iso = Path(tmpdir) / "archlinux-2026.iso"
            iso.write_bytes(b"\x00" * (1024 * 1024))
            with patch("src.main.load_all_metadata", return_value={}):
                result = runner.invoke(app, ["list", "--drive", tmpdir])
                self.assertEqual(result.exit_code, 0)
                self.assertIn("archlinux-2026.iso", result.stdout)

    def test_list_has_flags(self) -> None:
        result = runner.invoke(app, ["list", "--help"])
        self.assertIn("--config", result.stdout)
        self.assertIn("--drive", result.stdout)

    def test_list_does_not_have_dry_run(self) -> None:
        result = runner.invoke(app, ["list", "--help"])
        self.assertNotIn("--dry-run", result.stdout)


# ── sync ─────────────────────────────────────────────────────────────────────


class TestSync(unittest.TestCase):
    @patch("src.main.find_ventoy_drives", return_value=[Path("/tmp")])
    @patch("src.main.load_config", return_value=MOCK_CONFIG)
    def test_sync_no_installed(self, *_: MagicMock) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch("src.main.find_ventoy_drives", return_value=[Path(tmpdir)]):
                result = runner.invoke(app, ["sync"])
                self.assertEqual(result.exit_code, 0)
                self.assertIn("No distros installed", result.stdout)

    def test_sync_has_flags(self) -> None:
        result = runner.invoke(app, ["sync", "--help"])
        for flag in ["--config", "--drive", "--dry-run", "--force", "--clean", "--all"]:
            self.assertIn(flag, result.stdout, f"sync missing {flag}")


# ── verify ───────────────────────────────────────────────────────────────────


class TestVerify(unittest.TestCase):
    def test_verify_has_flags(self) -> None:
        result = runner.invoke(app, ["verify", "--help"])
        self.assertIn("--config", result.stdout)
        self.assertIn("--drive", result.stdout)

    def test_verify_does_not_have_dry_run(self) -> None:
        result = runner.invoke(app, ["verify", "--help"])
        self.assertNotIn("--dry-run", result.stdout)


# ── version ──────────────────────────────────────────────────────────────────


class TestVersion(unittest.TestCase):
    def test_version_shows_version(self) -> None:
        result = runner.invoke(app, ["version"])
        self.assertEqual(result.exit_code, 0)
        self.assertIn("Visync version:", result.stdout)


# ── flag consistency ─────────────────────────────────────────────────────────


class TestFlagConsistency(unittest.TestCase):
    """Every mutating command must have --config, --drive, --dry-run."""

    def _get_options(self, cmd: str) -> str:
        return runner.invoke(app, [cmd, "--help"]).stdout

    def test_install_consistency(self) -> None:
        for flag in ["--config", "--drive", "--dry-run", "--file"]:
            self.assertIn(flag, self._get_options("install"), f"install missing {flag}")

    def test_remove_consistency(self) -> None:
        for flag in ["--config", "--drive", "--dry-run"]:
            self.assertIn(flag, self._get_options("remove"), f"remove missing {flag}")

    def test_update_consistency(self) -> None:
        for flag in ["--config", "--drive", "--force", "--clean", "--dry-run"]:
            self.assertIn(flag, self._get_options("update"), f"update missing {flag}")

    def test_sync_consistency(self) -> None:
        for flag in ["--config", "--drive", "--dry-run", "--force", "--clean", "--all"]:
            self.assertIn(flag, self._get_options("sync"), f"sync missing {flag}")

    def test_autodetect_consistency(self) -> None:
        for flag in ["--config", "--drive", "--dry-run"]:
            self.assertIn(flag, self._get_options("autodetect"), f"autodetect missing {flag}")

    def test_read_commands_no_dry_run(self) -> None:
        for cmd in ["search", "info", "list", "verify", "version"]:
            self.assertNotIn("--dry-run", self._get_options(cmd), f"{cmd} should not have --dry-run")

    def test_read_commands_have_config_and_drive(self) -> None:
        for cmd in ["search", "info", "list", "verify"]:
            opts = self._get_options(cmd)
            self.assertIn("--config", opts, f"{cmd} missing --config")
            self.assertIn("--drive", opts, f"{cmd} missing --drive")


class TestShortFlags(unittest.TestCase):
    """Verify short flag aliases appear in help text."""

    def _get_options(self, cmd: str) -> str:
        return runner.invoke(app, [cmd, "--help"]).stdout

    def test_c_is_config(self) -> None:
        for cmd in [
            "install", "remove", "update", "search", "info",
            "list", "sync", "verify", "autodetect",
        ]:
            opts = self._get_options(cmd)
            self.assertIn("--config", opts)
            self.assertIn("-c", opts, f"{cmd} missing -c")

    def test_d_is_drive(self) -> None:
        for cmd in [
            "install", "remove", "update", "search", "info",
            "list", "sync", "verify", "autodetect",
        ]:
            opts = self._get_options(cmd)
            self.assertIn("--drive", opts)
            self.assertIn("-d", opts, f"{cmd} missing -d")

    def test_n_is_dry_run(self) -> None:
        for cmd in ["install", "remove", "update", "sync", "autodetect"]:
            opts = self._get_options(cmd)
            self.assertIn("--dry-run", opts)
            self.assertIn("-n", opts, f"{cmd} missing -n")

    def test_f_contextual(self) -> None:
        """install uses -f for --file, update/sync use -f for --force."""
        install_opts = self._get_options("install")
        self.assertIn("-f", install_opts)
        for cmd in ["update", "sync"]:
            opts = self._get_options(cmd)
            self.assertIn("-f", opts, f"{cmd} missing -f")


if __name__ == "__main__":
    unittest.main(verbosity=2)
