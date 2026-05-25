"""Unit tests for distro identification (no Ventoy hardware required)."""

import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.finder import identify_distro


class TestIdentifyDistro(unittest.TestCase):
    def test_base_distro_from_volume_id(self) -> None:
        self.assertEqual(identify_distro("UBUNTU_24_04", "ubuntu-24.04.iso"), "Ubuntu")
        self.assertEqual(identify_distro("FEDORA_41", "fedora-workstation.iso"), "Fedora")

    def test_fork_override_from_filename(self) -> None:
        self.assertEqual(identify_distro("ARCH_2024", "manjaro-kde-24.iso"), "Manjaro")
        self.assertEqual(identify_distro("DEBIAN_12", "kali-linux-2024.iso"), "Kali Linux")

    def test_standalone_match(self) -> None:
        self.assertEqual(identify_distro("NIXOS_24", "nixos.iso"), "NixOS")
        self.assertEqual(identify_distro("", "systemrescue-amd64.iso"), "SystemRescue")

    def test_filename_fallback(self) -> None:
        self.assertEqual(identify_distro("UNKNOWN", "alpine-3.19.iso"), "Alpine")

    def test_unknown_os(self) -> None:
        self.assertEqual(identify_distro("", "readme.txt"), "Unknown OS")


if __name__ == "__main__":
    unittest.main()
