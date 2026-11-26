#!/usr/bin/env python3
"""Build the install archive for a release.

The archive layout is fixed by AGENTS.md: `custom_components/`, `LICENSE` and
`README.md`, no caches. The version comes from `manifest.json`, so the archive
name cannot disagree with what Home Assistant reports as the installed version.
"""
from __future__ import annotations

import argparse
import json
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MANIFEST = ROOT / "custom_components" / "ermangizer" / "manifest.json"
PAYLOAD = ["custom_components", "LICENSE", "README.md"]


def manifest_version() -> str:
    return json.loads(MANIFEST.read_text(encoding="utf-8"))["version"]


def wanted(relative: Path) -> bool:
    return "__pycache__" not in relative.parts and relative.suffix != ".pyc"


def payload_files() -> list[Path]:
    """Files for the archive, as paths relative to the repository root."""
    out: list[Path] = []
    for entry in PAYLOAD:
        source = ROOT / entry
        files = (
            [source]
            if source.is_file()
            else sorted(p for p in source.rglob("*") if p.is_file())
        )
        out.extend(f.relative_to(ROOT) for f in files if wanted(f.relative_to(ROOT)))
    return out


def build(output: Path) -> list[str]:
    output.parent.mkdir(parents=True, exist_ok=True)
    names: list[str] = []
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        for relative in payload_files():
            archive.write(ROOT / relative, relative)
            names.append(str(relative))
    return names


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=ROOT / "dist")
    parser.add_argument("--version", default=None, help="override the manifest version")
    parser.add_argument(
        "--check",
        action="store_true",
        help="verify the archive for the manifest version exists and is current",
    )
    args = parser.parse_args()

    version = args.version or manifest_version()
    output = args.output_dir / f"ha-ermangizer-{version}.zip"

    if args.check:
        if not output.exists():
            raise SystemExit(f"MISSING {output}")
        with zipfile.ZipFile(output) as archive:
            stale = archive.testzip()
            if stale:
                raise SystemExit(f"CORRUPT entry: {stale}")
            packed = set(archive.namelist())
        on_disk = {str(path) for path in payload_files()}
        if packed != on_disk:
            missing = ", ".join(sorted(on_disk - packed))
            extra = ", ".join(sorted(packed - on_disk))
            raise SystemExit(f"STALE archive. missing [{missing}] extra [{extra}]")
        print(f"OK {output.name}: {len(packed)} files match the working tree")
        return

    names = build(output)
    print(f"{output.relative_to(ROOT)}  {len(names)} files  (version {version})")


if __name__ == "__main__":
    main()
