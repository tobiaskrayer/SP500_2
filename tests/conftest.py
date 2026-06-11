"""pytest-Setup: Repo-Root in sys.path (Module liegen top-level)."""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
