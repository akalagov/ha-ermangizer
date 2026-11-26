#!/usr/bin/env python3
"""Render the README parameter tables from the layout definitions.

The tables are long and mechanical, so they are generated rather than typed:
what the README claims is then exactly what the integration exposes. Run
without arguments to rewrite README.md, with ``--check`` to exit non-zero when
README.md has drifted from the code (a test does this).
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from custom_components.ermangizer.const import (  # noqa: E402
    ACCESS_ADVANCED,
    ACCESS_FACTORY,
    ACCESS_GENERAL,
    ACCESS_MONITOR,
)
from custom_components.ermangizer.layouts import LAYOUT_MAP, params_for_access  # noqa: E402
from custom_components.ermangizer.models import ParamDef  # noqa: E402

BEGIN = "<!-- params:begin -->"
END = "<!-- params:end -->"
README = ROOT / "README.md"

LEVELS = (
    (ACCESS_MONITOR, "только мониторинг"),
    (ACCESS_GENERAL, "общие"),
    (ACCESS_ADVANCED, "расширенные"),
    (ACCESS_FACTORY, "заводские"),
)

GROUPS = (
    (ACCESS_GENERAL, "Общие параметры"),
    (ACCESS_ADVANCED, "Расширенные параметры"),
    (ACCESS_FACTORY, "Заводские параметры"),
)

TABLE_HEADER = (
    "| Регистр | Параметр | Название | Сущность | Значения | Скрыт |\n"
    "| --- | --- | --- | --- | --- | --- |"
)


def _num(value: float) -> str:
    return f"{value:.2f}".rstrip("0").rstrip(".").replace(".", ",")


def _values(param: ParamDef) -> str:
    if param.options:
        return " / ".join(option for _, option in sorted(param.options.items()))
    span = f"{_num(param.min_value)}…{_num(param.max_value)}"
    if param.step not in (0.0, 1.0):
        span += f", шаг {_num(param.step)}"
    return f"{span} {param.unit or ''}".strip()


def _row(param: ParamDef) -> str:
    name = param.name + (" ⚠️" if param.warns else "")
    key = param.key.upper() if param.key[:1] == "p" else param.key
    kind = "select" if param.is_enum else "number"
    hidden = "да" if not param.entity_registry_enabled_default else ""
    return (
        f"| {param.address} | `{key}` | {name} | {kind} | {_values(param)} | {hidden} |"
    )


def _table(params: list[ParamDef]) -> str:
    return "\n".join([TABLE_HEADER, *(_row(p) for p in params)])


def render() -> str:
    modern = LAYOUT_MAP["modern_220_02_05"]
    legacy = LAYOUT_MAP["legacy_220_01"]
    out = [BEGIN, ""]

    out += [
        "Состав `number`/`select` зависит от уровня доступа контроллера: он",
        "повторяет уровни P099 самого прибора, а параметры фильтруются по рангу,",
        "поэтому повышение уровня только добавляет сущности, понижение — снимает.",
        "",
        "| Уровень | Параметров | Показанных по умолчанию |",
        "| --- | --- | --- |",
    ]
    for level, label in LEVELS:
        params = params_for_access(modern, level)
        shown = sum(1 for p in params if p.entity_registry_enabled_default)
        out.append(f"| {label} | {len(params)} | {shown} |")

    out += [
        "",
        "«Скрыт» — сущность зарегистрирована, но по умолчанию выключена; её",
        "можно включить на карточке устройства. На трафик это не влияет:",
        "параметры читаются блоками, скрытые — вместе с остальными.",
    ]

    for access, title in GROUPS:
        params = [p for p in modern.params if p.access == access]
        out += ["", f"### {title} — {len(params)}", "", _table(params)]

    out += [
        "",
        "### Параметры с предупреждением",
        "",
        "⚠️ в таблицах выше: меняют режим работы насоса. Предупреждение видно",
        "в атрибутах карточки сущности до того, как значение изменят.",
        "",
        "| Параметр | Предупреждение |",
        "| --- | --- |",
        *[f"| `{p.key.upper()}` {p.name} | {p.warns} |" for p in modern.params if p.warns],
    ]

    out += [
        "",
        "### Классическая карта `legacy_220_01`",
        "",
        f"В этом поколении нет Pnnn-алиасов: {len(legacy.params)} управляющих",
        "регистров заданы адресами напрямую.",
        "",
        _table(list(legacy.params)),
        END,
    ]
    return "\n".join(out)


def substitute(existing: str, block: str) -> str:
    pattern = re.compile(re.escape(BEGIN) + r".*?" + re.escape(END), re.DOTALL)
    if not pattern.search(existing):
        raise SystemExit(f"README.md has no {BEGIN} ... {END} block")
    return pattern.sub(lambda _: block, existing)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="fail if README.md is stale")
    args = parser.parse_args()

    existing = README.read_text(encoding="utf-8")
    updated = substitute(existing, render())
    if args.check:
        if updated != existing:
            print(
                "README.md parameter tables are stale; "
                "run scripts/render_params_table.py"
            )
            return 1
        return 0
    if updated != existing:
        README.write_text(updated, encoding="utf-8")
        print(f"updated {README}")
    else:
        print("README.md is already up to date")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
