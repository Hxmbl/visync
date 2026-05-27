# Visync
Ventoy ISO Synchronization Tool

# In development

Usage (quick and lazy)

- CLI (when installed):

  pip install -e .
  visync --help

- Tiny Python example (super simple):

  from pathlib import Path
  from src.finder import find_ventoy_drives, find_installed_isos_formatted

  drives = find_ventoy_drives()
  if drives:
      root = drives[0]
      print("Ventoy mounted at:", root)
      print("Detected ISOs:", find_installed_isos_formatted(root))
  else:
      print("No Ventoy drive found — plug one in and try again.")

Running tests

- No test runner is configured here and pytest isn't installed in this environment.
- To add/run tests locally: pip install pytest && pytest
