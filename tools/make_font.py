#!/usr/bin/env python3
"""產生自架版用的本機字型 fonts/zhuyinboard-round.woff2。

來源是 jf open 粉圓 2.1（SIL OFL 1.1）。只留下注音、介面文字和字典裡用得到的字，讓離線版不用從 Google Fonts 下載。
OFL 規定修改版（子集也算）不能使用保留字型名稱「open huninn」「huninn」，所以字型內部名稱改成 ZhuyinBoard Round。

用法：pip install fonttools brotli && python3 tools/make_font.py
"""
import urllib.request
from pathlib import Path

from fontTools import subset
from fontTools.ttLib import TTFont

ROOT = Path(__file__).resolve().parent.parent
SRC = "https://raw.githubusercontent.com/justfont/open-huninn-font/master/font/jf-openhuninn-2.1.ttf"
LICENSE = "https://raw.githubusercontent.com/justfont/open-huninn-font/master/LICENSE"
OUT = ROOT / "fonts" / "zhuyinboard-round.woff2"
FAMILY = "ZhuyinBoard Round"


def wanted_text() -> str:
    chars = {chr(c) for c in range(0x3100, 0x3130)} | set("ˉˊˇˋ˙") | {chr(c) for c in range(0x20, 0x7F)}
    chars |= set("，。？！、：；「」『』（）…—・→")
    for f in ("data/zhuyin-dict.js", "index.html"):
        chars |= {c for c in (ROOT / f).read_text(encoding="utf-8") if ord(c) > 0x7E}
    return "".join(sorted(chars))


def main() -> None:
    work = ROOT / "fonts" / "_work"
    work.mkdir(parents=True, exist_ok=True)
    ttf = work / "jf-openhuninn-2.1.ttf"
    if not ttf.exists():
        urllib.request.urlretrieve(SRC, ttf)
    urllib.request.urlretrieve(LICENSE, ROOT / "fonts" / "OFL.txt")

    font = TTFont(ttf)
    opts = subset.Options()
    opts.flavor = "woff2"
    opts.layout_features = ["*"]
    opts.name_IDs = ["*"]
    sub = subset.Subsetter(opts)
    sub.populate(text=wanted_text())
    sub.subset(font)

    name = font["name"]
    new = {1: FAMILY, 3: f"{FAMILY};2.1-subset", 4: FAMILY, 6: FAMILY.replace(" ", "-"), 16: FAMILY, 17: "Regular"}
    for rec in list(name.names):
        if rec.nameID in new:
            name.removeNames(nameID=rec.nameID)
    for nid, val in new.items():
        name.setName(val, nid, 3, 1, 0x409)
        name.setName(val, nid, 1, 0, 0)
    note = "Modified (subset) version of jf open huninn 2.1 by justfont Co., LTD., under SIL Open Font License 1.1."
    name.setName(note, 10, 3, 1, 0x409)

    font.flavor = "woff2"
    font.save(OUT)
    for old in (ROOT / "fonts").glob("huninn-subset.woff2"):
        old.unlink()
    for p in work.iterdir():
        p.unlink()
    work.rmdir()
    print(f"{OUT.name}: {OUT.stat().st_size / 1024:.0f} KB, {len(font.getGlyphOrder())} glyphs")


if __name__ == "__main__":
    main()
