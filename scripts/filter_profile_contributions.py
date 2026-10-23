#!/usr/bin/env python3
"""Remove known bulk-import days from github-profile-3d-contrib SVGs."""

from __future__ import annotations

import argparse
import datetime as dt
import re
import xml.etree.ElementTree as ET
from pathlib import Path


SVG_NS = "http://www.w3.org/2000/svg"
ET.register_namespace("", SVG_NS)

DATE_RANGE_RE = re.compile(r"^(\d{4}-\d{2}-\d{2}) / (\d{4}-\d{2}-\d{2})$")
TRANSLATE_RE = re.compile(r"translate\(([-\d.]+)[ ,]+([-\d.]+)\)")
SCALE_RE = re.compile(r"scale\(([-\d.]+)[ ,]+([-\d.]+)\)")


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _date_range(root: ET.Element) -> tuple[dt.date, dt.date]:
    for element in root.iter():
        if _local(element.tag) != "text" or not element.text:
            continue
        match = DATE_RANGE_RE.match(element.text.strip())
        if match:
            return tuple(dt.date.fromisoformat(value) for value in match.groups())  # type: ignore[return-value]
    raise ValueError("Contribution date range not found in SVG")


def _calendar_group(root: ET.Element, expected_days: int) -> ET.Element:
    for child in root:
        if _local(child.tag) != "g":
            continue
        bars = [item for item in child if _local(item.tag) == "g"]
        if len(bars) == expected_days:
            return child
    raise ValueError(f"Calendar group with {expected_days} days not found")


def _panel_level_zero(element: ET.Element) -> None:
    class_name = element.get("class")
    if class_name:
        class_name = re.sub(r"^(cont-(?:top|left|right)-)\d+$", r"\g<1>0", class_name)
        class_name = re.sub(r"^(cont-(?:top|left|right)-p\d+-)\d+$", r"\g<1>0", class_name)
        class_name = re.sub(r"^rb-l\d+-(top|left|right)$", r"rb-l0-\1", class_name)
        element.set("class", class_name)

    fill = element.get("fill")
    if fill:
        element.set("fill", re.sub(r"url\(#pattern_\d+_", "url(#pattern_0_", fill))


def _reset_bar(bar: ET.Element) -> None:
    transform = bar.get("transform", "")
    position = TRANSLATE_RE.search(transform)
    if not position:
        raise ValueError("Calendar bar is missing its translate transform")

    rects = [element for element in bar if _local(element.tag) == "rect"]
    if len(rects) != 3:
        raise ValueError("Unexpected calendar bar structure")

    left_panel = rects[1]
    scale = SCALE_RE.search(left_panel.get("transform", ""))
    if not scale:
        raise ValueError("Calendar bar is missing its panel scale")

    scale_y = float(scale.group(2))
    old_height = float(left_panel.get("height", "0")) * scale_y
    new_height = 3.0

    x = float(position.group(1))
    y = float(position.group(2)) + old_height - new_height
    bar.set("transform", f"translate({x:g} {y:.2f})")

    for panel in rects:
        _panel_level_zero(panel)

    for panel in rects[1:]:
        panel_scale = SCALE_RE.search(panel.get("transform", ""))
        if not panel_scale:
            raise ValueError("Calendar side panel is missing its scale")
        panel.set("height", f"{new_height / float(panel_scale.group(2)):.2f}")

    for child in list(bar):
        if _local(child.tag) == "animateTransform":
            bar.remove(child)
    for panel in rects:
        for child in list(panel):
            if _local(child.tag) == "animate":
                panel.remove(child)

def _decrease_total(root: ET.Element, removed: int) -> None:
    if removed <= 0:
        return
    for parent in root.iter():
        children = list(parent)
        for index, element in enumerate(children):
            if _local(element.tag) != "text" or (element.text or "").strip() != "contributions":
                continue
            if index == 0:
                continue
            total_element = children[index - 1]
            value = (total_element.text or "").strip()
            if value.isdigit():
                total_element.text = str(max(0, int(value) - removed))
                return


def filter_svg(path: Path, exclusions: dict[dt.date, int]) -> tuple[int, int]:
    tree = ET.parse(path)
    root = tree.getroot()
    start_date, end_date = _date_range(root)
    expected_days = (end_date - start_date).days + 1
    calendar = _calendar_group(root, expected_days)
    bars = [item for item in calendar if _local(item.tag) == "g"]

    removed = 0
    matched = 0
    for excluded_date, contribution_count in sorted(exclusions.items()):
        if excluded_date < start_date or excluded_date > end_date:
            continue
        _reset_bar(bars[(excluded_date - start_date).days])
        removed += contribution_count
        matched += 1

    if matched:
        _decrease_total(root, removed)
        tree.write(path, encoding="unicode", xml_declaration=False)
    return matched, removed


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("directory", type=Path)
    parser.add_argument(
        "--exclude",
        action="append",
        required=True,
        metavar="DATE=COUNT",
        help="Date and number of contributions to remove, for example 2026-10-02=120",
    )
    args = parser.parse_args()

    exclusions: dict[dt.date, int] = {}
    for value in args.exclude:
        date_value, separator, count_value = value.partition("=")
        if not separator:
            parser.error(f"Invalid exclusion {value!r}; expected DATE=COUNT")
        contribution_date = dt.date.fromisoformat(date_value)
        contribution_count = int(count_value)
        if contribution_count < 0:
            parser.error("Contribution count cannot be negative")
        exclusions[contribution_date] = contribution_count
    files = sorted(args.directory.glob("*.svg"))
    if not files:
        raise SystemExit(f"No SVG files found in {args.directory}")

    for path in files:
        matched, removed = filter_svg(path, exclusions)
        print(f"{path}: reset {matched} day(s), removed {removed} contribution(s)")


if __name__ == "__main__":
    main()
