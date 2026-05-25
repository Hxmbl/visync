import os
import sys

# Finds the absolute path of the [project] directory and adds it to sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

# Now Python can see the src directory
from src.finder import *

drives = find_ventoy_drives()

if not drives:
    print("No Ventoy drives detected.")
else:
    print("Detected Ventoy drives:")

    ventoy_paths = []

    for drive in drives:
        print("=" * 20, f" - {drive}", "=" * 20)
        ventoy_paths.append(drive)

        # os.system(f"ls {drive}")

        files = find_installed_isos(drive)
        if files:
            print(f"ISOs found on {drive}:")
            for f in files:
                print(f" - {f.name}")
        else:
            print(f"No ISOs found on {drive}.")

        print("\n")

        print("Trying the formatted version:")

        formatted_files = find_installed_isos_formatted(drive)
        if formatted_files:
            print(f"Formatted ISOs found on {drive}:")
            for f in formatted_files:
                print(f" - {f}")
        else:
            print(f"No ISOs found on {drive}. (Formatted version)")

        print("=" * 60 + "\n")
