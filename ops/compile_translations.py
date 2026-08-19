from __future__ import annotations

from pathlib import Path

import polib


PROJECT_ROOT = Path(__file__).resolve().parents[1]
LOCALE_ROOT = PROJECT_ROOT / "core" / "locale"


def compile_catalog(po_path: Path) -> Path:
    catalog = polib.pofile(str(po_path), encoding="utf-8")
    mo_path = po_path.with_suffix(".mo")
    temporary_path = mo_path.with_suffix(".mo.tmp")

    try:
        catalog.save_as_mofile(str(temporary_path))
        temporary_path.replace(mo_path)
    finally:
        temporary_path.unlink(missing_ok=True)

    return mo_path


def main() -> None:
    po_files = sorted(LOCALE_ROOT.glob("*/LC_MESSAGES/django.po"))
    if not po_files:
        raise RuntimeError(f"No translation catalogs found under {LOCALE_ROOT}")

    for po_path in po_files:
        mo_path = compile_catalog(po_path)
        print(f"Compiled {po_path.relative_to(PROJECT_ROOT)} -> {mo_path.name}")


if __name__ == "__main__":
    main()
