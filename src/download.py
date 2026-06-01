"""Scrape and synchronize distributions configured in config.toml."""

import concurrent.futures
import hashlib
import os
import re
import shutil
import socket
import sys
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).parent.parent))
from src.finder import (
    find_installed_isos,
    find_ventoy_drives,
    get_iso_volume_id,
    identify_distro,
    load_config,
    write_iso_metadata,
    remove_iso_metadata,
    visync_watchdog,
)
from src.verify import compare_versions, extract_version_from_filename

DEBUG = os.environ.get("VISYNC_DEBUG", "0") == "1"


def _debug(msg: str) -> None:
    """Print a debug message when VISYNC_DEBUG=1."""
    if DEBUG:
        print(f"  [debug] {msg}", file=sys.stderr)


MIRROR_CONNECT_TIMEOUT = 5
MIRROR_HTTP_TIMEOUT = 10
PER_DISTRO_TIMEOUT = 30
SCRAPE_DEADLINE = 120
DEFAULT_STAGING_DIR = Path("/tmp/visync_staging")


def ping_mirror(url: str) -> bool:
    """Pre-flight TCP connectivity check. Returns True if host is reachable."""
    _debug(f"Pinging {url}")
    try:
        parsed = urlparse(url)
        host = parsed.hostname
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        with socket.create_connection((host, port), timeout=MIRROR_CONNECT_TIMEOUT):
            _debug(f"Ping OK: {host}:{port}")
            return True
    except (socket.timeout, OSError) as e:
        _debug(f"Ping failed: {e}")
        return False


def fetch_html(url: str, allow_insecure: bool = False) -> str:
    """Download HTML source from a mirror index page."""
    _debug(f"Fetching {url} (insecure={allow_insecure})")
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        ctx = None
        if allow_insecure:
            import ssl

            ctx = ssl._create_unverified_context()
        with urllib.request.urlopen(req, timeout=MIRROR_HTTP_TIMEOUT, context=ctx) as response:
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
            print("    Skipping this mirror (non-interactive mode).")
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

    # Pre-flight connectivity check — skip dead mirrors instantly
    if not ping_mirror(base_url):
        print(f"[-] Mirror unreachable (ping failed): {base_url}")
        return "", ""

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


def download_iso(url: str, dest_path: Path, drive_root: Path | None = None) -> None:
    """Download an ISO file with streaming progress and optional metadata persistence."""
    _debug(f"Starting download: {url} -> {dest_path}")
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
                f"    Available disk space: {available / (1024**3):.2f} GiB"
            )
            print(
                "    [!] WARNING: Content-Length missing or unknown. "
                "Proceeding with download; disk space cannot be verified."
            )
    except Exception:
        pass

    CHUNK_SIZE = 128000
    part_path = dest_path.with_suffix(dest_path.suffix + ".part")

    try:
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=30) as resp:
            total = int(resp.headers.get("Content-Length", 0))
            downloaded = 0
            with open(part_path, "wb", buffering=1048576) as f:
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
    except OSError as e:
        print(f"\n[-] Write/disk error during download: {e}")
        part_path.unlink(missing_ok=True)
        return
    except Exception as e:
        print(f"\n[-] Network error during download: {e}")
        part_path.unlink(missing_ok=True)
        return

    part_path.rename(dest_path)
    print("\n[✓] Asset file write sequence complete.")

    sha256_hex = ""
    if drive_root:
        try:
            h = hashlib.sha256()
            with open(dest_path, "rb") as f:
                while True:
                    chunk = f.read(65536)
                    if not chunk:
                        break
                    h.update(chunk)
            sha256_hex = h.hexdigest()
        except OSError:
            pass

    _cleanup_old_versions(dest_path)

    if drive_root and sha256_hex:
        volume_id = get_iso_volume_id(dest_path)
        version = ""
        if volume_id:
            version = extract_version_from_filename(dest_path.name)
        variant_stem = _variant_stem(volume_id) if volume_id else ""
        write_iso_metadata(
            drive_root=drive_root,
            filename=dest_path.name,
            variant_stem=variant_stem,
            version=version,
            sha256=sha256_hex,
        )
        _debug(f"Metadata written for {dest_path.name}")


