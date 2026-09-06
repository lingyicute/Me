#!/usr/bin/env python3
import re, base64, urllib.request, os, sys, glob, json, hashlib

FONT_URL = "https://raw.githubusercontent.com/lingyicute/Nebulove/main/Nebulove.ttf"
FONT_FALLBACK_URL = "https://nebulove.92li.uk/Nebulove.woff2"
EMOJI_TTF_PATH = "static/fonts/Segoe UI Emoji.ttf"
EMOJI_FALLBACK_URL = "../fonts/Segoe UI Emoji.woff2"
CSS_PATH = "static/css/style.css"
CACHE_PATH = "scripts/.font-subset-cache.json"
TMP_FONT_PATH = "/tmp/Nebulove.ttf"
TEXT_SOURCES = ["index.html", "static/js/script.js"] + sorted(glob.glob("static/css/*.css"))

def collect_chars():
    """收集页面可能用到的全部字符"""
    chars = set()
    for path in TEXT_SOURCES:
        if not os.path.exists(path):
            print(f"Warning: {path} not found, skipped.")
            continue
        with open(path, "r", encoding="utf-8") as f:
            chars.update(f.read())
    # Ensure full ASCII printable set (32 to 126)
    for c in range(32, 127):
        chars.add(chr(c))
    # Common punctuation
    chars.update(['：', '，', '。', '！', '？', '；', '“', '”', '‘', '’', '（', '）', '【', '】', '—', '…', '·', '《', '》', '×', '＝', '÷', '＋', '－'])
    # Emoji 组合控制符（ZWJ / VS15 / VS16），保证 emoji 序列完整性
    chars.update(['\u200d', '\ufe0e', '\ufe0f'])
    return chars

def subset_to_woff2(font, chars, note=""):
    """子集化"""
    from fontTools.subset import Subsetter, Options

    cmap = font.getBestCmap()
    included = sorted(c for c in chars if ord(c) in cmap)
    if note:
        print(f"{note}: 字体命中 {len(included)} 个字符")
    subsetter = Subsetter(options=Options())
    subsetter.populate(unicodes=sorted({ord(c) for c in chars}))
    subsetter.subset(font)
    font.flavor = "woff2"
    font.recalcTimestamp = False  # 冻结 head.modified，保证输出可复现
    import io
    buf = io.BytesIO()
    font.save(buf)
    return buf.getvalue(), "".join(included)

def build_nebulove(chars):
    from fontTools.ttLib import TTFont
    if not os.path.exists(TMP_FONT_PATH):
        print(f"Downloading font from {FONT_URL}...")
        try:
            urllib.request.urlretrieve(FONT_URL, TMP_FONT_PATH)
        except Exception as e:
            print(f"Failed to download font: {e}", file=sys.stderr)
            sys.exit(1)
    font = TTFont(TMP_FONT_PATH)
    cmap = font.getBestCmap()
    missing = sorted(c for c in chars if ord(c) not in cmap and not c.isspace())
    if missing:
        print(f"Note: {len(missing)} chars not in Nebulove (emoji 等由 Segoe UI Emoji 渲染): {''.join(missing[:80])}")
    return subset_to_woff2(font, chars, "Nebulove")

def build_emoji(chars):
    from fontTools.ttLib import TTFont
    if not os.path.exists(EMOJI_TTF_PATH):
        print(f"Error: {EMOJI_TTF_PATH} not found — Fluent Emoji 是站点设计的一部分，缺少源文件即中止。", file=sys.stderr)
        sys.exit(1)
    font = TTFont(EMOJI_TTF_PATH)
    woff2, included = subset_to_woff2(font, chars, "Segoe UI Emoji (Fluent Emoji)")
    from fontTools.ttLib import TTFont as TF
    import io
    check = TF(io.BytesIO(woff2))
    if 'COLR' not in check or 'CPAL' not in check:
        print("Error: emoji 子集丢失 COLR/CPAL 彩色表 — 中止。", file=sys.stderr)
        sys.exit(1)
    kept = "".join(sorted(set(included) - {chr(c) for c in range(32, 127)}))
    print(f"  emoji 子集保留的非 ASCII 字符: {kept}")
    return woff2

