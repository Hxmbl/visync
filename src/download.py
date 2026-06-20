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
from src.output import (
    console,
    error,
    header,
    info,
    make_download_progress,
    removed,
    spin_start,
    spin_stop,
    spin_update,
    success,
    warn,
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
DEFAULT_STAGING_DIR = Path.home() / ".cache" / "visync" / "staging"


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
                warn("Mirror protected by bot challenge (Anubis). Cannot scrape automatically.")
                warn("Visit the URL in a browser, complete the challenge, then re-run.")
                return ""
                return ""
            return html
    except urllib.error.URLError as e:
        err_str = str(e).lower()
        if "ssl" in err_str or "certificate" in err_str or "cert" in err_str:
            error(f"SSL certificate verification failed for {url}")
            info(f"Details: {e}")
            return ""
        error(f"Network error: {url}: {e}")
        return ""
    except Exception as e:
        error(f"Network error: {url}: {e}")
        return ""


def process_scraping_strategy(name: str, settings: dict) -> tuple[str, str]:
    """Resolve specific folder parsing pipelines based on the configured strategy."""
    strategy = settings.get("strategy")
    base_url = settings.get("base_url")
    iso_regex = settings.get("iso_regex")

    # Pre-flight connectivity check — skip dead mirrors instantly
    if base_url and not ping_mirror(base_url):
        warn(f"Mirror unreachable (ping failed): {base_url}")
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

        variant_path = settings.get("variant_path", "Workstation/x86_64/iso")
        iso_dir_url = f"{base_url}{latest_version}/{variant_path}/"
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

    # Strategy D: NixOS channel page — parse version, construct ISO URL
    elif strategy == "nixos_channel":
        html = fetch_html(base_url)
        if not html:
            return "", ""

        # The channel page contains text like "nixos-26.05 release nixos-26.05.1947.a0374025a863"
        version_match = re.search(r"nixos-[\d\.]+\s+release\s+(nixos-[\d\.]+\.[a-f0-9]+)", html)
        if not version_match:
            warn(f"{name} — could not parse NixOS version from channel page")
            return "", ""

        full_version = version_match.group(1)  # e.g. "nixos-26.05.1947.a0374025a863"
        # Strip the "nixos-" prefix for constructing URLs
        version_id = full_version.replace("nixos-", "", 1)  # e.g. "26.05.1947.a0374025a863"
        # Extract the short version (e.g. "26.05") from the full version
        short_version_match = re.search(r"nixos-([\d]+\.[\d]+)", full_version)
        if not short_version_match:
            return "", ""
        short_version = short_version_match.group(1)  # e.g. "26.05"

        iso_filename = f"nixos-minimal-{version_id}-x86_64-linux.iso"
        iso_url = f"https://releases.nixos.org/nixos/{short_version}/{full_version}/{iso_filename}"

        # Verify the URL is reachable
        try:
            req = urllib.request.Request(iso_url, method="HEAD", headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=MIRROR_HTTP_TIMEOUT) as resp:
                if resp.status == 200:
                    return iso_filename, iso_url
        except Exception:
            pass

        return "", ""

    # Strategy E: Pop!_OS JSON API — fetch latest build info
    elif strategy == "popos_api":
        import json as _json

        api_url = settings.get("api_url", "https://api.pop-os.org/builds")
        variant = settings.get("variant", "generic")
        release = settings.get("release", "24.04")

        url = f"{api_url}/{release}/{variant}"
        html = fetch_html(url)
        if not html:
            return "", ""

        try:
            data = _json.loads(html)
            iso_url = data.get("url", "")
            if iso_url:
                iso_filename = iso_url.rsplit("/", 1)[-1]
                return iso_filename, iso_url
        except (_json.JSONDecodeError, KeyError):
            warn(f"{name} — could not parse Pop!_OS API response")

        return "", ""

    # Strategy F: Tails JSON API — fetch latest version from releases.json
    elif strategy == "tails_api":
        import json as _json

        api_url = settings.get("api_url", "https://tails.net/install/v2/Tails/amd64/stable/latest.json")
        file_type = settings.get("file_type", "img")  # "iso" or "img"

        html = fetch_html(api_url)
        if not html:
            return "", ""

        try:
            data = _json.loads(html)
            installations = data.get("installations", [])
            if not installations:
                return "", ""

            latest = installations[0]
            for installation in installations:
                if installation.get("version", "") > latest.get("version", ""):
                    latest = installation

            for path in latest.get("installation-paths", []):
                if path.get("type") == file_type:
                    for target in path.get("target-files", []):
                        url = target.get("url", "")
                        if url:
                            iso_filename = url.rsplit("/", 1)[-1]
                            return iso_filename, url
        except (_json.JSONDecodeError, KeyError, IndexError):
            warn(f"{name} — could not parse Tails API response")

        return "", ""

    return "", ""


def download_iso(url: str, dest_path: Path, drive_root: Path | None = None) -> bool:
    """Download an ISO file with streaming progress and optional metadata persistence.

    Returns True on success, False on failure.
    """
    _debug(f"Starting download: {url} -> {dest_path}")
    console.print(f"  [cyan]↓[/cyan] Downloading [bold]{dest_path.name}[/bold]")

    # Verify sufficient disk space (need 105% of expected size)
    try:
        usage = shutil.disk_usage(dest_path.parent)
        available = usage.free
        req = urllib.request.Request(url, method="HEAD", headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            expected = int(resp.headers.get("Content-Length", 0))
        if expected > 0:
            needed = int(expected * 1.05)
            info(f"Expected: {expected / (1024**3):.2f} GiB | Available: {available / (1024**3):.2f} GiB")
            if available < needed:
                error(
                    f"Insufficient disk space — need {needed / (1024**3):.2f} GiB, "
                    f"have {available / (1024**3):.2f} GiB"
                )
                return False
        else:
            info(f"Available disk space: {available / (1024**3):.2f} GiB")
            warn("Content-Length unknown — disk space cannot be verified.")
    except Exception:
        pass

    CHUNK_SIZE = 128000
    part_path = dest_path.with_suffix(dest_path.suffix + ".part")

    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            total = int(resp.headers.get("Content-Length", 0))
            downloaded = 0
            with make_download_progress() as progress:
                task = progress.add_task(
                    "download",
                    filename=dest_path.name,
                    total=total or None,
                )
                with open(part_path, "wb", buffering=1048576) as f:
                    while True:
                        chunk = resp.read(CHUNK_SIZE)
                        if not chunk:
                            break
                        f.write(chunk)
                        downloaded += len(chunk)
                        progress.update(task, completed=downloaded)
    except OSError as e:
        error(f"Write/disk error during download: {e}")
        part_path.unlink(missing_ok=True)
        return False
    except Exception as e:
        error(f"Network error during download: {e}")
        part_path.unlink(missing_ok=True)
        return False

    part_path.rename(dest_path)
    success(f"Downloaded {dest_path.name}")

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

    return True


def _cleanup_old_versions(new_iso: Path) -> None:
    """Scan the target directory and delete older ISOs of the same distribution variant.

    Uses volume ID to match distros, and extracts a variant stem to avoid
    deleting different flavors (e.g. Fedora KDE vs Fedora Sway).
    Falls back to filename-based matching for .img files (no ISO 9660 header).
    Safe to call — deletion failures are logged but never crash the program.
    """
    _debug(f"Cleanup check for {new_iso.name}")
    try:
        new_vid = get_iso_volume_id(new_iso)
        if new_vid:
            new_distro = identify_distro(new_vid, new_iso.name)
            new_stem = _variant_stem(new_vid)
        else:
            # Filename-based fallback for .img files or unreadable ISOs
            new_distro = identify_distro("", new_iso.name)
            new_stem = new_iso.name.rsplit("-", 1)[0].lower() if "-" in new_iso.name else ""

        # Skip unknown or generic matches — don't delete anything we can't positively identify
        if new_distro in ("Unknown OS", ""):
            return

        target_dir = new_iso.parent
        all_isos = find_installed_isos(target_dir)

        for iso_path in all_isos:
            if iso_path == new_iso:
                continue

            try:
                old_vid = get_iso_volume_id(iso_path)
                if old_vid:
                    old_distro = identify_distro(old_vid, iso_path.name)
                    old_stem = _variant_stem(old_vid)
                else:
                    old_distro = identify_distro("", iso_path.name)
                    old_stem = iso_path.name.rsplit("-", 1)[0].lower() if "-" in iso_path.name else ""

                if old_distro == new_distro and old_stem == new_stem:
                    removed(f"Removing deprecated image: {iso_path.name}")
                    iso_path.unlink(missing_ok=True)
                    remove_iso_metadata(new_iso.parent, iso_path.name)
            except OSError:
                warn(f"Could not remove stale file: {iso_path.name}")
            except Exception:
                pass
    except Exception:
        pass


def _sweep_old_versions(drive_root: Path) -> None:
    """Scan all ISOs on the drive and remove older versions of the same distro+variant.

    Groups ISOs by (distro, variant_stem), sorts each group by version, and
    removes all but the newest in each group.
    """
    from collections import defaultdict

    _debug("Running sweep for stale ISOs")
    all_isos = find_installed_isos(drive_root)
    groups: dict[tuple[str, str], list[tuple[str, Path]]] = defaultdict(list)

    for iso_path in all_isos:
        vid = get_iso_volume_id(iso_path)
        if vid:
            distro = identify_distro(vid, iso_path.name)
            stem = _variant_stem(vid)
        else:
            distro = identify_distro("", iso_path.name)
            stem = iso_path.name.rsplit("-", 1)[0].lower() if "-" in iso_path.name else ""
        version = extract_version_from_filename(iso_path.name) or "0"
        if distro and distro != "Unknown OS":
            groups[(distro, stem)].append((version, iso_path))

    for (distro, _stem), versions in groups.items():
        if len(versions) <= 1:
            continue
        versions.sort(key=lambda x: [int(d) for d in x[0].split(".") if d.isdigit()])
        newest_version, newest_path = versions[-1]
        for version, iso_path in versions[:-1]:
            try:
                removed(f"Removing old {distro} {version}: {iso_path.name}")
                iso_path.unlink(missing_ok=True)
                remove_iso_metadata(drive_root, iso_path.name)
            except OSError as e:
                warn(f"Could not remove {iso_path.name}: {e}")


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

    tokens = _re.split(r"([\s\-_]+)", protected)
    cleaned = []
    for token in tokens:
        if _re.match(r"^[\s\-_]+$", token):
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
    spin_update(clean_name)

    latest_filename, download_url = process_scraping_strategy(clean_name, settings)
    if not latest_filename:
        warn(f"{clean_name} — unable to reach mirror")
        return entry_id, clean_name, "", False, None

    local_ventoy_files = find_installed_isos(ventoy_root)

    # Exact filename match — already up to date (skip check if --force)
    if not force and any(f.name == latest_filename for f in local_ventoy_files):
        success(f"{clean_name} is up to date")
        return entry_id, clean_name, latest_filename, True, None

    # Version-based comparison: find best local candidate and compare
    remote_version = extract_version_from_filename(latest_filename)
    if not remote_version:
        warn(f"{clean_name} — could not parse version from '{latest_filename}'")
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
                success(
                    f"{clean_name} is up to date (local {local_version}, upstream {remote_version})"
                )
                return entry_id, clean_name, latest_filename, True, None

    if force:
        warn(f"{clean_name} — force re-download")

    return entry_id, clean_name, latest_filename, False, download_url


def _cleanup_part_files(*directories: Path) -> None:
    """Delete any leftover .part files from the given directories."""
    for directory in directories:
        if not directory.is_dir():
            continue
        for part_file in directory.rglob("*.part"):
            part_file.unlink(missing_ok=True)


def sync_all_configured_distros(
    dry_run: bool = False,
    force: bool = False,
    config_path: Path | None = None,
):
    """Iterate through user-defined scrapers to pull updates down safely."""
    _debug(f"sync_all_configured_distros(dry_run={dry_run}, force={force})")
    config = load_config(config_path)
    distro_scrapers = config.get("distros", {})
    iso_settings = config.get("iso", {})

    if not distro_scrapers:
        error("No distribution definitions configured inside [distros] block.")
        return

    use_buffer = "--no-buffer" not in sys.argv

    drives = find_ventoy_drives()
    if not drives:
        error("No Ventoy drives found.")
        return
    ventoy_root = drives[0]

    visync_watchdog(ventoy_root)
    _sweep_old_versions(ventoy_root)

    config_download_dir = iso_settings.get("download_dir", "").strip()
    if use_buffer:
        download_target_dir = Path(config_download_dir) if config_download_dir else DEFAULT_STAGING_DIR
        download_target_dir.mkdir(parents=True, exist_ok=True)
        info(f"Buffer staging → {download_target_dir}")
    else:
        download_target_dir = ventoy_root
        info(f"Direct volume mode → {download_target_dir}")

    pending_downloads: list[tuple[str, str]] = []
    scrape_start = __import__("time").monotonic()
    spin_start("Syncing ISOs...")
    with concurrent.futures.ThreadPoolExecutor(max_workers=len(distro_scrapers)) as executor:
        future_map = {
            executor.submit(_check_distro, entry_id, settings, ventoy_root, force): entry_id
            for entry_id, settings in distro_scrapers.items()
        }
        for future in concurrent.futures.as_completed(future_map, timeout=SCRAPE_DEADLINE):
            elapsed = __import__("time").monotonic() - scrape_start
            if elapsed > SCRAPE_DEADLINE:
                break
            try:
                entry_id, clean_name, latest_filename, up_to_date, download_url = future.result(timeout=PER_DISTRO_TIMEOUT)
            except concurrent.futures.TimeoutError:
                error(f"{future_map[future]} timed out")
                continue
            except (TimeoutError, ConnectionResetError, OSError) as e:
                error(f"{future_map[future]}: {e}")
                continue
            if up_to_date or not download_url:
                continue
            pending_downloads.append((download_url, latest_filename))
        executor.shutdown(wait=False, cancel_futures=True)
    spin_stop()

    if dry_run:
        if not pending_downloads:
            info("All ISOs are current — nothing to download.")
        else:
            console.print()
            info(f"Would download {len(pending_downloads)} file(s):")
            for url, filename in pending_downloads:
                console.print(f"    [cyan]→[/cyan] {filename}")
    else:
        for download_url, latest_filename in pending_downloads:
            dest = download_target_dir / latest_filename
            part_file = dest.with_suffix(dest.suffix + ".part")
            try:
                ok = download_iso(download_url, dest, drive_root=ventoy_root)
            except (TimeoutError, ConnectionResetError, OSError) as e:
                error(f"Failed syncing {latest_filename}: {e}")
                part_file.unlink(missing_ok=True)
                continue
            if not ok:
                part_file.unlink(missing_ok=True)
                continue
            if dest.parent != ventoy_root:
                drive_dest = ventoy_root / latest_filename
                try:
                    shutil.copy2(dest, drive_dest)
                    success(f"Copied {latest_filename} to Ventoy drive")
                    _cleanup_old_versions(drive_dest)
                except OSError as e:
                    error(f"Failed copying {latest_filename} to drive: {e}")
                    continue

    return download_target_dir


if __name__ == "__main__":
    header("VISYNC PROTOCOL LOGISTICAL EXTENSION ENGINE")
    try:
        sync_all_configured_distros()
    except KeyboardInterrupt:
        console.print("\n[red]✕ Sync canceled by user. Cleaning up partial downloads...[/red]")
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
