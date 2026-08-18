import sys
from pathlib import Path


def application_dir() -> Path:
    """Return the user-visible application directory.

    In a PyInstaller build this is the directory containing the executable,
    not PyInstaller's ``_internal`` or temporary extraction directory.
    """
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[1]


def storage_dir(name: str) -> Path:
    path = application_dir() / name
    path.mkdir(parents=True, exist_ok=True)
    return path


def resource_path(relative_path: str | Path) -> Path:
    """Return a bundled read-only resource in source and frozen builds."""
    root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[1]))
    return root / relative_path
