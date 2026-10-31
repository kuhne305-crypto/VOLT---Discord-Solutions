"""
VOLT – Datei für JEDEN VOLT-Bot
===============================
Macht zwei Dinge:
  1) Status an VoltStudio.work melden (Bot erscheint auf der Website und im Uptime-Kanal)
  2) VOLT-Werbung: Fußzeile, Bot-Status, /volt-Befehl (alles freiwillig)

EINBAUEN (3 Schritte)
---------------------
1. Diese Datei neben die bot.py des Bots legen.

2. In Railway beim Bot die Variable anlegen:
       VOLT_STATUS_KEY = <Schlüssel>
   Den Schlüssel bekommst du im VOLT-Discord mit:  /bots hinzufügen

3. In der bot.py EINE Zeile ergänzen, direkt nachdem der Bot erstellt wurde:

       from volt_credit import volt_start
       bot = commands.Bot(...)          # (oder discord.Client(...)) – gibt es schon
       volt_start(bot)                  # <- neu

   Fertig. Nach dem Neustart steht im Railway-Log:
       [VOLT] Status aktiv: <Name> meldet sich jede Minute bei VoltStudio.work

Es ist egal, ob volt_start oben in der Datei, im setup_hook oder im on_ready steht.
Mehrfaches Aufrufen startet keine zweite Meldung.
Gesendet werden nur: Bot-ID und Bot-Name, Anzahl Server, Ping, Laufzeit.
Keine Nachrichten, keine Mitglieder, keine Tokens.

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
VOLT_STATUS_VERSION = "1.1"

# Für das Feld „Über mich“ (Description) im Developer Portal, max. 400 Zeichen
VOLT_ABOUT = (
    "⚡ Gebaut von VOLT – kostenlose Familien-Dashboards, Fussball-Manager und Routen-Systeme mit eigenem Discord-Bot.\n"
    f"🌐 {VOLT_LABEL}\n"
    f"💬 {VOLT_INVITE.replace('https://', '')}"
)


# =====================================================================
# 1) STATUS AN VOLTSTUDIO.WORK
# =====================================================================
def volt_start(bot: discord.Client, key: str = None, *, interval: int = 60):
    """Startet die Statusmeldung. Den Schlüssel liest die Funktion aus VOLT_STATUS_KEY (Railway-Variable)."""
    key = (key or os.environ.get("VOLT_STATUS_KEY", "")).strip()
    if not key:
        print("[VOLT] Status AUS: Railway-Variable VOLT_STATUS_KEY fehlt. "
              "Schlüssel bekommst du im VOLT-Discord mit /bots hinzufügen.")
        return None
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
            volt_start(bot, key, interval=interval)
            return await original_login(*args, **kwargs)
        bot.login = _login
        return None
    task = getattr(bot, "_volt_status_task", None)
    if task is not None and not task.done():
        return task
    bot._volt_status_task = loop.create_task(_volt_loop(bot, key, interval))
    return bot._volt_status_task


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
