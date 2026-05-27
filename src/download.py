"""Scrape and synchronize any distribution dynamically configured inside config.toml."""

import re
import shutil
import sys
import tomllib
import urllib.error
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
        # TODO: Add a later fallback mechanism to load a default embedded config if the file is missing or malformed
        return {}


def fetch_html(url: str, allow_insecure: bool = False) -> str:
    """Download plain text source HTML from an external mirror index. (Web scraping. API in the future?)"""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        ctx = None
        if allow_insecure:
            import ssl

            ctx = ssl._create_unverified_context()
        with urllib.request.urlopen(req, timeout=10, context=ctx) as response:
            html = response.read().decode("utf-8", errors="ignore")
            # Detect bot-protected pages (e.g. Anubis proof-of-work)
            if "Anubis" in html[:1000]:
                print("""
[-] Mirror protected by bot challenge (Anubis). Cannot scrape automatically."
Visit the URL in a browser, complete the challenge, then re-run."
(NOTE: The challenge cannot be forwarded to a browser because"
Anubis binds the challenge to this specific HTTP session.)")
                """)
                return ""
            return html
    except urllib.error.URLError as e:
        err_str = str(e).lower()
        if "ssl" in err_str or "certificate" in err_str or "cert" in err_str:
            print(
                f"[-] SSL certificate verification failed for {url}\n    Details: {e}"
            )
            try:
                answer = input(
                    "[?] SSL verification failed. Retry with an insecure connection? (y/N): "
                )
            except EOFError:
                print("\n[-] No input detected. Defaulting to 'No' to ensure security.")
                answer = "n"
            if answer.lower() == "y":
                return fetch_html(url, allow_insecure=True)
            print("    Skipping this mirror.")
            return ""
        print(f"[-] Network link failure targeting mirror node {url}: {e}")
        return ""
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

    # A later implementation could add a more generic "custom_parser" strategy that loads a user-defined Python module with custom parsing logic for more complex sites. Currently you have to choose from built-in strategies or add new ones manually in the code. Not really good.

    return "", ""


def download_iso(url: str, dest_path: Path):
    """Download streaming asset payloads showing direct feedback text trackers."""
    print(f"[*] Extracting resource stream -> {dest_path.name}")
    print(
        "    Note: Progress shows 0% during connection setup. "
        "This is normal, wait a bit."
    )

    # Verify sufficient disk space (need 105% of expected size)
    try:
        usage = shutil.disk_usage(dest_path.parent)
        available = usage.free
        req = urllib.request.Request(url, method="HEAD")
        with urllib.request.urlopen(req, timeout=10) as resp:
            expected = int(resp.headers.get("Content-Length", 0))
        if expected > 0:
            needed = int(expected * 1.05)
            print(
                f"    Expected size: {expected / (1024**3):.2f} GiB "
                f"| Available: {available / (1024**3):.2f} GiB"
            )
            if available < needed:
                print(
                    f"[-] Insufficient disk space. "
                    f"Need {needed / (1024**3):.2f} GiB, "
                    f"have {available / (1024**3):.2f} GiB."
                    "\nWe check for 105% of the expected size so we don't corrupt your drive.\nClean up some space and try again."
                )
                return
        else:
            print(
                f"    Available disk space: {available / (1024**3):.2f} GiB "
                f"(unknown download size, skipping space check)"  # <--- THIS IS RISKY.
            )
    except Exception:
        pass

    CHUNK_SIZE = 8192  # 8 KiB read buffer

    try:
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=30) as resp:
            total = int(resp.headers.get("Content-Length", 0))
            downloaded = 0
            with open(dest_path, "wb") as f:
                while True:
                    chunk = resp.read(CHUNK_SIZE)
                    if not chunk:
                        break
                    f.write(chunk)
                    downloaded += len(chunk)
                    if total > 0:
                        percent = (downloaded / total) * 100
                        sys.stdout.write(
                            f"\r    -> {downloaded / (1024**2):.0f} / "
                            f"{total / (1024**2):.0f} MiB ({percent:.1f}%)"
                        )
                        sys.stdout.flush()
        print(
            "\n[✓] Asset file write sequence complete."
        )  # <--- No need for this to have been an f-string since there are no variables.
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
        print("[-] ERROR: No Ventoy drives found.")
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

        # Execute final write loop
        final_file_destination = download_target_dir / latest_filename
        download_iso(download_url, final_file_destination)


if __name__ == "__main__":
    print("====================================================")
    print("     VISYNC PROTOCOL LOGISTICAL EXTENSION ENGINE    ")
    print("====================================================")
    sync_all_configured_distros()
