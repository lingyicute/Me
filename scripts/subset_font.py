#!/usr/bin/env python3
"""Subset the design fonts into separately cacheable WOFF2 files.

Optional maintenance/CI tool, not a runtime build requirement.
Run: pip install fonttools brotli && python scripts/subset_font.py
Use --force to refresh the upstream font, or NEBULOVE_FONT=/path/to/font.ttf offline.
"""
import hashlib
from html.parser import HTMLParser
import io
import json
import os
from pathlib import Path
import re
import sys
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
FONT_URL = "https://raw.githubusercontent.com/lingyicute/Nebulove/main/Nebulove.ttf"
CSS_PATH = ROOT / "static/css/style.css"
EMOJI_PATH = ROOT / "static/fonts/Segoe UI Emoji.ttf"
CACHE_PATH = ROOT / "scripts/.font-subset-cache.json"
OUTPUTS = {
    "b": ROOT / "static/fonts/nebulove-subset.woff2",
    "emoji": ROOT / "static/fonts/emoji-subset.woff2",
}


class VisibleText(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.ignored = 0
        self.chars = set()

    def handle_starttag(self, tag, attrs):
        if tag in {"head", "script", "style"}:
            self.ignored += 1
        if not self.ignored:
            for name, value in attrs:
                if name in {"alt", "title", "aria-label", "placeholder"} and value:
                    self.chars.update(value)

    def handle_endtag(self, tag):
        if tag in {"head", "script", "style"}:
            self.ignored = max(0, self.ignored - 1)

    def handle_data(self, text):
        if not self.ignored:
            self.chars.update(text)


def collect_chars():
    parser = VisibleText()
    parser.feed((ROOT / "index.html").read_text(encoding="utf-8"))
    chars = parser.chars
    # Avoid subsetting Chinese code comments, SVG paths or base64 blobs as visible text.
    css = re.sub(r"/\*.*?\*/", "", CSS_PATH.read_text(encoding="utf-8"), flags=re.S)
    for content in re.findall(r'content:\s*[\'"]([^\'"]*)[\'"]', css):
        chars.update(content)
    chars.update(chr(c) for c in range(32, 127))  # Includes dynamic visitor counts / English UI.
    chars.update("：，。！？；“”‘’（）【】—…·《》×＝÷＋－\u200d\ufe0e\ufe0f")
    return chars


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def subset(font, chars):
    from fontTools.subset import Options, Subsetter

    subsetter = Subsetter(options=Options())
    subsetter.populate(unicodes=sorted(ord(c) for c in chars))
    subsetter.subset(font)
    font.flavor = "woff2"
    font.recalcTimestamp = False
    output = io.BytesIO()
    font.save(output)
    return output.getvalue()


def replace_face(css, family, filename):
    for match in re.finditer(r"@font-face\s*\{[^}]*\}", css):
        if re.search(r'font-family:\s*"' + re.escape(family) + r'"\s*;', match[0]):
            face = f'''@font-face {{
    font-family: "{family}";
    src: url("../fonts/{filename}") format("woff2");
    font-display: swap;
}}'''
            return css[:match.start()] + face + css[match.end():]
    raise ValueError(f"Missing font-face: {family}")


def main():
    from fontTools.ttLib import TTFont

    chars = collect_chars()
    local_font = os.environ.get("NEBULOVE_FONT")
    source_key = digest(Path(local_font)) if local_font else FONT_URL
    fingerprint = hashlib.sha256((
        source_key + digest(EMOJI_PATH) + digest(Path(__file__))
        + json.dumps(sorted(ord(c) for c in chars))
    ).encode()).hexdigest()
    css = CSS_PATH.read_text(encoding="utf-8")
    if "--force" not in sys.argv and CACHE_PATH.exists():
        cached = json.loads(CACHE_PATH.read_text(encoding="utf-8"))
        if cached.get("fingerprint") == fingerprint and all(
            path.exists() and path.name in css
            and cached.get("outputs", {}).get(path.name) == digest(path)
            for path in OUTPUTS.values()
        ):
            print("Visible charset unchanged; WOFF2 subsets are current.")
            return

    if local_font:
        nebulove = TTFont(local_font)
    else:
        print("Downloading Nebulove source font...")
        with urllib.request.urlopen(FONT_URL, timeout=90) as response:
            nebulove = TTFont(io.BytesIO(response.read()))
    emoji = TTFont(EMOJI_PATH)
    fonts = {"b": subset(nebulove, chars), "emoji": subset(emoji, chars)}
    check = TTFont(io.BytesIO(fonts["emoji"]))
    if not {"COLR", "CPAL"}.issubset(check.keys()):
        raise ValueError("Fluent Emoji color tables were lost; refusing to publish")

    new_css = css
    for family, path in OUTPUTS.items():
        new_css = replace_face(new_css, family, path.name)
    assert new_css.count("@font-face") == css.count("@font-face")
    for family, path in OUTPUTS.items():
        path.write_bytes(fonts[family])
        print(f"{path.name}: {len(fonts[family]):,} bytes")
    CSS_PATH.write_text(new_css, encoding="utf-8")
    CACHE_PATH.write_text(json.dumps({
        "fingerprint": fingerprint,
        "source": FONT_URL,
        "charset_count": len(chars),
        "outputs": {p.name: digest(p) for p in OUTPUTS.values()},
    }, indent=2) + "\n", encoding="utf-8")
    print("Updated external subsets; no font data embedded in render-blocking CSS.")


if __name__ == "__main__":
    main()
