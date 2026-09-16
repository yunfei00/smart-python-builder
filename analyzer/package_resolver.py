from __future__ import annotations


PACKAGE_MAP: dict[str, str] = {
    "bs4": "beautifulsoup4",
    "cv2": "opencv-python",
    "PIL": "Pillow",
    "serial": "pyserial",
    "sklearn": "scikit-learn",
    "yaml": "PyYAML",
}


def resolve_package(import_name: str) -> str:
    """Map a top-level import name to its installable PyPI distribution name."""
    return PACKAGE_MAP.get(import_name, import_name)


def resolve_packages(import_names: set[str]) -> list[str]:
    return sorted({resolve_package(name) for name in import_names}, key=str.lower)
