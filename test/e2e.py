#!/usr/bin/env python3
"""注音溝通板的端對端測試：在本機開伺服器提供 docs/，用模擬觸控檢查拼字、選取判斷、設定、離線，並存截圖。

用法：
  pip install playwright pillow && playwright install chromium
  python3 tools/build.py && python3 test/e2e.py
  （要用系統的 Chrome：CHROME_PATH=/usr/bin/google-chrome python3 test/e2e.py）
"""
import asyncio
import functools
import http.server
import os
import socketserver
import sys
import threading
from pathlib import Path

from playwright.async_api import async_playwright

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"
SHOTS = ROOT / "test" / "shots"
results = []


def check(name, cond, detail=""):
    results.append((name, bool(cond), detail))


MOCK = """
window.__said = [];
try {
  const s = window.speechSynthesis;
  if (s) { s.speak = u => { if (u && u.text && u.text.trim()) window.__said.push(u.text); }; s.cancel = () => {}; }
} catch (e) {}
"""


class QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


def serve():
    handler = functools.partial(QuietHandler, directory=str(DOCS))
    httpd = socketserver.ThreadingTCPServer(("127.0.0.1", 0), handler)
    httpd.daemon_threads = True
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd, f"http://127.0.0.1:{httpd.server_address[1]}/"


async def st(page):
    return await page.evaluate("""({view: ZhuyinBoard.state.view, group: ZhuyinBoard.state.group, comp: {...ZhuyinBoard.state.comp},
      text: ZhuyinBoard.state.text.map(u => u.t).join(''), last: ZhuyinBoard.state.text.slice(-1)[0] || null, said: window.__said.slice(),
      pre: (document.querySelector('#out .pre') || {}).textContent || ''})""")


async def center(page, sel):
    b = await page.locator(sel).first.bounding_box()
    return b["x"] + b["width"] / 2, b["y"] + b["height"] / 2, b


async def tap(page, sel, wait=620):
    x, y, _ = await center(page, sel)
    await page.mouse.move(x, y)
    await page.mouse.down()
    await page.wait_for_timeout(60)
    await page.mouse.up()
    await page.wait_for_timeout(wait)


