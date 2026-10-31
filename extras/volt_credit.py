"""
VOLT – Datei für JEDEN VOLT-Bot
===============================
EINBAUEN: Datei neben die bot.py legen und direkt nach dem Erstellen des Bots:

    from volt_credit import volt_start
    bot = commands.Bot(...)          # (oder discord.Client(...)) – gibt es schon
    volt_start(bot)                  # <- neu

Was dann passiert:
  1) VOLT-Werbung im Bot-Status: Der Bot zeigt abwechselnd seinen eigenen Status
     (z. B. "Schaut ximtyron auf Twitch" oder LIVE) und "⚡ VoltStudio.work".
     Hat der Bot keinen eigenen Status, steht dort dauerhaft "⚡ VoltStudio.work".
     Ausschalten: volt_start(bot, werbung=False)
  2) Optional (nur wenn die Railway-Variable VOLT_STATUS_KEY gesetzt ist):
     Der Bot meldet jede Minute privat an VOLT ADMIN, dass er läuft.
     Gesendet werden nur Bot-ID, Bot-Name, Anzahl Server, Ping und Laufzeit.

Es ist egal, ob volt_start oben in der Datei, im setup_hook oder im on_ready steht.
Mehrfaches Aufrufen startet nichts doppelt.

OPTIONAL: VOLT-Werbung
----------------------
    from volt_credit import volt_footer, volt_presence, add_volt_command
    embed = volt_footer(embed)                 # Fußzeile "⚡ made by VOLT · VoltStudio.work"
    await volt_presence(bot)                   # im on_ready: Bot-Status "⚡ VoltStudio.work"
    add_volt_command(bot.tree)                 # vor bot.tree.sync(): Befehl /volt
Den Text für „Über mich“ im Developer Portal findest du unten in VOLT_ABOUT.
"""
import asyncio
import math
import os
import platform
import time

import aiohttp
import discord
from discord import app_commands

VOLT_URL = "https://voltstudio.work"
VOLT_LABEL = "VoltStudio.work"
VOLT_INVITE = "https://discord.gg/RpUtNGT6uj"
VOLT_FOOTER = f"⚡ made by VOLT · {VOLT_LABEL}"
VOLT_COLOR = 0xFF1F2A
VOLT_STATUS_URL = os.environ.get("VOLT_STATUS_URL", f"{VOLT_URL}/api/heartbeat")
VOLT_STATUS_VERSION = "1.2"
VOLT_AD_TEXT = f"⚡ {VOLT_LABEL}"
VOLT_AD_SECONDS = 20      # so lange steht die VOLT-Werbung im Status ...
VOLT_OWN_SECONDS = 40     # ... und so lange der eigene Status des Bots (z. B. Twitch)

# Für das Feld „Über mich“ (Description) im Developer Portal, max. 400 Zeichen
VOLT_ABOUT = (
    "⚡ Gebaut von VOLT – kostenlose Familien-Dashboards, Fussball-Manager und Routen-Systeme mit eigenem Discord-Bot.\n"
    f"🌐 {VOLT_LABEL}\n"
    f"💬 {VOLT_INVITE.replace('https://', '')}"
)


# =====================================================================
# 1) STATUS AN VOLTSTUDIO.WORK
# =====================================================================
def volt_start(bot: discord.Client, key: str = None, *, interval: int = 60, werbung: bool = True):
    """Startet VOLT-Werbung im Bot-Status und (mit VOLT_STATUS_KEY) die private Statusmeldung."""
    if werbung:
        _install_presence_hook(bot)
    key = (key or os.environ.get("VOLT_STATUS_KEY", "")).strip()
    interval = max(30, int(interval))
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        # Aufruf oben in der Datei (noch kein Event-Loop): Start beim Login nachholen.
        # login() wird von bot.run()/bot.start() immer aufgerufen, auch wenn der Bot
        # später einen eigenen setup_hook oder on_ready bekommt.
        if getattr(bot, "_volt_hooked", False):
            return None
        bot._volt_hooked = True
        original_login = bot.login

        async def _login(*args, **kwargs):
            volt_start(bot, key, interval=interval, werbung=werbung)
            return await original_login(*args, **kwargs)
        bot.login = _login
        return None
    if werbung:
        ptask = getattr(bot, "_volt_presence_task", None)
        if ptask is None or ptask.done():
            bot._volt_presence_task = loop.create_task(_volt_presence_loop(bot))
    if not key:
        return getattr(bot, "_volt_presence_task", None)
    task = getattr(bot, "_volt_status_task", None)
    if task is not None and not task.done():
        return task
    bot._volt_status_task = loop.create_task(_volt_loop(bot, key, interval))
    return bot._volt_status_task


# ---------------------------------------------------------------------
# VOLT-Werbung im Bot-Status (wechselt mit dem eigenen Status des Bots)
# ---------------------------------------------------------------------
def _ad_activity():
    if hasattr(discord, "CustomActivity") and discord.version_info >= (2, 3):
        return discord.CustomActivity(name=VOLT_AD_TEXT)
    return discord.Game(name=VOLT_LABEL)


def _install_presence_hook(bot):
    """Merkt sich jeden Status, den der Bot selbst setzt (z. B. Twitch LIVE), damit er nicht verloren geht."""
    if getattr(bot, "_volt_orig_presence", None) is not None:
        return
    original = bot.change_presence
    bot._volt_orig_presence = original
    bot._volt_own = {"activity": getattr(bot, "activity", None), "status": None}

    async def change_presence(*, activity=None, status=None, **kwargs):
        bot._volt_own = {"activity": activity, "status": status}
        return await original(activity=activity, status=status, **kwargs)
    bot.change_presence = change_presence