def _cleanup_old_versions(new_iso: Path) -> None:
    """Scan the target directory and delete older ISOs of the same distribution variant.

    Uses volume ID to match distros, and extracts a variant stem to avoid
    deleting different flavors (e.g. Fedora KDE vs Fedora Sway).
    Safe to call — deletion failures are logged but never crash the program.
    """
    _debug(f"Cleanup check for {new_iso.name}")
    try:
        new_vid = get_iso_volume_id(new_iso)
        if not new_vid:
            return
        new_distro = identify_distro(new_vid, new_iso.name)
        new_stem = _variant_stem(new_vid)

        # Skip unknown or generic matches — don't delete anything we can't positively identify
        if new_distro in ("Unknown OS", ""):
            return

        target_dir = new_iso.parent
        all_isos = find_installed_isos(target_dir)

        for iso_path in all_isos:
            if iso_path == new_iso:
                continue
            if iso_path.suffix.lower() != ".iso":
                continue

            try:
                old_vid = get_iso_volume_id(iso_path)
                if not old_vid:
                    continue
                old_distro = identify_distro(old_vid, iso_path.name)
                old_stem = _variant_stem(old_vid)

                if old_distro == new_distro and old_stem == new_stem:
                    print(
                        f"\x1b[33m[-] Removing deprecated image: {iso_path.name}\x1b[0m"
                    )
                    iso_path.unlink(missing_ok=True)
                    remove_iso_metadata(new_iso.parent, iso_path.name)
            except OSError:
                print(
                    f"[!] WARNING: Could not remove stale file: {iso_path.name}"
                )
            except Exception:
                pass
    except Exception:
        pass


def _variant_stem(volume_id: str) -> str:
    """Extract a stable variant stem from a volume ID by removing version-like tokens.

    Version tokens are segments that start with a digit (e.g. '44', '24.04.4').
    Architecture tokens like 'x86_64' and 'amd64' are preserved because they start
    with a letter, even though they contain digits. Consecutive separators
    (from removed version tokens) are collapsed into a single hyphen.

    Examples:
        'Fedora-E-dvd-x86_64-44'         → 'fedora-e-dvd-x86_64'
        'Fedora-KDE-Live-44'             → 'fedora-kde-live'
        'Ubuntu-Server 24.04.4 LTS amd64' → 'ubuntu-server-amd64'
    """
    import re as _re

    # Temporarily protect architecture names that contain underscores
    # (e.g. x86_64) by replacing the underscore with a placeholder
    protected = volume_id
    arch_patterns = _re.findall(r"\b(x86_\d+|amd\d+|i\d86|arm\w*)\b", volume_id, _re.I)
    for arch in arch_patterns:
        safe_arch = arch.replace("_", "§")
        protected = protected.replace(arch, safe_arch, 1)

    tokens = _re.split(r"([\s\-]+)", protected)
    cleaned = []
    for token in tokens:
        if _re.match(r"^[\s\-]+$", token):
            cleaned.append(token)
            continue
        # Remove tokens that start with a digit (version numbers)
        if token and token[0].isdigit():
            continue
        cleaned.append(token)

    stem = "".join(cleaned)
    stem = stem.replace("§", "_")
    stem = _re.sub(r"\b(lts|esd|point)\b", "", stem, flags=_re.I)
    stem = _re.sub(r"[\s\-]+", "-", stem).strip(" -_")
    return stem.lower()


def _check_distro(entry_id: str, settings: dict, ventoy_root: Path, force: bool = False) -> tuple[str, str, str, bool, str | None]:
    """Scrape and version-check a single distro. Returns metadata for download decisions."""
    clean_name = settings.get("clean_name", entry_id)
    _debug(f"Checking {clean_name} (force={force})")
    print(f"\n=== PROCESSING REPOSITORY SYNCHRONIZATION: {clean_name.upper()} ===")

    latest_filename, download_url = process_scraping_strategy(clean_name, settings)
    if not latest_filename:
        print(
            f"[-] Unable to determine remote file properties for {clean_name}. Skipping section."
        )
        return entry_id, clean_name, "", False, None

    print(f"[+] Current upstream variant reference target: {latest_filename}")

    local_ventoy_files = find_installed_isos(ventoy_root)

    # Exact filename match — already up to date (skip check if --force)
    if not force and any(f.name == latest_filename for f in local_ventoy_files):
        print(f"[✓] {clean_name} is fully initialized and matches upstream build.")
        return entry_id, clean_name, latest_filename, True, None

    # Version-based comparison: find best local candidate and compare
    remote_version = extract_version_from_filename(latest_filename)
    if not remote_version:
        print(f"[!] WARNING: Could not extract version from remote filename '{latest_filename}'. Skipping.")
        return entry_id, clean_name, "", False, None

    if not force:
        local_candidates = [
            f for f in local_ventoy_files
            if extract_version_from_filename(f.name)
        ]
        if local_candidates:
            remote_stem = latest_filename.split("-")[0].lower()
            same_distro = [
                f for f in local_candidates
                if f.name.lower().startswith(remote_stem)
            ]
            best_local = same_distro[0] if same_distro else local_candidates[0]
            local_version = extract_version_from_filename(best_local.name)

            comparison = compare_versions(remote_version, local_version)
            if comparison <= 0:
                print(
                    f"[✓] {clean_name} local version ({local_version}) is current "
                    f"(upstream: {remote_version}). Skipping download."
                )
                return entry_id, clean_name, latest_filename, True, None

    if force:
        print(f"[!] --force: Skipping version check for {clean_name}")

    return entry_id, clean_name, latest_filename, False, download_url


