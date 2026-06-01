# Visync

Ventoy ISO Synchronization Tool. Keeps your Ventoy drive current with upstream releases — automatically scrapes mirrors, downloads updates, verifies checksums, and cleans up deprecated images.

## Install

```bash
pip install -e .
```

Requires Python 3.11+ and a mounted Ventoy drive.

## Usage

```bash
# Sync all configured distros to the Ventoy drive
visync sync

# Preview what would be downloaded
visync sync --dry-run

# Force re-download even if version matches
visync sync --force

# List ISOs on the drive (metadata-fast or header-scan fallback)
visync list

# Verify checksums against upstream
visync verify

# Scan a specific directory instead of auto-detected drive
visync list --drive /path/to/ventoy
visync verify --drive /path/to/ventoy
```

## Configuration

Edit `config.toml` to add or remove distros. Each distro entry defines a scraping strategy, mirror URL, and checksum verification method.

**Built-in strategies:**
- `direct_match` — scrapes a flat index page (Arch Linux)
- `fedora_nested` — traverses version directories then variant subdirectories
- `ubuntu_nested` — traverses version directories for Ubuntu releases

**Checksum formats:** `gpg_checksum` (Fedora), `sha256sums` (Ubuntu, Arch), `json` (Tails)

## How it works

1. **Detect** — finds mounted Ventoy drives on Windows, macOS, or Linux
2. **Scrape** — concurrent mirror scraping with TCP pre-flight checks and watchdog timeouts
3. **Compare** — version-aware comparison (semantic or date-based) against local ISOs
4. **Download** — streaming downloads with 128 KiB chunks, disk space validation, and `.part` temp files
5. **Verify** — optional checksum verification against published hashes
6. **Clean** — removes deprecated ISOs of the same distro variant
7. **Cache** — writes `.visync/metadata/` manifests for instant future listings

## Safety

- `.visync/` watchdog enforces a 1 GiB ceiling (deep clean orphaned metadata, then wipe)
- Guardrails prevent deletion of `.iso` or `.img` files under any circumstance
- `--dry-run` mode for previewing without touching anything
- Failed downloads clean up `.part` files automatically

## Tests

```bash
python3 -m unittest discover -s test -v
```

## Debug

```bash
VISYNC_DEBUG=1 visync sync
```
