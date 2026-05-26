"""Scrape and synchronize any distribution dynamically configured inside config.toml."""

import re
import sys
import tomllib
import urllib.request
from pathlib import Path

# Adjust standard path imports for internal source files
sys.path.insert(0, str(Path(__file__).parent.parent))
from src.finder import find_installed_isos, find_ventoy_drives


def load_config() -> dict:
    """Load configuration dictionary maps and distro settings from config.toml."""
    config_path = Path(__file__).parent.parent / "config.toml"
    try:
        with open(config_path, "rb") as f:
            return tomllib.load(f)
    except Exception as e:
        print(f"[-] Critical Error: Failed to parse config.toml database: {e}")
        return {}


def fetch_html(url: str) -> str:
    """Download plain text source HTML from an external mirror index."""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=10) as response:
            return response.read().decode("utf-8", errors="ignore")
    except Exception as e:
        print(f"[-] Network link failure targeting mirror node {url}: {e}")
        return ""


def process_scraping_strategy(name: str, settings: dict) -> tuple[str, str]:
    """Resolve specific folder parsing pipelines based on the configured strategy."""
    strategy = settings.get("strategy")
    base_url = settings.get("base_url")
    iso_regex = settings.get("iso_regex")

    # Strategy A: Direct Index File Tracking (e.g. Arch Linux)
    if strategy == "direct_match":
        html = fetch_html(base_url)
        if not html:
            return "", ""
        match = re.search(iso_regex, html)
        if match:
            return match.group(1), f"{base_url}{match.group(1)}"

    # Strategy B: Two-Tier Version Directory Traversal for Fedora
    elif strategy == "fedora_nested":
        root_html = fetch_html(base_url)
        if not root_html:
            return "", ""
        versions = re.findall(settings.get("version_regex"), root_html)
        if not versions:
            return "", ""

        versions.sort(key=lambda x: [int(d) for d in x.split(".") if d.isdigit()])
        latest_version = versions[-1]

        iso_dir_url = f"{base_url}{latest_version}/Workstation/x86_64/iso/"
        iso_html = fetch_html(iso_dir_url)
        if not iso_html:
            return "", ""

        match = re.search(iso_regex, iso_html)
        if match:
            return match.group(1), f"{iso_dir_url}{match.group(1)}"

    # Strategy C: Directory Sub-paths for Ubuntu Ecosystem Releases
    elif strategy == "ubuntu_nested":
        root_html = fetch_html(base_url)
        if not root_html:
            return "", ""
        versions = re.findall(settings.get("version_regex"), root_html)
        if not versions:
            return "", ""

        versions.sort(key=lambda x: [int(d) for d in x.split(".") if d.isdigit()])
        latest_version = versions[-1]

        iso_dir_url = f"{base_url}{latest_version}/"
        iso_html = fetch_html(iso_dir_url)
        if not iso_html:
            return "", ""

        match = re.search(iso_regex, iso_html)
        if match:
            return match.group(1), f"{iso_dir_url}{match.group(1)}"

    return "", ""


def download_iso(url: str, dest_path: Path):
    """Download streaming asset payloads showing direct feedback text trackers."""
    print(f"[*] Extracting resource stream -> {dest_path.name}")
    try:

        def callback(blocks, block_size, total_size):
            if total_size > 0:
                percent = (blocks * block_size / total_size) * 100
                sys.stdout.write(f"\r    -> Progress Counter: {percent:.1f}%")
                sys.stdout.flush()

        urllib.request.urlretrieve(url, str(dest_path), reporthook=callback)
        print(f"\n[✓] Asset file write sequence complete.")
    except Exception as e:
        print(f"\n[-] Resource save exception tracking download: {e}")


def sync_all_configured_distros():
    """Iterate through user-defined scrapers to pull updates down safely."""
    config = load_config()
    distro_scrapers = config.get("distros", {})
    iso_settings = config.get("iso", {})

    if not distro_scrapers:
        print(
            "[-] Aborting: No distribution definitions configured inside [distros] block."
        )
        return

    # Check for CLI bypass flag
    use_buffer = "--no-buffer" not in sys.argv

    # Track target paths
    drives = find_ventoy_drives()
    if not drives:
        print("[-] Target failure: No valid active Ventoy partition structures found.")
        return
    ventoy_root = drives[0]

    # Establish output path limits
    config_download_dir = iso_settings.get("download_dir", "").strip()
    if use_buffer and config_download_dir:
        download_target_dir = Path(config_download_dir)
        download_target_dir.mkdir(parents=True, exist_ok=True)
        print(f"[*] Buffer Staging Enabled -> {download_target_dir}")
    else:
        download_target_dir = ventoy_root
        print(
            f"[*] Direct Volume Mode Enabled -> Writing to mount path: {download_target_dir}"
        )

    # Process all user entries one by one
    for entry_id, settings in distro_scrapers.items():
        clean_name = settings.get("clean_name", entry_id)
        print(f"\n=== PROCESSING REPOSITORY SYNCHRONIZATION: {clean_name.upper()} ===")

        latest_filename, download_url = process_scraping_strategy(clean_name, settings)
        if not latest_filename:
            print(
                f"[-] Unable to determine remote file properties for {clean_name}. Skipping section."
            )
            continue

        print(f"[+] Current upstream variant reference target: {latest_filename}")

        # Scan active device profiles
        local_ventoy_files = find_installed_isos(ventoy_root)

        if any(f.name == latest_filename for f in local_ventoy_files):
            print(f"[✓] {clean_name} is fully initialized and matches upstream build.")
            continue

        # Look for outdated occurrences targeting the specific lower keyword tag
        target_keyword = settings.get("keyword", "").lower()
        if target_keyword:
            for local_file in local_ventoy_files:
                if target_keyword in local_file.name.lower():
                    print(
                        f"[X] Stale package block version detected on storage media: {local_file.name}"
                    )
                    print(
                        "[*] Performing file node eviction to maintain disk constraints..."
                    )
                    try:
                        local_file.unlink()
                    except Exception as e:
                        print(f"[-] Node clearance exception error: {e}")

        # Execute final write loop
        final_file_destination = download_target_dir / latest_filename
        download_iso(download_url, final_file_destination)


if __name__ == "__main__":
    print("====================================================")
    print("     VISYNC PROTOCOL LOGISTICAL EXTENSION ENGINE    ")
    print("====================================================")
    sync_all_configured_distros()
