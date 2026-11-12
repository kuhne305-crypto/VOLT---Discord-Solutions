"""Baut das VOLT-Icon-Set:
  web/assets/icons/volt-icons.svg      Sprite für Websites/Dashboards  (<use href="…#vi-regeln">)
  web/assets/icons/svg/<name>.svg      Einzel-SVGs (Ivory/Amber)
  web/assets/icons/discord/v_<name>.png 128×128 Kacheln für Discord-Emojis und Rollen-Icons
  web/assets/icons/icons.json          Liste mit Gruppe, Name und Reihenfolge für Discord

Aufruf (braucht Playwright, läuft nur beim Entwickeln):  python3 extras/icons/build.py
"""
import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from icons import COLORS, DISCORD_ORDER, ICONS, body  # noqa: E402

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
OUT = os.path.join(ROOT, "web", "assets", "icons")
TILE_BG = "#1c1d20"


def sprite() -> str:
    syms = "".join(f'<symbol id="vi-{k}" viewBox="0 0 24 24">{body(k)}</symbol>' for k in ICONS)
    return f'<svg xmlns="http://www.w3.org/2000/svg" style="display:none">{syms}</svg>\n'


def single(k) -> str:
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" width="96" height="96" '
            f'color="{COLORS["main"]}">{body(k)}</svg>\n')


def tile(k, px=128) -> str:
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" width="{px}" height="{px}">'
            f'<path d="M0 0H19L24 5V24H0Z" fill="{TILE_BG}"/>'
            f'<path d="M19 0L24 5" stroke="{COLORS["accent"]}" stroke-width=".9"/>'
            f'<g transform="translate(3.3 3.3) scale(.725)" color="{COLORS["main"]}">{body(k, sw=2.7)}</g></svg>')


async def render_pngs():
    from playwright.async_api import async_playwright
    os.makedirs(os.path.join(OUT, "discord"), exist_ok=True)
    html = "<!doctype html><html><body style='margin:0;background:transparent'>" + "".join(
        f"<div id='t-{k}' style='width:128px;height:128px;display:inline-block'>{tile(k)}</div>" for k in ICONS) + "</body></html>"
    async with async_playwright() as p:
        br = await p.chromium.launch()
        pg = await br.new_page(viewport={"width": 1280, "height": 900}, device_scale_factor=1)
        await pg.set_content(html)
        for k in ICONS:
            await pg.locator(f"#t-{k}").screenshot(path=os.path.join(OUT, "discord", f"v_{k}.png"), omit_background=True)
        await br.close()


def main():
    os.makedirs(os.path.join(OUT, "svg"), exist_ok=True)
    with open(os.path.join(OUT, "volt-icons.svg"), "w", encoding="utf-8") as f:
        f.write(sprite())
    for k in ICONS:
        with open(os.path.join(OUT, "svg", f"{k}.svg"), "w", encoding="utf-8") as f:
            f.write(single(k))
    meta = {"order": DISCORD_ORDER,
            "icons": {k: {"group": v["group"], "label": v["label"]} for k, v in ICONS.items()}}
    with open(os.path.join(OUT, "icons.json"), "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=1)
    asyncio.run(render_pngs())
    print(f"{len(ICONS)} Icons gebaut → {OUT}")


if __name__ == "__main__":
    main()