async def functional(page, url):
    await page.goto(url)
    await page.evaluate("localStorage.clear()")
    await page.reload()
    await page.wait_for_timeout(300)
    s = await st(page)
    check("opens on the home view with 8 blocks", s["view"] == "home" and await page.locator("#board [data-target]").count() == 8, s["view"])

    # 拼「爸」
    await tap(page, '[aria-label="ㄅ、ㄆ、ㄇ、ㄈ這一組"]')
    await tap(page, '#board [data-say="ㄅ"]')
    s = await st(page)
    check("ㄅ picked → medial/final view, ㄅ shown in the typing strip", s["comp"]["ini"] == "ㄅ" and s["view"] == "mf" and s["pre"] == "ㄅ", s)
    check("ㄩ dimmed after ㄅ", await page.locator('#board [data-say="ㄩ"]').get_attribute("aria-disabled") == "true")
    await tap(page, '#board [data-say="ㄩ"]')
    s = await st(page)
    check("tapping a dimmed block does nothing", s["comp"]["med"] == "" and s["view"] == "mf", s)
    await tap(page, '[aria-label="ㄚ、ㄛ、ㄜ、ㄝ這一組"]')
    await tap(page, '#board [data-say="ㄚ"]')
    s = await st(page)
    check("ㄚ picked → tone view, strip shows ㄅㄚ", s["view"] == "tone" and s["pre"] == "ㄅㄚ", s)
    await tap(page, '#board [data-say="ㄅㄚˋ"]')
    s = await st(page)
    check("四聲 → candidates, strip shows ㄅㄚˋ", s["view"] == "cand" and s["pre"] == "ㄅㄚˋ", s)
    await tap(page, '#board [data-say="爸"]')
    s = await st(page)
    check("爸 typed with reading ㄅㄚˋ and spoken", s["text"] == "爸" and s["last"]["z"] == "ㄅㄚˋ" and "爸" in s["said"] and s["pre"] == "", s)

    blocks = page.locator("#board [data-target]")
    b0 = await blocks.nth(0).bounding_box()
    b1 = await blocks.nth(1).bounding_box()
    c0 = (b0["x"] + b0["width"] / 2, b0["y"] + b0["height"] / 2)
    c1 = (b1["x"] + b1["width"] / 2, b1["y"] + b1["height"] / 2)

    # 滑動修正：按在第一格，滑到第二格停一下再放開 → 第二格
    await page.mouse.move(*c0); await page.mouse.down(); await page.wait_for_timeout(150)
    await page.mouse.move(*c1, steps=8); await page.wait_for_timeout(250); await page.mouse.up(); await page.wait_for_timeout(620)
    s = await st(page)
    check("slide to another block and rest → that block", s["view"] == "group" and s["group"] == "ㄉㄊㄋㄌ", s)
    await tap(page, '[data-rail="back"]')

    # 抬手時手滑：停在第一格，放開時滑到第二格 → 第一格
    await page.mouse.move(*c0); await page.mouse.down(); await page.wait_for_timeout(400)
    await page.mouse.move(*c1, steps=2); await page.mouse.up(); await page.wait_for_timeout(620)
    s = await st(page)
    check("slip while lifting → the block the finger rested on", s["view"] == "group" and s["group"] == "ㄅㄆㄇㄈ", s)
    await tap(page, '[data-rail="back"]')

    # 取消：滑到打字列再放開
    ox, oy, _ = await center(page, "#out")
    await page.mouse.move(*c0); await page.mouse.down(); await page.wait_for_timeout(200)
    await page.mouse.move(ox, oy, steps=6); await page.wait_for_timeout(250); await page.mouse.up(); await page.wait_for_timeout(620)
    s = await st(page)
    check("lifting on the typing strip cancels", s["view"] == "home", s)

    # 縫隙吸附：點在離第二格 3px 的縫隙
    await page.mouse.move(b1["x"] - 3, c1[1]); await page.mouse.down(); await page.wait_for_timeout(60); await page.mouse.up(); await page.wait_for_timeout(620)
    s = await st(page)
    check("touch in the gap → nearest block", s["view"] == "group" and s["group"] == "ㄉㄊㄋㄌ", s)
    await tap(page, '[data-rail="back"]')

    # 防手抖連按
    await page.mouse.move(*c0); await page.mouse.down(); await page.wait_for_timeout(40); await page.mouse.up()
    await page.wait_for_timeout(230)
    gb = await page.locator("#board [data-target]").first.bounding_box()
    await page.mouse.move(gb["x"] + gb["width"] / 2, gb["y"] + gb["height"] / 2); await page.mouse.down(); await page.wait_for_timeout(40); await page.mouse.up()
    await page.wait_for_timeout(500)
    s = await st(page)
    check("second tap within the guard time is ignored", s["view"] == "group" and s["comp"]["ini"] == "", s)
    await tap(page, "#board [data-target]:nth-child(1)")
    s = await st(page)
    check("after the guard time a tap works again", s["comp"]["ini"] == "ㄅ", s)
    await tap(page, '[data-rail="back"]')
    s = await st(page)
    check("退回 removes the last zhuyin", s["comp"]["ini"] == "" and s["view"] == "home", s)

    # 按住才選
    await page.evaluate("ZhuyinBoard.cfg.press = 'hold'; ZhuyinBoard.render()")
    await page.mouse.move(*c0); await page.mouse.down(); await page.wait_for_timeout(330)
    s1 = await st(page)
    await page.wait_for_timeout(600)
    s2 = await st(page)
    await page.mouse.up(); await page.wait_for_timeout(400)
    check("hold mode: a short touch does not select", s1["view"] == "home", s1["view"])
    check("hold mode: holding long enough selects", s2["view"] == "group" and s2["group"] == "ㄅㄆㄇㄈ", s2)
    await page.evaluate("ZhuyinBoard.go('home')"); await page.wait_for_timeout(450)
    await page.mouse.move(*c0); await page.mouse.down(); await page.wait_for_timeout(300)
    await page.mouse.move(*c1, steps=2); await page.wait_for_timeout(120)
    await page.mouse.move(*c0, steps=2); await page.wait_for_timeout(420)
    s = await st(page); await page.mouse.up(); await page.wait_for_timeout(400)
    check("hold mode: a short wobble keeps the progress", s["view"] == "group" and s["group"] == "ㄅㄆㄇㄈ", s)
    await page.evaluate("ZhuyinBoard.go('home')"); await page.wait_for_timeout(450)

    # 一碰就選
    await page.evaluate("ZhuyinBoard.cfg.press = 'down'; ZhuyinBoard.render()")
    await page.mouse.move(*c1); await page.mouse.down(); await page.wait_for_timeout(40)
    await page.mouse.move(*c0, steps=3); await page.mouse.up(); await page.wait_for_timeout(500)
    s = await st(page)
    check("touch-down mode: the first block touched wins", s["view"] == "group" and s["group"] == "ㄉㄊㄋㄌ", s)
    await page.evaluate("ZhuyinBoard.cfg.press = 'lift'; ZhuyinBoard.go('home')"); await page.wait_for_timeout(450)

    # 常用句、唸出來
    await tap(page, '#board [data-say="常用句"]')
    await tap(page, '#board [data-say="我要喝水"]')
    s = await st(page)
    check("phrase typed and spoken", s["text"].endswith("我要喝水") and "我要喝水" in s["said"], (s["text"], s["said"][-2:]))
    await tap(page, '[data-rail="speak"]')
    s = await st(page)
    check("唸出來 speaks everything typed", s["said"][-1] == "爸我要喝水", s["said"][-1])

    # 設定：在「更多」裡，點一下不會開，按住一秒才開
    await tap(page, '[data-rail="menu"]')
    check("更多 has 9 blocks including 按住開設定", await page.locator("#board [data-target]").count() == 9 and await page.locator('#board [data-say="按住開設定"]').count() == 1)
    await tap(page, '#board [data-say="按住開設定"]')
    check("a quick tap does not open settings and shows a hint", await page.locator("#settings").is_hidden() and await page.locator("#toast").is_visible())
    x, y, _ = await center(page, '#board [data-say="按住開設定"]')
    await page.mouse.move(x, y); await page.mouse.down(); await page.wait_for_timeout(1250); await page.mouse.up(); await page.wait_for_timeout(400)
    check("holding 按住開設定 for a second opens settings", await page.locator("#settings").is_visible())
    await page.locator("[data-close-settings]").first.click(); await page.wait_for_timeout(300)
    check("完成 closes settings", await page.locator("#settings").is_hidden())

    # 大字給人看、全部清除
    await tap(page, '[data-rail="menu"]')
    await tap(page, '#board [data-say="大字給人看"]')
    fs = await page.evaluate("parseFloat(document.getElementById('showInner').style.fontSize)")
    check("大字給人看 fills the screen with large text", await page.locator("#show").is_visible() and fs > 100, fs)
    await tap(page, '[data-show="close"]')
    check("回去打字 closes it", await page.locator("#show").is_hidden())
    await tap(page, '[data-rail="menu"]')
    await tap(page, '#board [data-say="全部清除"]')
    await tap(page, "#board .warn")
    s = await st(page)
    check("全部清除 clears the text", s["text"] == "", s["text"])

    # 一頁全部注音
    await page.evaluate("ZhuyinBoard.cfg.layout = 'all'; ZhuyinBoard.go('all')"); await page.wait_for_timeout(300)
    check("one-page layout: 37 zhuyin + 常用句 + 拼好了", await page.locator("#board [data-target]").count() == 39)
    await tap(page, '#board [data-say="ㄇ"]')
    await tap(page, '#board [data-say="ㄚ"]')
    await tap(page, '#board [data-say="ㄇㄚˉ"]')
    await tap(page, '#board [data-say="媽"]')
    s = await st(page)
    check("one-page layout composes 媽", s["text"] == "媽" and s["view"] == "all", s)
    await page.evaluate("ZhuyinBoard.cfg.layout = 'big'; ZhuyinBoard.go('home')"); await page.wait_for_timeout(300)

    # 外接鍵盤
    await page.keyboard.press("1"); await page.wait_for_timeout(450)
    check("keyboard 1 picks the first block", (await st(page))["view"] == "group")

    # 純函式
    pure = await page.evaluate("""() => {
      const { pickTarget, releaseChoice } = ZhuyinBoard._test;
      const r = (l, t, w, h) => ({ left: l, top: t, right: l + w, bottom: t + h });
      const list = [{ el: 'A', r: r(0, 100, 100, 100) }, { el: 'B', r: r(116, 100, 100, 100) }];
      return {
        inside: pickTarget(list, 50, 150, null, 44), gapNearB: pickTarget(list, 112, 150, null, 44),
        farAway: pickTarget(list, 500, 150, null, 44), inZone: pickTarget(list, 50, 130, r(0, 120, 300, 20), 44),
        quickTapSlip: releaseChoice([{ el: 'A', t: 0 }, { el: 'B', t: 60 }], 90, 110, 120),
        restedThenSlip: releaseChoice([{ el: 'A', t: 0 }, { el: 'B', t: 500 }, { el: 'C', t: 800 }], 850, 110, 120),
        settledOnLast: releaseChoice([{ el: 'A', t: 0 }, { el: 'B', t: 500 }], 700, 110, 120),
        cancelZone: releaseChoice([{ el: 'A', t: 0 }, { el: null, t: 400 }], 600, 110, 120),
        slipOffEdge: releaseChoice([{ el: 'A', t: 0 }, { el: null, t: 400 }], 450, 110, 120),
      };
    }""")
    expect = {"inside": "A", "gapNearB": "B", "farAway": None, "inZone": None, "quickTapSlip": "A",
              "restedThenSlip": "B", "settledOnLast": "B", "cancelZone": None, "slipOffEdge": "A"}
    for k, v in expect.items():
        check(f"pure: {k}", pure[k] == v, pure[k])


