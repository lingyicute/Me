#!/usr/bin/env python3
"""Generate smaller images and a cached-canvas version of the original snake.

Optional maintenance tool; the website needs no Python/build step at runtime.
The original images and animated SVGs are kept as editable source assets.
Run: python -m pip install Pillow && python scripts/optimize_assets.py
"""
from pathlib import Path
import json
import re
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]


def images():
    from PIL import Image

    source = Image.open(ROOT / "static/img/bg.webp").convert("RGB")
    for name, width, quality in [("bg-desktop.webp", 1440, 82), ("bg-mobile.webp", 900, 80)]:
        height = round(source.height * width / source.width)
        image = source.resize((width, height), Image.Resampling.LANCZOS)
        image.save(ROOT / "static/img" / name, "WEBP", quality=quality, method=6)
    avatar = Image.open(ROOT / "static/img/logo.webp")
    avatar.resize((400, 400), Image.Resampling.LANCZOS).save(
        ROOT / "static/img/avatar.webp", "WEBP", quality=84, method=6
    )
    icon = Image.open(ROOT / "static/img/heartface.png").convert("RGBA")
    icon.resize((64, 64), Image.Resampling.LANCZOS).save(ROOT / "static/img/favicon.png", optimize=True)


def keyframes(css):
    pattern = r"@keyframes\s+(\w+)\{((?:[^{}]*\{[^{}]*\})*)\}"
    return dict(re.findall(pattern, css))


def frames(block, kind, base):
    result = {0: base, 100: base}
    for selectors, declarations in re.findall(r"([^{}]+)\{([^{}]+)\}", block):
        if kind == "translate":
            match = re.search(r"translate\(([-\d.]+)px,([-\d.]+)px\)", declarations)
            value = [float(match[1]), float(match[2])]
        else:
            match = re.search(r"scale\(([-\d.]+),1\)", declarations)
            value = [float(match[1])]
        for percent in selectors.split(","):
            result[float(percent.rstrip("%"))] = value
    return [[t, *value] for t, value in sorted(result.items())]


def compact_numbers(value):
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, list):
        return [compact_numbers(v) for v in value]
    if isinstance(value, dict):
        return {k: compact_numbers(v) for k, v in value.items()}
    return value


def snake(theme):
    source = ROOT / f"static/svg/snake-{theme}.svg"
    text = source.read_text(encoding="utf-8")
    svg = ET.fromstring(text)
    ns = {"s": "http://www.w3.org/2000/svg"}
    css = svg.find("s:style", ns).text
    animations = keyframes(css)
    variables = dict(re.findall(r"--(\w+):([^;}]+)", css))
    duration = int(re.search(r"animation:none (\d+)ms", css)[1])
    data = {
        "duration": duration,
        "colors": [variables["ce"], *[variables[f"c{i}"] for i in range(1, 5)]],
        "border": variables["cb"],
        "snakeColor": variables["cs"],
        "cells": [],
        "segments": [],
        "bars": [],
    }
    for rect in svg.findall("s:rect", ns):
        classes = rect.get("class").split()
        kind = classes[0]
        name = classes[1] if len(classes) > 1 else None
        if kind == "c":
            index = len(data["cells"])
            # Both originals use a column-major, 16-unit grid (last dark column is shorter).
            assert float(rect.get("x")) == (index // 7) * 16 + 2
            assert float(rect.get("y")) == (index % 7) * 16 + 2
            color, eaten_at = 0, 101
            if name:
                rule = re.search(r"\.c\." + name + r"\{([^}]+)\}", css)[1]
                color = int(re.search(r"fill:var\(--c([1-4])\)", rule)[1])
                eaten_at = float(re.search(r"([\d.]+)%,100%\{fill:var\(--ce\)", animations[name])[1])
            data["cells"].append([color, eaten_at])
        elif kind == "s":
            base = [int(name[1:]) * 16, -16]
            data["segments"].append({
                "rect": [float(rect.get(a)) for a in ("x", "y", "width", "height", "rx")],
                "frames": frames(animations[name], "translate", base),
            })
        elif kind == "u":
            rule = re.search(r"\.u\." + name + r"\{([^}]+)\}", css)[1]
            data["bars"].append({
                "rect": [float(rect.get(a)) for a in ("x", "y", "width", "height")],
                "color": int(re.search(r"fill:var\(--c([1-4])\)", rule)[1]),
                "frames": frames(animations[name], "scale", [0]),
            })
    folder = ROOT / "static/data"
    folder.mkdir(exist_ok=True)
    (folder / f"snake-{theme}.json").write_text(
        json.dumps(compact_numbers(data), separators=(",", ":")) + "\n", encoding="utf-8"
    )
    # A genuine static first frame for no-JS, reduced-motion and fetch failures.
    static_css = re.sub(r"@keyframes\s+\w+\{(?:[^{}]*\{[^{}]*\})*\}", "", css)
    static_css = re.sub(r"animation(?:-[\w-]+)?:[^;}]+;?", "", static_css)
    static_css = re.sub(r"[^{}]+\{\}", "", static_css)
    static = text.replace(css, static_css)
    assert "@keyframes" not in static and "animation:" not in static
    (ROOT / f"static/svg/snake-{theme}-static.svg").write_text(static, encoding="utf-8")


def main():
    images()
    for theme in ("Light", "Dark"):
        snake(theme)
    print("Images, static fallbacks and snake timing data regenerated from the original assets.")


if __name__ == "__main__":
    main()
