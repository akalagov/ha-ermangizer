"""UI strings: every step, menu option and error the flow can show must be labelled.

Home Assistant renders a menu option or a form field with an empty caption when
its string is missing, rather than falling back to English. A "Controllers on
this bus" dialog with two blank arrows is the result, and nothing in a flow
test notices because the option ids still work. These checks are static on
purpose: they compare what the flow can request against what the catalog and
the translations provide.
"""
from __future__ import annotations

import ast
import json
import re
from pathlib import Path

import pytest

from custom_components.ermangizer.const import DOMAIN, SUBENTRY_TYPE_PUMP

COMPONENT_DIR = Path(__file__).resolve().parent.parent / "custom_components" / DOMAIN

PLACEHOLDER = re.compile(r"\{([a-z_][a-z0-9_]*)\}")


def _load(name: str | Path) -> dict:
    return json.loads((COMPONENT_DIR / name).read_text(encoding="utf-8"))


def _menus() -> dict[str, list[str]]:
    """step_id -> menu_options, as requested by the flow code."""
    tree = ast.parse((COMPONENT_DIR / "config_flow.py").read_text(encoding="utf-8"))
    found: dict[str, list[str]] = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not (isinstance(func, ast.Attribute) and func.attr == "async_show_menu"):
            continue
        kwargs = {kw.arg: kw.value for kw in node.keywords if kw.arg}
        step = kwargs["step_id"].value
        options = [item.value for item in kwargs["menu_options"].elts]
        found[step] = options
    return found


def _keys(tree: dict, prefix: str = "") -> set[str]:
    out: set[str] = set()
    for key, value in tree.items():
        path = f"{prefix}/{key}"
        out.add(path)
        if isinstance(value, dict):
            out |= _keys(value, path)
    return out


def _strings(tree: dict, prefix: str = "") -> dict[str, str]:
    out: dict[str, str] = {}
    for key, value in tree.items():
        path = f"{prefix}/{key}"
        if isinstance(value, dict):
            out |= _strings(value, path)
        elif isinstance(value, str):
            out[path] = value
    return out


def test_every_menu_option_is_labelled() -> None:
    catalog = _load("strings.json")["config"]["step"]
    for step, options in _menus().items():
        labels = catalog.get(step, {}).get("menu_options", {})
        missing = [option for option in options if option not in labels]
        assert not missing, (
            f"step {step!r} offers {options} but strings.json has menu_options "
            f"for {sorted(labels)}; the UI shows blank rows for {missing}"
        )


def test_menu_options_match_the_flow_exactly() -> None:
    """Also the other way round: a renamed step must not leave strings behind."""
    catalog = _load("strings.json")["config"]["step"]
    for step, options in _menus().items():
        labels = set(catalog.get(step, {}).get("menu_options", {}))
        assert labels == set(options), (
            f"step {step!r}: strings.json labels {sorted(labels)}, the flow "
            f"offers {sorted(options)}"
        )


@pytest.mark.parametrize("language", ["en", "ru"])
def test_translations_cover_every_string(language: str) -> None:
    catalog = _load("strings.json")
    translated = _load(f"translations/{language}.json")
    missing = _keys(catalog) - _keys(translated)
    assert not missing, f"{language}.json is missing: {sorted(missing)}"


@pytest.mark.parametrize("language", ["en", "ru"])
def test_translations_keep_their_placeholders(language: str) -> None:
    """A dropped `{count}` renders a literal brace instead of a number."""
    catalog = _strings(_load("strings.json"))
    translated = _strings(_load(f"translations/{language}.json"))
    for path, source in catalog.items():
        if path not in translated:
            continue
        lost = set(PLACEHOLDER.findall(source)) - set(PLACEHOLDER.findall(translated[path]))
        assert not lost, f"{language}.json {path} dropped placeholders {sorted(lost)}"


def test_subentry_flow_has_its_own_strings_section() -> None:
    """Subentry flows read `config_subentries/<type>`, not `config`.

    Adding a pump from the device card is a subentry flow, so reusing the
    config-section labels leaves that dialog untranslated.
    """
    catalog = _load("strings.json")
    assert "config_subentries" in catalog, (
        "the pump subentry flow needs config_subentries/pump; config/step is "
        "not consulted for it"
    )
    subentry = catalog["config_subentries"][SUBENTRY_TYPE_PUMP]
    assert subentry.get("entry_type"), "entry_type names the thing in the UI"
    assert set(subentry["step"]) >= {"user", "reconfigure"}
    assert "user" in subentry.get("initiate_flow", {}), (
        "initiate_flow/user is the caption of the add button"
    )


def test_selector_options_are_labelled() -> None:
    """Selector options resolve through `selector/<key>/options/<value>`.

    An option id with no entry renders the raw id ("rtu_over_tcp") to the user,
    and a renamed constant silently loses its label, so compare against the
    lists the selectors are actually built from.
    """
    from custom_components.ermangizer.config_flow import (
        ACCESS_OPTIONS,
        CONNECTION_TYPE_OPTIONS,
        LAYOUT_OPTIONS,
    )

    options = _load("strings.json").get("selector", {})
    for key, values in (
        ("connection_type", CONNECTION_TYPE_OPTIONS),
        ("layout", LAYOUT_OPTIONS),
        ("access_level", ACCESS_OPTIONS),
    ):
        labelled = set(options.get(key, {}).get("options", {}))
        missing = [value for value in values if value not in labelled]
        assert not missing, f"selector {key!r} has no label for {missing}"