async def offline(browser, url):
    ctx = await browser.new_context(viewport={"width": 430, "height": 860})
    page = await ctx.new_page()
    await page.goto(url)
    ok = await page.evaluate("""async () => { if (!('serviceWorker' in navigator)) return false;
      await navigator.serviceWorker.ready; return true; }""")
    await page.reload()
    await page.wait_for_function("navigator.serviceWorker.controller !== null", timeout=10000)
    await ctx.set_offline(True)
    await page.reload()
    await page.wait_for_timeout(500)
    tiles = await page.locator("#board [data-target]").count()
    dict_ok = await page.evaluate("Object.keys((window.ZHUYIN_DICT || {chars: {}}).chars).length > 1000")
    font_ok = await page.evaluate("document.fonts.check('40px \"ZhuyinBoard Round\"', 'ㄅ')")
    check("offline: reopening without network still works (board, dictionary, font)", ok and tiles == 8 and dict_ok and font_ok, (ok, tiles, dict_ok, font_ok))
    await ctx.close()


async def shots(browser, url):
    SHOTS.mkdir(parents=True, exist_ok=True)
    seed = "ZhuyinBoard.state.text = [...'我要喝水'].map(t => ({t, z: ''})).concat([{t:'爸', z:'ㄅㄚˋ'}]); "
    press = """(() => { const el = document.querySelectorAll('#board [data-target]')[%d]; const b = el.getBoundingClientRect();
      el.dispatchEvent(new PointerEvent('pointerdown', {bubbles: true, cancelable: true, clientX: b.left + b.width/2, clientY: b.top + b.height*0.6, pointerId: 3, pointerType: 'touch', isPrimary: true})); })()"""
    plan = [
        ("phone_home", 430, 860, "light", seed + "ZhuyinBoard.go('home');"),
        ("phone_mf_spelling", 430, 860, "light", seed + "ZhuyinBoard.state.comp.ini='ㄅ'; ZhuyinBoard.go('mf');" + press % 4),
        ("phone_menu", 430, 860, "light", seed + "ZhuyinBoard.go('menu');"),
        ("ipad_landscape_home", 1180, 820, "light", seed + "ZhuyinBoard.go('home');"),
        ("ipad_portrait_cand_dark", 820, 1180, "dark", seed + "ZhuyinBoard.state.comp.ini='ㄅ'; ZhuyinBoard.state.comp.fin='ㄚ'; ZhuyinBoard.state.tone='ˋ'; ZhuyinBoard.go('cand');"),
    ]
    out = []
    for name, w, h, scheme, setup in plan:
        ctx = await browser.new_context(viewport={"width": w, "height": h}, color_scheme=scheme, service_workers="block")
        await ctx.add_init_script(MOCK)
        p = await ctx.new_page()
        errs = []
        p.on("pageerror", lambda e: errs.append(str(e)))
        await p.goto(url)
        await p.evaluate("document.fonts.ready")
        await p.evaluate(setup)
        await p.wait_for_timeout(300)
        path = SHOTS / f"{name}.png"
        await p.screenshot(path=str(path))
        over = await p.evaluate("document.documentElement.scrollWidth > document.documentElement.clientWidth || document.documentElement.scrollHeight > document.documentElement.clientHeight")
        check(f"screenshot {name}: no page errors, no overflow", not errs and not over, (errs[:2], over))
        out.append(path)
        await ctx.close()
    try:
        from PIL import Image
        ims = [Image.open(p) for p in out]
        ims = [im.resize((im.width // 2, im.height // 2)) for im in ims]
        top = ims[:3]
        W = max(sum(i.width for i in top) + 40, ims[3].width + ims[4].width + 30)
        H = max(i.height for i in top) + max(ims[3].height, ims[4].height) + 30
        canvas = Image.new("RGB", (W, H), (128, 128, 128))
        x = 10
        for im in top:
            canvas.paste(im, (x, 10)); x += im.width + 10
        y = max(i.height for i in top) + 20
        canvas.paste(ims[3], (10, y)); canvas.paste(ims[4], (20 + ims[3].width, y))
        canvas.save(SHOTS / "montage.png")
    except ImportError:
        pass


async def main():
    httpd, url = serve()
    try:
        async with async_playwright() as pw:
            kw = {"executable_path": os.environ["CHROME_PATH"]} if os.environ.get("CHROME_PATH") else {}
            browser = await pw.chromium.launch(**kw)
            ctx = await browser.new_context(viewport={"width": 1180, "height": 820}, service_workers="block")
            await ctx.add_init_script(MOCK)
            page = await ctx.new_page()
            errs = []
            page.on("pageerror", lambda e: errs.append(str(e)))
            try:
                await functional(page, url)
            except Exception as e:  # 讓後面的檢查照樣跑
                check("functional run finished", False, repr(e))
            check("no page errors during the run", not errs, errs[:3])
            await ctx.close()
            await offline(browser, url)
            await shots(browser, url)
            await browser.close()
    finally:
        httpd.shutdown()
    fails = [r for r in results if not r[1]]
    for name, ok, detail in results:
        print(("PASS " if ok else "FAIL ") + name + ("" if ok else f"  -> {detail}"))
    print(f"\n{len(results) - len(fails)}/{len(results)} passed")
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    asyncio.run(main())