def replace_face(css, family, new_block):
    """替换指定 font-family 的 @font-face，返回新 CSS"""
    target = None
    for m in re.finditer(r'@font-face\s*\{[^}]*\}', css):
        if re.search(r'font-family\s*:\s*[\'"]?' + re.escape(family) + r'[\'"]?\s*;', m.group(0)):
            target = m
            break
    if target is None:
        print(f'Error: @font-face for font-family "{family}" not found in style.css.', file=sys.stderr)
        sys.exit(1)
    return css[:target.start()] + new_block + css[target.end():]

def main():
    force = "--force" in sys.argv

    if not os.path.exists(CSS_PATH):
        print(f"Error: {CSS_PATH} not found.", file=sys.stderr)
        sys.exit(1)

    print("Reading text sources:", ", ".join(TEXT_SOURCES))
    chars = collect_chars()
    print(f"Total unique characters needed: {len(chars)}")

    emoji_src_hash = ""
    if os.path.exists(EMOJI_TTF_PATH):
        with open(EMOJI_TTF_PATH, "rb") as f:
            emoji_src_hash = hashlib.sha256(f.read()).hexdigest()

    fingerprint = hashlib.sha256(
        FONT_URL.encode() + emoji_src_hash.encode()
        + json.dumps(sorted(ord(c) for c in chars)).encode()
    ).hexdigest()

    # 字符集与字体源均与上次一致，且 CSS 中已内联两份子集 → 跳过（--force 可强制）
    if not force and os.path.exists(CACHE_PATH):
        try:
            cached = json.load(open(CACHE_PATH, encoding="utf-8"))
            css_now = open(CSS_PATH, encoding="utf-8").read()
            if cached.get("fingerprint") == fingerprint and css_now.count("data:font/woff2") >= 2:
                print("Charset unchanged since last subset. Skipping. (use --force to rebuild)")
                return
        except Exception:
            pass  # 缓存损坏则重新生成

    nebulove_woff2, _ = build_nebulove(chars)
    print(f"Nebulove subset: {len(nebulove_woff2)} bytes ({len(nebulove_woff2) / 1024:.2f} KB)")
    emoji_woff2 = build_emoji(chars)
    print(f"Segoe UI Emoji subset: {len(emoji_woff2)} bytes ({len(emoji_woff2) / 1024:.2f} KB)")

    b64_nebulove = base64.b64encode(nebulove_woff2).decode("utf-8")
    b64_emoji = base64.b64encode(emoji_woff2).decode("utf-8")

    with open(CSS_PATH, "r", encoding="utf-8") as f:
        css = f.read()
    faces_before = css.count("@font-face")

    nebulove_face = f'''@font-face {{
    font-family: "b";
    src: url("data:font/woff2;charset=utf-8;base64,{b64_nebulove}") format("woff2"),
        url("{FONT_FALLBACK_URL}") format("woff2");
    font-display: swap;
}}'''
    emoji_face = f'''@font-face {{
    font-family: "emoji";
    src: url("data:font/woff2;charset=utf-8;base64,{b64_emoji}") format("woff2"),
        url("{EMOJI_FALLBACK_URL}") format("woff2");
    font-display: swap;
}}'''

    new_css = replace_face(css, "b", nebulove_face)
    new_css = replace_face(new_css, "emoji", emoji_face)

    # 安全检查
    if new_css.count("@font-face") != faces_before:
        print('Error: @font-face count changed — aborting.', file=sys.stderr)
        sys.exit(1)
    for fam in ('"b"', '"emoji"'):
        if f'font-family: {fam};' not in new_css:
            print(f'Error: @font-face {fam} missing after update — aborting.', file=sys.stderr)
            sys.exit(1)
    if EMOJI_FALLBACK_URL not in new_css:
        print('Error: emoji fallback url missing — aborting.', file=sys.stderr)
        sys.exit(1)

    with open(CSS_PATH, "w", encoding="utf-8") as f:
        f.write(new_css)
    with open(CACHE_PATH, "w", encoding="utf-8") as f:
        json.dump({"fingerprint": fingerprint, "sources": TEXT_SOURCES}, f, ensure_ascii=False, indent=2)
        f.write("\n")

    if new_css == css:
        print("style.css unchanged (identical output).")
    print("style.css updated successfully!")

if __name__ == "__main__":
    main()