def _cleanup_part_files(*directories: Path) -> None:
    """Delete any leftover .part files from the given directories."""
    for directory in directories:
        if not directory.is_dir():
            continue
        for part_file in directory.rglob("*.part"):
            part_file.unlink(missing_ok=True)


def sync_all_configured_distros(dry_run: bool = False, force: bool = False):
    """Iterate through user-defined scrapers to pull updates down safely."""
    _debug(f"sync_all_configured_distros(dry_run={dry_run}, force={force})")
    config = load_config()
    distro_scrapers = config.get("distros", {})
    iso_settings = config.get("iso", {})

    if not distro_scrapers:
        print(
            "[-] Aborting: No distribution definitions configured inside [distros] block."
        )
        return

    use_buffer = "--no-buffer" not in sys.argv

    drives = find_ventoy_drives()
    if not drives:
        print("[-] ERROR: No Ventoy drives found.")
        return
    ventoy_root = drives[0]

    visync_watchdog(ventoy_root)

    config_download_dir = iso_settings.get("download_dir", "").strip()
    if use_buffer:
        download_target_dir = Path(config_download_dir) if config_download_dir else DEFAULT_STAGING_DIR
        download_target_dir.mkdir(parents=True, exist_ok=True)
        print(f"[*] Buffer Staging Enabled -> {download_target_dir}")
    else:
        download_target_dir = ventoy_root
        print(
            f"[*] Direct Volume Mode Enabled -> Writing to mount path: {download_target_dir}"
        )

    pending_downloads: list[tuple[str, str]] = []
    scrape_start = __import__("time").monotonic()
    with concurrent.futures.ThreadPoolExecutor(max_workers=len(distro_scrapers)) as executor:
        future_map = {
            executor.submit(_check_distro, entry_id, settings, ventoy_root, force): entry_id
            for entry_id, settings in distro_scrapers.items()
        }
        for future in concurrent.futures.as_completed(future_map, timeout=SCRAPE_DEADLINE):
            elapsed = __import__("time").monotonic() - scrape_start
            if elapsed > SCRAPE_DEADLINE:
                print(f"[!] Watchdog: overall scrape deadline ({SCRAPE_DEADLINE}s) exceeded. Aborting scrape phase.")
                break
            try:
                entry_id, clean_name, latest_filename, up_to_date, download_url = future.result(timeout=PER_DISTRO_TIMEOUT)
            except concurrent.futures.TimeoutError:
                print(f"[✗] Watchdog: {future_map[future]} scrape timed out ({PER_DISTRO_TIMEOUT}s limit). Skipping.")
                continue
            except (TimeoutError, ConnectionResetError, OSError) as e:
                print(f"[✗] Failed syncing {future_map[future]}: {e}")
                continue
            if up_to_date or not download_url:
                continue
            pending_downloads.append((download_url, latest_filename))
        executor.shutdown(wait=False, cancel_futures=True)

    if dry_run:
        if not pending_downloads:
            print("[*] Dry run: nothing to download — all ISOs are current.")
        else:
            print(f"\n[*] Dry run: would download {len(pending_downloads)} file(s):")
            for url, filename in pending_downloads:
                print(f"    -> {filename}")
                print(f"       {url}")
    else:
        for download_url, latest_filename in pending_downloads:
            dest = download_target_dir / latest_filename
            part_file = dest.with_suffix(dest.suffix + ".part")
            try:
                download_iso(download_url, dest, drive_root=ventoy_root)
            except (TimeoutError, ConnectionResetError, OSError) as e:
                print(f"[✗] Failed syncing {latest_filename}: {e}")
                part_file.unlink(missing_ok=True)
                continue

    return download_target_dir


if __name__ == "__main__":
    print("====================================================")
    print("     VISYNC PROTOCOL LOGISTICAL EXTENSION ENGINE    ")
    print("====================================================")
    try:
        sync_all_configured_distros()
    except KeyboardInterrupt:
        print("\n\x1b[31m✕ Sync canceled by user. Cleaning up partial downloads...\x1b[0m")
        _config = load_config()
        _iso_settings = _config.get("iso", {})
        _cleanup_targets: list[Path] = []
        _download_dir = _iso_settings.get("download_dir", "").strip()
        if _download_dir:
            _cleanup_targets.append(Path(_download_dir))
        else:
            _cleanup_targets.append(DEFAULT_STAGING_DIR)
        _drives = find_ventoy_drives()
        if _drives:
            _cleanup_targets.append(_drives[0])
        _cleanup_part_files(*_cleanup_targets)
        raise SystemExit(130)
