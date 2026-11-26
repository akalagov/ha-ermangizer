"""The install archive layout, as AGENTS.md defines it.

A wrong layout breaks manual installs and is only noticed after the release is
published: Home Assistant needs `custom_components/ermangizer/` inside the zip,
and caches inside the archive overwrite the user's compiled files on unpack.
"""
from __future__ import annotations

import json
import zipfile
from pathlib import Path

from scripts.package_release import build, manifest_version, payload_files

ROOT = Path(__file__).resolve().parent.parent


def test_archive_carries_the_integration_under_custom_components(tmp_path: Path) -> None:
    output = tmp_path / "archive.zip"
    build(output)

    with zipfile.ZipFile(output) as archive:
        names = set(archive.namelist())

    assert "custom_components/ermangizer/manifest.json" in names
    assert "custom_components/ermangizer/translations/ru.json" in names
    assert {"LICENSE", "README.md"} <= names
    assert not [name for name in names if "__pycache__" in name or name.endswith(".pyc")]
    assert {name.split("/")[0] for name in names} == {
        "custom_components",
        "LICENSE",
        "README.md",
    }


def test_archive_version_matches_the_manifest(tmp_path: Path) -> None:
    """manifest.json is the single source of the version; the archive name and
    what Home Assistant reports as installed must agree with it."""
    output = tmp_path / f"ha-ermangizer-{manifest_version()}.zip"
    build(output)

    with zipfile.ZipFile(output) as archive:
        packed = json.loads(archive.read("custom_components/ermangizer/manifest.json"))

    assert packed["version"] == manifest_version()


def test_payload_skips_test_and_tooling_files() -> None:
    packed = {str(path) for path in payload_files()}
    assert not [path for path in packed if path.startswith(("tests/", "scripts/", ".github/"))]
    assert "pytest.ini" not in packed
    assert "requirements-dev.txt" not in packed