async def _volt_presence_loop(bot):
    await bot.wait_until_ready()
    await asyncio.sleep(8)  # eigener Status des Bots (on_ready) zuerst
    showing_ad = False
    while not bot.is_closed():
        own = getattr(bot, "_volt_own", {}) or {}
        has_own = own.get("activity") is not None
        try:
            if not has_own:
                if not showing_ad:  # kein eigener Status: Werbung einmal setzen und stehen lassen
                    await bot._volt_orig_presence(activity=_ad_activity(), status=own.get("status"))
                    showing_ad = True
                await asyncio.sleep(VOLT_OWN_SECONDS)
                continue
            if showing_ad:
                await bot._volt_orig_presence(activity=own["activity"], status=own.get("status"))
                showing_ad = False
                await asyncio.sleep(VOLT_OWN_SECONDS)
            else:
                await bot._volt_orig_presence(activity=_ad_activity(), status=own.get("status"))
                showing_ad = True
                await asyncio.sleep(VOLT_AD_SECONDS)
        except asyncio.CancelledError:
            raise
        except Exception:
            await asyncio.sleep(VOLT_OWN_SECONDS)


def _ping_ms(bot):
    lat = getattr(bot, "latency", None)
    if lat is None or not isinstance(lat, (int, float)) or math.isnan(lat) or math.isinf(lat):
        return None
    return int(lat * 1000)


async def _volt_loop(bot: discord.Client, key: str, interval: int):
    started = time.time()
    await bot.wait_until_ready()
    last_msg = None

    def say(code, text):
        nonlocal last_msg
        if last_msg != code:          # jede Meldung nur einmal ins Log, kein Spam
            print(text)
            last_msg = code

    headers = {"Authorization": f"Bearer {key}", "User-Agent": f"VOLT-Status/{VOLT_STATUS_VERSION}"}
    timeout = aiohttp.ClientTimeout(total=15)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        while not bot.is_closed():
            ping = _ping_ms(bot)
            payload = {
                "v": VOLT_STATUS_VERSION,
                "bot_id": str(bot.user.id) if bot.user else None,
                "bot_name": str(bot.user) if bot.user else None,
                "guilds": len(bot.guilds),
                "ping_ms": ping,
                "uptime_s": int(time.time() - started),
                "discord_ok": bool(bot.is_ready() and ping is not None),
                "python": platform.python_version(),
                "discord_py": discord.__version__,
            }
            try:
                async with session.post(VOLT_STATUS_URL, json=payload, headers=headers) as r:
                    if r.status == 200:
                        data = await r.json(content_type=None)
                        say("ok", f"[VOLT] Status aktiv: {data.get('name', 'Bot')} meldet sich jede Minute bei {VOLT_LABEL}")
                        interval = max(30, int(data.get("interval") or interval))
                    elif r.status == 401:
                        say("401", "[VOLT] Status abgelehnt: VOLT_STATUS_KEY ist falsch oder wurde gelöscht. "
                                   "Neuen Schlüssel mit /bots neuer-schlüssel holen.")
                    elif r.status == 403:
                        say("403", "[VOLT] Status blockiert (HTTP 403). In Cloudflare unter Security → Bots "
                                   "den Bot Fight Mode ausschalten.")
                    else:
                        say(f"http{r.status}", f"[VOLT] Website antwortet mit HTTP {r.status}, versuche es weiter …")
            except asyncio.CancelledError:
                raise
            except Exception as ex:  # Website kurz weg (z. B. Neustart): einfach weiter versuchen
                say("down", f"[VOLT] {VOLT_LABEL} gerade nicht erreichbar ({type(ex).__name__}), versuche es weiter …")
            await asyncio.sleep(interval)


# =====================================================================
# 2) VOLT-WERBUNG (optional)
# =====================================================================
def volt_footer(embed: discord.Embed, prefix: str = None) -> discord.Embed:
    """Setzt die VOLT-Fußzeile. Mit prefix z. B. 'Familie Volt • ⚡ made by VOLT · VoltStudio.work'."""
    embed.set_footer(text=f"{prefix} • {VOLT_FOOTER}" if prefix else VOLT_FOOTER)
    return embed


def volt_view() -> discord.ui.View:
    v = discord.ui.View(timeout=None)
    v.add_item(discord.ui.Button(label="Website", emoji="🌐", style=discord.ButtonStyle.link, url=VOLT_URL))
    v.add_item(discord.ui.Button(label="VOLT-Discord", emoji="💬", style=discord.ButtonStyle.link, url=VOLT_INVITE))
    return v


async def volt_presence(bot: discord.Client):
    """Bot-Status: ⚡ VoltStudio.work"""
    try:
        await bot.change_presence(activity=discord.CustomActivity(name=f"⚡ {VOLT_LABEL}"))
    except discord.HTTPException:
        pass


def add_volt_command(tree: app_commands.CommandTree):
    """Fügt /volt hinzu: kurze Info, wer den Bot gebaut hat, mit Website- und Discord-Button."""
    @tree.command(name="volt", description="Wer hat diesen Bot gebaut?")
    async def volt_cmd(interaction: discord.Interaction):
        e = discord.Embed(
            title="⚡ Dieser Bot wurde von VOLT gebaut",
            description=("Kostenlose Familien-Dashboards, Fussball-Manager und Routen-Systeme mit eigenem "
                         "Discord-Bot. Gebaut und betreut von einer Person, Made in Germany.\n\n"
                         f"🌐 **{VOLT_LABEL}**"),
            color=VOLT_COLOR)
        volt_footer(e)
        await interaction.response.send_message(embed=e, view=volt_view(), ephemeral=True)
    return volt_cmd
