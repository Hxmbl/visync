import os
import sys

# Finds the absolute path of the [project] directory and adds it to sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

# Now Python can see the src directory
from src.finder import *


def test_find_ventoy_drives():
    drives = find_ventoy_drives()
    return drives


print(test_find_ventoy_drives())

print(test_find_ventoy_drives()[0])

os.system(f"ls {test_find_ventoy_drives()[0]}")
