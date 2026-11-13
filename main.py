"""
VOLT - Discord Solutions | All-in-One Bot
Setup, Verify, Tickets (Produkt-Auswahl + Bestätigung), Sicherheit, Warns,
Blacklist, Bewertungen, FAQ, Logs, Willkommenskarten, Arbeitsstatus,
Uptime-Monitor + Website (läuft im selben Railway-Service).
"""
import os
import io
import re
import math
import time
import asyncio
import json
import random
import hashlib
import hmac
import secrets
import mimetypes
import unicodedata
import datetime as dt
from collections import defaultdict, deque

import aiohttp
import aiosqlite
import discord
from aiohttp import web
from discord import app_commands
from discord.ext import commands, tasks

# ===============================================================
# KONFIG (Railway-Variablen)
# ===============================================================
TOKEN = os.environ["DISCORD_TOKEN"]
OWNER_ID = int(os.environ["OWNER_ID"])
GUILD_ID = int(os.environ["GUILD_ID"]) if os.environ.get("GUILD_ID") else None
# Datenbank liegt auf dem Railway-Volume (SQLite). Railway setzt den Pfad automatisch.
VOLUME_PATH = os.environ.get("RAILWAY_VOLUME_MOUNT_PATH", "")
if VOLUME_PATH:
    os.makedirs(VOLUME_PATH, exist_ok=True)
    DB_PATH = os.path.join(VOLUME_PATH, "volt.db")
else:
    DB_PATH = "volt.db"
    print("WARNUNG: Kein Volume erkannt, Daten gehen bei Neustart verloren!")
_backup = None  # VOLT Backups (siehe volt_backup.py)
DONATION_URL = os.environ.get("DONATION_URL", "")  # leer lassen: Spenden werden auf Discord geklärt

# Website (Railway setzt PORT automatisch)
SITE_ENABLED = os.environ.get("SITE_ENABLED", "1") != "0"
SITE_PORT = int(os.environ.get("PORT", "8080"))
MAX_PARALLEL = max(1, int(os.environ.get("MAX_PARALLEL", "2")))            # Projekte gleichzeitig
PROJECTS_PER_DAY = max(0.1, float(os.environ.get("PROJECTS_PER_DAY", "1")))  # normales Tempo
DISCORD_INVITE_URL = os.environ.get("DISCORD_INVITE_URL", "https://discord.gg/RpUtNGT6uj")
SITE_URL = os.environ.get("SITE_URL", "https://voltstudio.work").rstrip("/")
SITE_LABEL = "VoltStudio.work"
SITE_HOST = SITE_URL.split("://", 1)[-1].split("/", 1)[0]
MONITOR_INTERVAL = max(30, int(os.environ.get("MONITOR_INTERVAL", "60")))  # Sekunden zwischen zwei Uptime-Checks
# "VOLT System" = Zustand der Server-Plattform in der eigenen Region (Compute, Netzwerk, Speicher).
VOLT_SYSTEM_URL = os.environ.get("VOLT_SYSTEM_URL", "https://api.railwaystatus.com/status")
VOLT_SYSTEM_REGION = os.environ.get("VOLT_SYSTEM_REGION", "US West")
VOLT_SYSTEM_PARTS = ("Compute", "Networking — Public", "Networking — Private", "Storage")
# Optional: Schlüssel für die Verwaltung per HTTP (Bots anlegen, Dienste überwachen). Leer = aus.
ADMIN_API_KEY = os.environ.get("VOLT_ADMIN_KEY", "").strip()
# Wird diese Nummer erhöht, postet der Bot nach dem nächsten Start einmal alle Panels neu (wie /panels).
PANELS_VERSION = "2026-11-13b"

MIN_ACCOUNT_AGE_DAYS = int(os.environ.get("MIN_ACCOUNT_AGE_DAYS", "3"))  # 0 = aus
RAID_JOINS = int(os.environ.get("RAID_JOINS", "6"))      # so viele Joins ...
RAID_WINDOW = int(os.environ.get("RAID_WINDOW", "15"))   # ... in so vielen Sekunden
RAID_LOCKDOWN = 120                                      # Sekunden Kick-Modus nach Raid
NUKE_LIMIT = 3                                           # Loeschungen/Bans ...
NUKE_WINDOW = 30                                         # ... in Sekunden
MAX_OPEN_TICKETS = 2
SUPPORT_SEES_TICKETS = False

BRAND = "VOLT • Discord Solutions • VoltStudio.work"
BRAND_COLOR = 0xFFB83F   # VOLT Electric Amber
C_ONLINE, C_WARTUNG, C_STOERUNG = 0x23A55A, 0xFF7A45, 0xFF4D5E

intents = discord.Intents.default()
intents.members = True
intents.message_content = True

# max_messages: mehr Nachrichten im Speicher = bei Bearbeiten/Löschen ist der alte Text im Mod-Log bekannt
bot = commands.Bot(command_prefix="!", intents=intents, max_messages=10000)
pool = None  # DB-Objekt, wird im setup_hook gesetzt


# ===============================================================
# ROLLEN
# ===============================================================
# Rollenfarben im VOLT-Look: vom Amber (Owner) über Bronze bis zu den neutralen Tönen
ROLES = [
    ("owner", "👑 Owner", 0xFFB83F, discord.Permissions(administrator=True), True),
    ("admin", "🎖️ Admin", 0xD99A35, discord.Permissions(administrator=True), True),
    ("support", "🎧 Support", 0xC29A5B, discord.Permissions(
        manage_messages=True, moderate_members=True, kick_members=True), True),
    ("kunde", "💼 Kunde", 0xF2EFE8, discord.Permissions.none(), True),
    ("user", "👤 User", 0xB8B2A6, discord.Permissions.none(), False),
    ("bots", "🤖 Bots", 0x92734B, discord.Permissions.none(), False),
    ("unverified", "❔ Unverifiziert", 0x6B6862, discord.Permissions.none(), False),
]
# Icon aus dem VOLT-Icon-Set pro Rolle (Rollen-Icons gehen erst ab Server-Boost Stufe 2)
ROLE_ICON = {"owner": "owner", "admin": "admin", "support": "support", "kunde": "kunde",
             "user": "user", "bots": "bot", "unverified": "unverifiziert"}
ROLE_NAMES = {k: n for k, n, *_ in ROLES}
# Frühere Namen (vor dem VOLT-Design): so werden bestehende Rollen weiter gefunden und umbenannt
ROLE_OLD_NAMES = {"admin": ["🛡️ Admin"], "support": ["🔧 Support"], "user": ["✅ User"],
                  "unverified": ["⛔ Unverifiziert"]}


def role_names(*keys) -> set:
    return {n for k in keys for n in [ROLE_NAMES[k], *ROLE_OLD_NAMES.get(k, [])]}
ROLE_CACHE: dict[int, dict[str, discord.Role]] = {}


def find_role(guild: discord.Guild, key: str):
    cached = ROLE_CACHE.get(guild.id, {}).get(key)
    if cached and guild.get_role(cached.id):
        return cached
    for name in [ROLE_NAMES[key], *ROLE_OLD_NAMES.get(key, [])]:
        role = discord.utils.get(guild.roles, name=name)
        if role:
            return role
    return None


def has_team_role(member: discord.Member) -> bool:
    if member.id == OWNER_ID or member.id == member.guild.owner_id:
        return True
    names = role_names("owner", "admin", "support")
    return any(r.name in names for r in member.roles)


def can_moderate(actor: discord.Member, target: discord.Member) -> bool:
    if target.bot or target.id == OWNER_ID or target.id == actor.guild.owner_id:
        return False
    if actor.id == OWNER_ID:
        return True
    return not has_team_role(target)


# ===============================================================
# RECHTE
# ===============================================================
def build_overwrites(guild: discord.Guild, mode: str):
    everyone = guild.default_role
    owner, admin = find_role(guild, "owner"), find_role(guild, "admin")
    support, user = find_role(guild, "support"), find_role(guild, "user")

    see = discord.PermissionOverwrite(view_channel=True, read_message_history=True)
    see_write = discord.PermissionOverwrite(
        view_channel=True, read_message_history=True, send_messages=True)
    hidden = discord.PermissionOverwrite(view_channel=False)
    bot_full = discord.PermissionOverwrite(
        view_channel=True, send_messages=True, manage_channels=True,
        manage_messages=True, read_message_history=True,
        embed_links=True, attach_files=True, connect=True)

    ow = {guild.me: bot_full}

    if mode == "info":
        ow[everyone] = discord.PermissionOverwrite(view_channel=True, connect=False)
    elif mode == "honeypot":  # jeder sieht UND darf schreiben (Falle fuer gehackte Accounts)
        ow[everyone] = discord.PermissionOverwrite(
            view_channel=True, read_message_history=True, send_messages=True)
    elif mode == "public":
        ow[everyone] = discord.PermissionOverwrite(
            view_channel=True, read_message_history=True, send_messages=False)
    elif mode == "verified":
        ow[everyone] = hidden
        if user:
            ow[user] = discord.PermissionOverwrite(
                view_channel=True, read_message_history=True, send_messages=False)
    elif mode == "team":
        ow[everyone] = hidden
        for r in (owner, admin, support):
            if r:
                ow[r] = see_write
    elif mode == "ticket":
        ow[everyone] = hidden
        for r in (owner, admin):
            if r:
                ow[r] = see_write
        if SUPPORT_SEES_TICKETS and support:
            ow[support] = see_write
    elif mode == "admin":
        ow[everyone] = hidden
        for r in (owner, admin):
            if r:
                ow[r] = see
    return ow


def ticket_overwrites(guild: discord.Guild, creator: discord.Member):
    """Ticket-Channel: NUR Ersteller + Owner/Admin + Bot."""
    ow = build_overwrites(guild, "ticket")
    ow[creator] = discord.PermissionOverwrite(
        view_channel=True, read_message_history=True, send_messages=True,
        attach_files=True, embed_links=True,
        manage_channels=False, manage_messages=False)
    return ow


# ===============================================================
# SERVER-STRUKTUR
# ===============================================================
SEP = "・"   # Trenner zwischen Emoji und Kanalname (VOLT-Design, vorher „│“)
STRUCTURE = [
    ("／ SERVERINFO", "info", [
        ("👥 Mitglieder: 0", "voice"),
        ("🟢 Status: Online", "voice"),
        ("⭐ Bewertungen: bald verfügbar", "voice"),
    ]),
    ("／ WILLKOMMEN", "public", [
        (f"📄{SEP}regeln", "text"),
        (f"👋{SEP}willkommen", "text"),
        (f"✅{SEP}verify", "text"),
        (f"⛔{SEP}nicht-schreiben", "text", "honeypot"),
    ]),
    ("／ INFOS", "verified", [
        (f"📢{SEP}ankündigungen", "text"),
        (f"📊{SEP}server-status", "text"),
        (f"📶{SEP}uptime", "text"),
        (f"🌐{SEP}website", "text"),
        (f"⭐{SEP}bewertungen", "text"),
        (f"❔{SEP}faq", "text"),
        (f"🖼️{SEP}portfolio", "text"),
    ]),
    ("／ SHOP", "verified", [
        (f"📦{SEP}produkte", "text"),
        (f"🛒{SEP}bestellen", "text"),
    ]),
    ("🟡 OFFENE TICKETS", "ticket", []),
    ("🔵 IN BEARBEITUNG", "ticket", []),
    ("🟢 LAUFENDE PROJEKTE", "ticket", []),
    ("🟠 WARTUNG", "ticket", []),
    ("🗃️ ARCHIV", "ticket", []),
    ("／ TEAM-INTERN", "team", [
        (f"💬{SEP}team-chat", "text"),
        (f"📋{SEP}aufgaben", "text"),
    ]),
    ("／ LOGS", "admin", [
        (f"🔒{SEP}admin-logs", "text"),
        (f"🎫{SEP}ticket-logs", "text"),
        (f"🛡️{SEP}mod-logs", "text"),
        (f"🚪{SEP}join-leave-logs", "text"),
    ]),
]
TICKET_CATEGORY_KEYS = ("OFFENE TICKETS", "WARTELISTE", "IN BEARBEITUNG", "LAUFENDE PROJEKTE", "WARTUNG", "ARCHIV")


def find_channel(guild: discord.Guild, key: str, kind=discord.TextChannel):
    for ch in guild.channels:
        if isinstance(ch, kind) and key in ch.name:
            return ch
    return None


def find_category(guild: discord.Guild, key: str):
    for c in guild.categories:
        if key in c.name:
            return c
    return None


def emb(title: str, desc: str = "", color: int = BRAND_COLOR) -> discord.Embed:
    e = discord.Embed(title=title, description=desc, color=color,
                      timestamp=discord.utils.utcnow())
    e.set_footer(text=BRAND)
    return e


async def log(guild: discord.Guild, key: str, embed: discord.Embed, file=None):
    ch = find_channel(guild, key)
    if ch:
        try:
            await ch.send(embed=embed, file=file) if file else await ch.send(embed=embed)
        except discord.HTTPException:
            pass


# ===============================================================
# PRODUKTE (Discord-Panels, Bestellung und Website nutzen dieselbe Liste)
# ===============================================================
PRODUCTS = [
    {"key": "familien-dashboard", "emoji": "👪", "name": "Familien-Dashboard", "tag": "All-in-One",
     "label": "👪 Familien-Dashboard (All-in-One)",
     "short": "Mitglieder, Termine, Kasse, Lager und Sanktionen in einem Dashboard, mit eigenem Discord-Bot.",
     "points": ["14 Systeme in einem Dashboard, 61 Bot-Befehle",
                "Termine & Aufstellung mit Komme · Später · Komme nicht",
                "Kasse, Wochenabgaben und Lager mit Leihgabe",
                "Sanktionen mit Erinnerung per DM, eigene Log-Channels"],
     "demo": "Vorschau, Sneak Peek und klickbare Demo"},
    {"key": "fussball-manager", "emoji": "⚽", "name": "Fussball-Manager", "tag": "Dashboard + Bot",
     "label": "⚽ Fussball-Manager",
     "short": "Spiele planen, Zusagen über Discord, The Stage per Drag & Drop und Ergebnisse mit Bildbeweis.",
     "points": ["Login nur per Discord, Zugriff nur für eure Rollen",
                "Spiele mit max. 25 Teilnehmern, Zusagen per Button",
                "The Stage (Main & Classic) per Drag & Drop",
                "Felder-Übersicht und Ergebnisse mit Bildbeweis"],
     "demo": "Vorschau zum Durchklicken"},
    {"key": "routen-system", "emoji": "🗺️", "name": "Routen Manager", "tag": "Bot + Dashboard",
     "label": "🗺️ Routen Manager",
     "short": "Familien, Kontrollen & Wachen, Arbeiter, Sanktionen, Blacklist und Routen-Sync in einem System.",
     "points": ["Familienrolle per Passwort, mit Kürzel und Ablaufdatum",
                "Kontrollen & Wachen mit Level und Wochenranking",
                "Zentraler Sanktionskatalog, Blacklist mit Vorfällen",
                "Routen-Sync: Blood-Outs des Routen-Besitzers automatisch übernehmen"],
     "demo": "Vorschau zum Durchklicken"},
]
CUSTOM_REQUEST = "💡 Individuelle Anfrage"
PROJECT_TYPES = [p["label"] for p in PRODUCTS] + [CUSTOM_REQUEST]


def product_url(key: str) -> str:
    return f"{SITE_URL}/{key}"


def product_by_label(label: str):
    return next((p for p in PRODUCTS if p["label"] == label), None)


def channel_url(guild: discord.Guild, ch) -> str:
    return f"https://discord.com/channels/{guild.id}/{ch.id}" if ch else SITE_URL


def volt_link_view() -> discord.ui.View:
    """Buttons zu Website und Produkten, z. B. für /volt und den Website-Kanal."""
    v = discord.ui.View(timeout=None)
    v.add_item(discord.ui.Button(label="Website", emoji="🌐", style=discord.ButtonStyle.link, url=SITE_URL))
    for p in PRODUCTS:
        v.add_item(discord.ui.Button(label=p["name"], emoji=p["emoji"], style=discord.ButtonStyle.link,
                                     url=product_url(p["key"])))
    return v


def donate_view():
    v = discord.ui.View(timeout=None)
    if DONATION_URL:
        v.add_item(discord.ui.Button(label="Freiwillig spenden", emoji="💛",
                                     style=discord.ButtonStyle.link, url=DONATION_URL))
    return v


# ===============================================================
# DATENBANK
# ===============================================================
SCHEMA = """
CREATE TABLE IF NOT EXISTS tickets (
  id INTEGER PRIMARY KEY AUTOINCREMENT, channel_id INTEGER UNIQUE, user_id INTEGER NOT NULL,
  project_type TEXT, project_name TEXT, slug TEXT, description TEXT,
  platform TEXT, link TEXT, budget TEXT,
  status TEXT NOT NULL DEFAULT 'open', price TEXT, offer_message_id INTEGER,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS warns (
  id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL, mod_id INTEGER, reason TEXT,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS blacklist (
  user_id INTEGER PRIMARY KEY, reason TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP,
  until INTEGER, mod_id INTEGER);
CREATE TABLE IF NOT EXISTS stats (
  key TEXT PRIMARY KEY, value INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS reviews (
  id INTEGER PRIMARY KEY AUTOINCREMENT, ticket_id INTEGER UNIQUE, user_id INTEGER, stars INTEGER,
  comment TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS dm_optout (
  user_id INTEGER PRIMARY KEY, created_at TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS work_sessions (
  id INTEGER PRIMARY KEY AUTOINCREMENT, ticket_id INTEGER NOT NULL,
  started_at REAL NOT NULL, ended_at REAL);
CREATE TABLE IF NOT EXISTS settings (
  key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS bots (
  id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT UNIQUE NOT NULL, product TEXT,
  key_hash TEXT UNIQUE NOT NULL, public INTEGER NOT NULL DEFAULT 1, created_at TEXT DEFAULT CURRENT_TIMESTAMP,
  first_seen REAL, last_seen REAL, online_s REAL NOT NULL DEFAULT 0, beats INTEGER NOT NULL DEFAULT 0,
  guilds INTEGER, ping INTEGER, uptime_s INTEGER, discord_ok INTEGER, bot_user TEXT);
"""


class DB:
    """Kleiner SQLite-Wrapper (Platzhalter $1, $2 ... wie bisher)."""

    def __init__(self, path: str):
        self.path = path
        self.conn = None

    async def connect(self):
        self.conn = await aiosqlite.connect(self.path)
        self.conn.row_factory = aiosqlite.Row
        await self.conn.executescript(SCHEMA)
        await self.conn.commit()

    @staticmethod
    def _q(q: str) -> str:
        return re.sub(r"\$(\d+)", r"?\1", q)

    async def execute(self, q, *args):
        await self.conn.execute(self._q(q), args)
        await self.conn.commit()

    async def fetch(self, q, *args):
        cur = await self.conn.execute(self._q(q), args)
        rows = await cur.fetchall()
        await cur.close()
        await self.conn.commit()
        return rows

    async def fetchrow(self, q, *args):
        cur = await self.conn.execute(self._q(q), args)
        row = await cur.fetchone()
        await cur.close()
        await self.conn.commit()
        return row

    async def fetchval(self, q, *args):
        row = await self.fetchrow(q, *args)
        return row[0] if row else None


async def get_ticket(channel_id: int):
    return await pool.fetchrow("SELECT * FROM tickets WHERE channel_id=$1", channel_id)


async def get_setting(key: str, default=None):
    """Einstellungen (Arbeitsstatus, Uptime-Monitor ...) als JSON in der Datenbank."""
    raw = await pool.fetchval("SELECT value FROM settings WHERE key=$1", key)
    if raw is None:
        return default
    try:
        return json.loads(raw)
    except ValueError:
        return default


async def set_setting(key: str, value):
    await pool.execute("INSERT INTO settings (key, value) VALUES ($1, $2) "
                       "ON CONFLICT (key) DO UPDATE SET value=excluded.value", key, json.dumps(value))


# ===============================================================
# DM-BENACHRICHTIGUNGEN
# Schreibt das Team (Owner, Admin, Support) im Ticket, bekommt der
# Ersteller eine DM mit Link. Pro Ticket höchstens alle DM_COOLDOWN
# Sekunden, außer der Kunde hat zwischendurch selbst geschrieben.
# ===============================================================
DM_COOLDOWN = int(os.environ.get("DM_COOLDOWN", "300"))
_dm_last: dict[int, float] = {}   # channel_id -> Zeit der letzten DM


def ticket_link_view(guild_id: int, channel_id: int) -> discord.ui.View:
    v = discord.ui.View(timeout=None)
    v.add_item(discord.ui.Button(label="Zum Ticket", emoji="🎫", style=discord.ButtonStyle.link,
                                 url=f"https://discord.com/channels/{guild_id}/{channel_id}"))
    return v


async def dm_allowed(user_id: int) -> bool:
    return not await pool.fetchval("SELECT 1 FROM dm_optout WHERE user_id=$1", user_id)


async def notify_ticket_owner(guild: discord.Guild, ticket, title: str, text: str, *,
                              force: bool = False, author: discord.Member = None) -> bool:
    """DM an den Ticket-Ersteller. force=True ignoriert den Cooldown, nie aber das Opt-out."""
    if not ticket or ticket["status"] == "deleted":
        return False
    now = time.time()
    if not force and now - _dm_last.get(ticket["channel_id"], 0) < DM_COOLDOWN:
        return False
    if not await dm_allowed(ticket["user_id"]):
        return False
    member = guild.get_member(ticket["user_id"])
    if member is None:
        return False
    e = emb(title, text)
    e.add_field(name="Ticket", value=f"#{ticket['id']} · {ticket['project_name']}", inline=False)
    if author:
        e.set_author(name=f"{author.display_name} · VOLT-Team", icon_url=author.display_avatar.url)
    e.set_footer(text=f"{BRAND} • Abschalten mit /dm-benachrichtigungen")
    try:
        await member.send(embed=e, view=ticket_link_view(guild.id, ticket["channel_id"]))
    except discord.HTTPException:  # DMs geschlossen
        return False
    _dm_last[ticket["channel_id"]] = now
    return True


# ===============================================================
# WERKBANK & ZEITERFASSUNG
# /platz 1|2 legt ein Ticket auf die Werkbank und startet die Uhr.
# /zeit pause|weiter steuert sie. Bei Läuft/Wartung/Archiv/Abgelehnt
# wird der Platz automatisch frei und die Uhr gestoppt.
# ===============================================================
async def timer_running(ticket_id: int) -> bool:
    return bool(await pool.fetchval(
        "SELECT 1 FROM work_sessions WHERE ticket_id=$1 AND ended_at IS NULL", ticket_id))


async def start_timer(ticket_id: int):
    if not await timer_running(ticket_id):
        await pool.execute("INSERT INTO work_sessions (ticket_id, started_at) VALUES ($1, $2)", ticket_id, time.time())


async def stop_timer(ticket_id: int):
    await pool.execute("UPDATE work_sessions SET ended_at=$1 WHERE ticket_id=$2 AND ended_at IS NULL",
                       time.time(), ticket_id)


async def work_seconds(ticket_id: int) -> float:
    v = await pool.fetchval(
        "SELECT sum(coalesce(ended_at, $1) - started_at) FROM work_sessions WHERE ticket_id=$2", time.time(), ticket_id)
    return float(v or 0)


def fmt_dur(sec) -> str:
    sec = int(sec or 0)
    h, m = sec // 3600, (sec % 3600) // 60
    if h:
        return f"{h} Std {m:02d} Min"
    return f"{m} Min" if m else "unter 1 Min"


async def free_slot(ticket_id: int):
    await stop_timer(ticket_id)
    await pool.execute("UPDATE tickets SET slot=NULL WHERE id=$1", ticket_id)
    invalidate_site_cache()


async def has_review(ticket_id: int) -> bool:
    return bool(await pool.fetchval("SELECT 1 FROM reviews WHERE ticket_id=$1", ticket_id))


async def request_review(guild: discord.Guild, channel, ticket, *, dm: bool = True, by=None) -> bool:
    """Bittet den Kunden im Ticket (und per DM) um eine Bewertung, falls noch keine da ist."""
    if await has_review(ticket["id"]):
        return False
    member = guild.get_member(ticket["user_id"])
    await channel.send(
        content=member.mention if member else None,
        embed=emb("⭐ Wie zufrieden bist du?",
                  f"**{ticket['project_name']}** läuft! Wenn alles passt, freue ich mich über eine kurze Bewertung "
                  f"mit 1 bis 5 Sternen. Sie erscheint in #bewertungen und auf der Website.\n\n"
                  f"Spenden sind freiwillig. 💛"),
        view=ReviewView())
    if DONATION_URL:
        await channel.send(view=donate_view())
    if dm:
        await notify_ticket_owner(guild, ticket, "⭐ Bewerte dein Projekt",
                                  f"**{ticket['project_name']}** läuft! Wenn du zufrieden bist, kannst du es jetzt "
                                  f"im Ticket mit 1 bis 5 Sternen bewerten.", force=True, author=by)
    return True


# ===============================================================
# TICKET-STATUS
# ===============================================================
STATUS = {
    "open":        ("🟡", "OFFENE TICKETS", "Offen"),
    "offered":     ("🟡", "OFFENE TICKETS", "Angebot gesendet"),
    "waiting":     ("🕓", "WARTELISTE", "Warteliste (anderer Server)"),
    "progress":    ("🔵", "IN BEARBEITUNG", "Angenommen / in Bearbeitung"),
    "running":     ("🟢", "LAUFENDE PROJEKTE", "Läuft"),
    "maintenance": ("🟠", "WARTUNG", "In Wartungsmodus"),
    "paused":      ("⏳", "IN BEARBEITUNG", "Pausiert / wartet auf dich"),
    "rejected":    ("🔴", "ARCHIV", "Abgelehnt"),
    "archived":    ("🗃️", "ARCHIV", "Archiviert"),
    "support":     ("❔", "OFFENE TICKETS", "Support-Frage"),
}
STATUS_TEXT = {
    "waiting": "Deine Anfrage steht auf der Warteliste.",
    "progress": "Dein Projekt wurde angenommen und wird jetzt bearbeitet.",
    "running": "Dein Projekt ist live und läuft.",
    "maintenance": "Dein Projekt befindet sich im Wartungsmodus.",
    "paused": "Dein Projekt ist pausiert und wartet auf Rückmeldung.",
    "rejected": "Das Ticket wurde abgelehnt und geschlossen.",
    "archived": "Dein Projekt ist abgeschlossen und archiviert. Danke für dein Vertrauen!",
}
ACTIVE_STATES = ("progress", "running", "maintenance", "paused")
rename_log: dict[int, list] = defaultdict(list)


def rename_wait(channel_id: int) -> int:
    """Discord: ca. 2 Umbenennungen pro 10 Minuten pro Channel."""
    now = time.time()
    rename_log[channel_id] = [t for t in rename_log[channel_id] if now - t < 600]
    if len(rename_log[channel_id]) >= 2:
        return int(600 - (now - rename_log[channel_id][0])) + 1
    return 0


# Umbenennungen, die Discord gerade blockt, werden automatisch nachgeholt.
# Kommen mehrere Statuswechsel hintereinander, gewinnt immer der neueste Name.
_pending_rename: dict[int, str] = {}
_rename_tasks: dict[int, asyncio.Task] = {}


async def _rename_later(channel: discord.TextChannel, wait: int):
    try:
        await asyncio.sleep(wait)
        name = _pending_rename.pop(channel.id, None)
        ch = channel.guild.get_channel(channel.id)
        if not name or ch is None or ch.name == name:
            return
        await ch.edit(name=name, reason="VOLT Ticket: Kanalname nachgezogen")
        rename_log[channel.id].append(time.time())
    except discord.HTTPException:
        pass
    finally:
        _rename_tasks.pop(channel.id, None)


def schedule_rename(channel: discord.TextChannel, name: str, wait: int):
    _pending_rename[channel.id] = name
    if channel.id not in _rename_tasks:
        _rename_tasks[channel.id] = asyncio.create_task(_rename_later(channel, wait))


def slugify(text: str) -> str:
    text = re.sub(r"[^a-z0-9äöüß]+", "-", text.lower().strip()).strip("-")
    return text[:40] or "projekt"


async def apply_status(guild: discord.Guild, channel: discord.TextChannel, ticket, status: str):
    emoji, cat_key, _ = STATUS[status]
    name = f"{emoji}{SEP}{ticket['slug']}"
    cat = find_category(guild, cat_key)
    kwargs = {}
    delayed = 0
    if channel.name != name:
        wait = rename_wait(channel.id)
        if wait:
            # Discord blockt gerade: Status gilt trotzdem sofort, der Name folgt automatisch
            schedule_rename(channel, name, wait)
            delayed = wait
        else:
            kwargs["name"] = name
            _pending_rename.pop(channel.id, None)
    elif channel.id in _pending_rename:
        _pending_rename.pop(channel.id, None)  # Name passt schon wieder, nichts nachholen
    if cat and channel.category_id != cat.id:
        kwargs["category"] = cat
    if kwargs:
        await channel.edit(**kwargs, sync_permissions=False, reason=f"VOLT Ticket #{ticket['id']}: {status}")
        if "name" in kwargs:
            rename_log[channel.id].append(time.time())

    member = guild.get_member(ticket["user_id"])
    if member:
        if status in ("archived", "rejected"):
            await channel.set_permissions(member, view_channel=True,
                                          read_message_history=True, send_messages=False)
        else:
            await channel.set_permissions(member, view_channel=True, read_message_history=True,
                                          send_messages=True, attach_files=True, embed_links=True)
    await pool.execute("UPDATE tickets SET status=$1 WHERE id=$2", status, ticket["id"])
    # Zeitstempel für die Website (durchschnittliche Bauzeit)
    if status == "progress":
        await pool.execute(
            "UPDATE tickets SET accepted_at=COALESCE(accepted_at, CURRENT_TIMESTAMP) WHERE id=$1", ticket["id"])
    elif status == "running":
        await pool.execute(
            "UPDATE tickets SET live_at=COALESCE(live_at, CURRENT_TIMESTAMP) WHERE id=$1", ticket["id"])
    # Werkbank: fertig/geschlossen -> Platz frei, Uhr stoppt; wartet auf Kunde -> nur Uhr stoppt
    if status in ("running", "maintenance", "archived", "rejected"):
        await free_slot(ticket["id"])
    elif status == "paused":
        await stop_timer(ticket["id"])
    invalidate_site_cache()
    return True, delayed


async def make_transcript(channel: discord.TextChannel, ticket) -> discord.File:
    lines = [f"Transcript Ticket #{ticket['id']} | {ticket['project_name']} | User-ID {ticket['user_id']}",
             "-" * 60]
    async for m in channel.history(limit=None, oldest_first=True):
        text = m.clean_content
        if m.embeds:
            text += " [Embed: " + ", ".join((e.title or "-") for e in m.embeds) + "]"
        for a in m.attachments:
            text += f" [Datei: {a.url}]"
        lines.append(f"[{m.created_at:%Y-%m-%d %H:%M}] {m.author}: {text}")
    data = io.BytesIO("\n".join(lines).encode("utf-8"))
    return discord.File(data, filename=f"transcript-{ticket['id']}.txt")


# ===============================================================
# VERIFY
# ===============================================================
class VerifyView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Regeln akzeptieren", emoji="✅",
                       style=discord.ButtonStyle.success, custom_id="volt:verify")
    async def accept(self, interaction: discord.Interaction, button: discord.ui.Button):
        guild, member = interaction.guild, interaction.user
        user_role, unv = find_role(guild, "user"), find_role(guild, "unverified")
        if user_role is None:
            return await interaction.response.send_message(
                "❌ Rolle fehlt, bitte Team informieren.", ephemeral=True)
        if user_role in member.roles:
            return await interaction.response.send_message(
                "✅ Du bist bereits verifiziert.", ephemeral=True)
        await member.add_roles(user_role, reason="Regeln akzeptiert")
        if unv and unv in member.roles:
            await member.remove_roles(unv, reason="Regeln akzeptiert")
        await interaction.response.send_message(
            "✅ Willkommen! Du hast die Regeln akzeptiert und siehst jetzt den ganzen Server.",
            ephemeral=True)
        await log(guild, "join-leave-logs", emb("✅ Verifiziert", f"{member.mention} hat die Regeln akzeptiert.", 0x2ECC71))


# ===============================================================
# FAQ
# ===============================================================
FAQ = {
    "Was kostet das?": "Für Familien und Fraktionen auf **Narco City** ist alles **kostenlos**. Wenn du zufrieden bist, "
                       "freue ich mich über eine freiwillige Spende, die klären wir direkt im Ticket. 💛\n\n"
                       "Anfragen von **anderen Servern** können wir leider nicht annehmen.",
    "Welche Produkte gibt es?": "👪 **Familien-Dashboard** (All-in-One)\n⚽ **Fussball-Manager**\n🗺️ **Routen Manager**\n\n"
                                f"Alle mit Vorschau zum Durchklicken auf **{SITE_LABEL}** und im Produkte-Kanal.",
    "Wie läuft eine Bestellung ab?": "1) In #bestellen dein Produkt auswählen\n2) Angeben, ob du von Narco City kommst und ob ihr "
                                     "schon einen Discord-Server habt\n3) Kurzen Fragebogen ausfüllen (Familie, Ränge, Funktionen)\n"
                                     "4) Ich prüfe deine Anfrage und schicke dir eine Bestätigung\n5) Du bestätigst oder lehnst ab\n"
                                     "6) Dein Projekt wird umgesetzt, du siehst den Status am Channel-Symbol.",
    "Wo sehe ich, ob alles läuft?": "Im Uptime-Kanal hier auf Discord und im Live-Status auf der Website. "
                                    "Dort steht, ob alle Systeme erreichbar sind, ob gerade Wartung ist oder eine Störung.",
    "Bekomme ich Bescheid, wenn das Team antwortet?": "Ja. Sobald jemand aus dem Team in deinem Ticket schreibt, bekommst du "
                                                       "eine DM mit Link zum Ticket. Mit **/dm-benachrichtigungen** schaltest du das an oder aus.",
    "Was bedeuten die Status-Symbole?": "🟡 Offen · 🔵 In Bearbeitung · 🟢 Läuft · 🟠 Wartungsmodus · "
                                        "⏳ Pausiert · 📦 Archiv · 🔴 Abgelehnt",
    "Wer sieht mein Ticket?": "Nur du und der Owner/Admin. Kein anderer User, auch keine Kunden.",
    "Was darf ich NICHT ins Ticket schreiben?": "Schicke **nie** deinen Bot-Token, Passwörter oder Zahlungsdaten. "
                                                "Für Zugänge sprechen wir einen sicheren Weg ab.",
    "Für wen ist das Angebot?": "Ausschließlich für Familien und Fraktionen auf **Narco City**, die ihren Discord mit "
                                "Dashboard und eigenem Bot organisieren wollen. Andere Server können wir leider nicht annehmen.",
    "Warum kann ich kein Ticket öffnen?": "Entweder hast du schon die maximale Anzahl offener Tickets oder du bist "
                                          "vorübergehend gesperrt. Bei einer Sperre siehst du beim Öffnen, bis wann sie "
                                          "gilt und warum.",
}


class FaqView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.select(custom_id="volt:faq", placeholder="Wähle eine Frage …",
                       options=[discord.SelectOption(label=q[:100], value=str(i))
                                for i, q in enumerate(FAQ)])
    async def pick(self, interaction: discord.Interaction, select: discord.ui.Select):
        q = list(FAQ)[int(select.values[0])]
        await interaction.response.send_message(embed=emb(f"❓ {q}", FAQ[q]), ephemeral=True)

    @discord.ui.button(label="Frage nicht dabei? Support-Ticket öffnen", emoji="❔", row=1,
                       style=discord.ButtonStyle.secondary, custom_id="volt:faq:support")
    async def support(self, interaction: discord.Interaction, button: discord.ui.Button):
        await open_support(interaction)


# ===============================================================
# SUPPORT-TICKETS: neutrale Fragen für alle, ohne Server-Abfrage und ohne Fragebogen
# ===============================================================
class SupportModal(discord.ui.Modal, title="Support-Anfrage"):
    subject = discord.ui.TextInput(label="Worum geht es?", min_length=3, max_length=60,
                                   placeholder="z. B. Frage zum VOLT Bot")
    message = discord.ui.TextInput(label="Dein Anliegen", style=discord.TextStyle.paragraph, min_length=10,
                                   max_length=1500, placeholder="Schreib direkt rein, wobei wir dir helfen können.")

    async def on_submit(self, interaction: discord.Interaction):
        guild, member = interaction.guild, interaction.user
        if len(re.findall(r"[0-9A-Za-zÄÖÜäöüß]", self.message.value)) < 8:
            return await interaction.response.send_message(
                "❌ Beschreib dein Anliegen bitte kurz in ein paar Worten.", ephemeral=True)
        await interaction.response.defer(ephemeral=True)
        n = await pool.fetchval(
            "SELECT count(*) FROM tickets WHERE user_id=$1 AND status NOT IN ('archived','rejected','deleted')",
            member.id)
        if n >= MAX_OPEN_TICKETS:
            return await interaction.followup.send(
                f"❌ Du hast schon {n} offene Tickets (Maximum {MAX_OPEN_TICKETS}).", ephemeral=True)
        subject, text = self.subject.value.strip(), self.message.value.strip()
        slug = slugify(f"support-{member.name}")
        ow = ticket_overwrites(guild, member)
        sup = find_role(guild, "support")
        if sup:   # Helfer übernehmen die Erstantwort
            ow[sup] = discord.PermissionOverwrite(view_channel=True, read_message_history=True, send_messages=True,
                                                  attach_files=True, embed_links=True)
        channel = await guild.create_text_channel(
            f"{STATUS['support'][0]}{SEP}{slug}", category=find_category(guild, "OFFENE TICKETS"), overwrites=ow,
            topic=f"Support von {member} | {subject}"[:1024], reason="VOLT Support")
        tid = await pool.fetchval(
            """INSERT INTO tickets (channel_id,user_id,project_type,project_name,slug,description,platform,status)
               VALUES ($1,$2,$3,$4,$5,$6,$7,$8) RETURNING id""",
            channel.id, member.id, "Support", subject, slug, text, "Support", "support")
        invalidate_site_cache()
        e = emb(f"{ic('faq', '❔')} Support #{tid} – {subject}", text[:4000])
        e.add_field(name="Von", value=member.mention, inline=True)
        await channel.send(
            content=f"<@{OWNER_ID}>{' ' + sup.mention if sup else ''} {member.mention}\n"
                    f"Danke für deine Nachricht! Schreib gern noch Details oder Screenshots dazu. "
                    f"Sobald das Team antwortet, bekommst du eine DM.",
            embed=e, view=SupportTicketView(),
            allowed_mentions=discord.AllowedMentions(users=True, roles=True))
        await interaction.followup.send(f"✅ Dein Support-Ticket wurde erstellt: {channel.mention}", ephemeral=True)
        await log(guild, "ticket-logs", emb("❔ Support-Ticket geöffnet",
                                            f"#{tid} · {subject} · {member.mention}\n{channel.mention}"))


async def open_support(interaction: discord.Interaction):
    if not await ticket_allowed(interaction):
        return
    await interaction.response.send_modal(SupportModal())


class SupportTicketView(discord.ui.View):
    """Im Support-Ticket: Ersteller, Helfer oder Owner schließen es mit „Erledigt“."""
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Erledigt", emoji="✅", style=discord.ButtonStyle.success, custom_id="volt:s:done")
    async def done(self, interaction: discord.Interaction, button: discord.ui.Button):
        ticket = await get_ticket(interaction.channel.id)
        if not ticket or ticket["status"] != "support":
            return await interaction.response.send_message("❌ Dieses Support-Ticket ist schon geschlossen.",
                                                           ephemeral=True)
        user = interaction.user
        if not (user.id == ticket["user_id"] or has_team_role(user)):
            return await interaction.response.send_message("❌ Keine Berechtigung.", ephemeral=True)
        await interaction.response.defer(ephemeral=True)
        try:
            f = await make_transcript(interaction.channel, ticket)
            await log(interaction.guild, "ticket-logs",
                      emb("✅ Support erledigt", f"#{ticket['id']} · {ticket['project_name']} · geschlossen von {user.mention}"),
                      file=f)
        except discord.HTTPException:
            pass
        _, delayed = await apply_status(interaction.guild, interaction.channel, ticket, "archived")
        await interaction.channel.send(embed=emb("✅ Erledigt", "Dieses Support-Ticket ist geschlossen. "
                                                              "Neue Frage? Einfach wieder auf **Support / Frage** klicken."))
        if user.id != ticket["user_id"]:
            await notify_ticket_owner(interaction.guild, ticket, "✅ Support-Ticket geschlossen",
                                      f"Dein Support-Ticket **{ticket['project_name']}** wurde als erledigt markiert.",
                                      force=True, author=user)
        await interaction.followup.send("✅ Ticket geschlossen.", ephemeral=True)


# ===============================================================
# TICKET: OEFFNEN
# ===============================================================
def is_other_server(ticket) -> bool:
    """Anfrage von außerhalb Narco City (Warteliste, nicht kostenlos)."""
    return (ticket["platform"] or "").startswith("Anderer Server")


class TicketPrecheckView(discord.ui.View):
    """Vor dem Fragebogen: Narco City oder anderer Server, Discord-Server vorhanden?"""
    def __init__(self, ptype: str):
        super().__init__(timeout=600)
        self.ptype = ptype
        self.nc = None
        self.has_server = None

    @staticmethod
    def _mark(select: discord.ui.Select):
        for o in select.options:
            o.default = o.value == select.values[0]

    @discord.ui.select(placeholder="🌍 Woher kommst du?", row=0, options=[
        discord.SelectOption(label="Narco City", value="nc", emoji="🌴",
                             description="Für Narco City ist alles kostenlos"),
        discord.SelectOption(label="Anderer Server", value="other", emoji="🌐",
                             description="Leider nicht möglich, nur Narco City")])
    async def origin(self, interaction: discord.Interaction, select: discord.ui.Select):
        if select.values[0] == "other":
            self.stop()
            return await interaction.response.edit_message(view=None, embed=emb(
                "🌴 Nur für Narco City",
                "Sorry, VOLT betreut **ausschließlich Familien und Fraktionen von Narco City**. "
                "Anfragen von anderen Servern können wir leider nicht annehmen.\n\n"
                "Danke trotzdem für dein Interesse! 🙏", 0xE74C3C))
        self.nc = True
        self._mark(select)
        await interaction.response.edit_message(view=self)

    @discord.ui.select(placeholder="💬 Habt ihr schon einen Discord-Server?", row=1, options=[
        discord.SelectOption(label="Ja, haben wir", value="yes", emoji="✅"),
        discord.SelectOption(label="Nein, brauchen wir auch", value="no", emoji="🆕",
                             description="Der Server wird mit eingerichtet")])
    async def server(self, interaction: discord.Interaction, select: discord.ui.Select):
        self.has_server = select.values[0] == "yes"
        self._mark(select)
        await interaction.response.edit_message(view=self)

    @discord.ui.button(label="Weiter zum Fragebogen", emoji="📝", style=discord.ButtonStyle.primary, row=2)
    async def go(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.nc is None or self.has_server is None:
            return await interaction.response.send_message("❌ Bitte beantworte erst beide Fragen.", ephemeral=True)
        if not await ticket_allowed(interaction):
            return
        await interaction.response.send_modal(TicketModal(self.ptype, self.nc, self.has_server))


def precheck_embed(ptype: str) -> discord.Embed:
    return emb(f"📝 Anfrage: {ptype}",
               "Kurz vorab, damit deine Anfrage schnell bearbeitet werden kann:\n\n"
               "🌴 **Narco City:** alles kostenlos\n"
               "🌐 **Andere Server:** können wir leider nicht annehmen\n\n"
               "Beantworte beide Fragen und klick dann auf **Weiter zum Fragebogen**.")


class TicketModal(discord.ui.Modal):
    def __init__(self, ptype: str, nc: bool, has_server: bool):
        prod = product_by_label(ptype)
        super().__init__(title=(f"Anfrage: {prod['name']}" if prod else "Individuelle Anfrage")[:45])
        self.ptype, self.nc, self.has_server = ptype, nc, has_server
        self.pname = discord.ui.TextInput(label="Name eurer Familie / eures Projekts", min_length=2, max_length=40,
                                          placeholder="wird zum Namen deines Ticket-Kanals")
        self.who = discord.ui.TextInput(
            label="Dein Ingame-Name auf Narco City" if nc else "Welcher Server / welche Community?",
            min_length=3, max_length=50, placeholder="Vor- und Nachname ingame" if nc else "z. B. Name eures RP-Servers")
        self.ranks = discord.ui.TextInput(label="Eure Ränge (von oben nach unten)", style=discord.TextStyle.paragraph,
                                          min_length=5, max_length=500,
                                          placeholder="z. B. Boss, Underboss, Capo, Member, Prospect")
        self.desc = discord.ui.TextInput(label="Welche Funktionen braucht ihr? Wünsche",
                                         style=discord.TextStyle.paragraph, min_length=10, max_length=1000,
                                         placeholder="z. B. Kasse, Wochenabgaben, Lager, Sanktionen, Termine – oder alles")
        if has_server:
            self.link = discord.ui.TextInput(label="Einladung zu eurem Discord", min_length=8, max_length=200,
                                             placeholder="discord.gg/…")
        else:
            self.link = discord.ui.TextInput(label="Wünsche für euren neuen Discord (optional)", required=False,
                                             max_length=300, placeholder="z. B. Name, Farben, Kanäle")
        for item in (self.pname, self.who, self.ranks, self.desc, self.link):
            self.add_item(item)

    async def on_submit(self, interaction: discord.Interaction):
        guild, member = interaction.guild, interaction.user
        # Nur Punkte/Striche o. Ä. zählen nicht als Angabe
        meaningful = lambda v: len(re.findall(r"[0-9A-Za-zÄÖÜäöüß]", v or "")) >= 2
        fields = [("Familie", self.pname), ("Ingame-Name", self.who), ("Ränge", self.ranks), ("Funktionen", self.desc)]
        if self.has_server:
            fields.append(("Discord-Einladung", self.link))
        bad = [n for n, f in fields if not meaningful(f.value)]
        if self.has_server and not bad and not re.search(r"discord(app)?\.(gg|com)/", self.link.value, re.I):
            bad.append("Discord-Einladung (Link wie discord.gg/…)")
        if bad:
            return await interaction.response.send_message(
                "❌ Bitte fülle den Fragebogen richtig aus. Fehlt oder ungültig: **" + ", ".join(bad) + "**.\n"
                "Wähl dein Produkt in #bestellen einfach noch einmal aus.", ephemeral=True)
        await interaction.response.defer(ephemeral=True)

        n = await pool.fetchval(
            "SELECT count(*) FROM tickets WHERE user_id=$1 AND status NOT IN ('archived','rejected','deleted')",
            member.id)
        if n >= MAX_OPEN_TICKETS:
            return await interaction.followup.send(
                f"❌ Du hast schon {n} offene Tickets (Maximum {MAX_OPEN_TICKETS}).", ephemeral=True)

        slug = slugify(self.pname.value)
        desc = self.desc.value
        link = self.link.value if self.has_server else None
        if not self.has_server and self.link.value:
            desc += f"\n\nWünsche für den neuen Discord: {self.link.value}"
        cat = find_category(guild, "OFFENE TICKETS")
        channel = await guild.create_text_channel(
            f"🟡{SEP}{slug}", category=cat, overwrites=ticket_overwrites(guild, member),
            topic=f"Ticket von {member} | {self.ptype} | Narco City", reason="VOLT Ticket")
        tid = await pool.fetchval(
            """INSERT INTO tickets (channel_id,user_id,project_type,project_name,slug,description,
               platform,link,budget,status,ingame,ranks,has_discord)
               VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13) RETURNING id""",
            channel.id, member.id, self.ptype, self.pname.value, slug, desc,
            "Narco City", link, None, "open", self.who.value, self.ranks.value,
            "ja" if self.has_server else "nein")
        invalidate_site_cache()

        prod = product_by_label(self.ptype)
        e = emb(f"🟡 Ticket #{tid} – {self.pname.value}", color=0xF1C40F)
        e.add_field(name="Produkt", value=self.ptype, inline=True)
        e.add_field(name="Herkunft", value="🌴 Narco City", inline=True)
        e.add_field(name="Ingame-Name", value=self.who.value, inline=True)
        e.add_field(name="Discord-Server", value=(f"✅ vorhanden · {link}" if self.has_server
                                                  else "🆕 wird mit eingerichtet"), inline=False)
        e.add_field(name="Ränge", value=self.ranks.value[:1024], inline=False)
        e.add_field(name="Funktionen & Wünsche", value=desc[:1024], inline=False)
        e.add_field(name="Von", value=member.mention, inline=True)
        if prod:
            e.add_field(name="🔎 Vorschau", value=f"[{prod['name']} ansehen]({product_url(prod['key'])})", inline=False)
        await channel.send(
            content=f"<@{OWNER_ID}> {member.mention}\nDeine Anfrage ist eingegangen. "
                    f"Du bekommst hier eine Bestätigung, sobald sie geprüft wurde. "
                    f"Antwortet das Team, bekommst du eine DM.",
            embed=e, view=AdminPanelView())
        await interaction.followup.send(f"✅ Dein Ticket wurde erstellt: {channel.mention}", ephemeral=True)
        await log(guild, "ticket-logs", emb("🟡 Ticket geöffnet",
                                            f"#{tid} · {self.pname.value} · {member.mention}\n{channel.mention}"))


def product_options():
    opts = [discord.SelectOption(label=p["name"], value=str(i), emoji=p["emoji"],
                                 description=p["short"][:100]) for i, p in enumerate(PRODUCTS)]
    opts.append(discord.SelectOption(label="Individuelle Anfrage", value=str(len(PRODUCTS)), emoji="💡",
                                     description="Etwas anderes oder eine Erweiterung"))
    return opts


BL_DURATIONS = [("1 Tag", 1), ("3 Tage", 3), ("1 Woche", 7), ("2 Wochen", 14), ("1 Monat", 30), ("Dauerhaft", 0)]


def bl_until_text(until) -> str:
    return f"bis <t:{int(until)}:f> (<t:{int(until)}:R>)" if until else "dauerhaft"


async def active_blacklist(user_id: int):
    """Aktiver Blacklist-Eintrag oder None. Abgelaufene Sperren werden dabei gelöscht."""
    r = await pool.fetchrow("SELECT * FROM blacklist WHERE user_id=$1", user_id)
    if r and r["until"] and r["until"] <= time.time():
        await pool.execute("DELETE FROM blacklist WHERE user_id=$1", user_id)
        return None
    return r


async def blacklist_user(guild: discord.Guild, user: discord.abc.User, days: int, reason: str, by) -> int | None:
    until = int(time.time() + days * 86400) if days > 0 else None
    await pool.execute("INSERT INTO blacklist (user_id,reason,until,mod_id) VALUES ($1,$2,$3,$4) "
                       "ON CONFLICT (user_id) DO UPDATE SET reason=$2, until=$3, mod_id=$4, "
                       "created_at=CURRENT_TIMESTAMP", user.id, reason, until, by.id)
    await log(guild, "mod-logs", emb("🚫 Ticket-Sperre", f"{user.mention} · {bl_until_text(until)}\n"
                                                          f"**Grund:** {reason}\nVon: {by.mention}"))
    try:
        await user.send(embed=emb("🚫 Ticket-Sperre",
                                  f"Du kannst {bl_until_text(until)} keine Tickets bei **{BRAND}** öffnen.\n"
                                  f"**Grund:** {reason}", 0xE74C3C))
    except discord.HTTPException:
        pass
    return until


async def ticket_allowed(interaction: discord.Interaction) -> bool:
    bl = await active_blacklist(interaction.user.id)
    if bl:
        await interaction.response.send_message(
            f"🚫 Du kannst {bl_until_text(bl['until'])} keine Tickets öffnen.\n**Grund:** {bl['reason'] or '–'}",
            ephemeral=True)
        return False
    n = await pool.fetchval(
        "SELECT count(*) FROM tickets WHERE user_id=$1 AND status NOT IN ('archived','rejected','deleted')",
        interaction.user.id)
    if n >= MAX_OPEN_TICKETS:
        await interaction.response.send_message(
            f"❌ Du hast schon {n} offene Tickets (Maximum {MAX_OPEN_TICKETS}).", ephemeral=True)
        return False
    return True


class ProjectSelect(discord.ui.Select):
    def __init__(self, persistent: bool = False):
        kw = {"custom_id": "volt:ticket:product"} if persistent else {}
        super().__init__(placeholder="🛒 Produkt wählen und anfragen …", options=product_options(), row=0, **kw)

    async def callback(self, interaction: discord.Interaction):
        if not await ticket_allowed(interaction):
            return
        ptype = PROJECT_TYPES[int(self.values[0])]
        await interaction.response.send_message(embed=precheck_embed(ptype), view=TicketPrecheckView(ptype),
                                                ephemeral=True)


class ProjectSelectView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=180)
        self.add_item(ProjectSelect())


class TicketPanelView(discord.ui.View):
    """Bestell-Panel: Produkt direkt auswählen, darunter die Vorschauen auf der Website und der Support-Knopf."""
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(ProjectSelect(persistent=True))
        for p in PRODUCTS:
            self.add_item(discord.ui.Button(label=f"Vorschau {p['name']}", emoji=p["emoji"], row=1,
                                            style=discord.ButtonStyle.link, url=product_url(p["key"])))

    @discord.ui.button(label="Support / Frage", emoji="❔", style=discord.ButtonStyle.secondary,
                       custom_id="volt:ticket:support", row=2)
    async def support(self, interaction: discord.Interaction, button: discord.ui.Button):
        await open_support(interaction)


class LegacyTicketButtonView(discord.ui.View):
    """Alter „Ticket öffnen“-Button aus früheren Panels funktioniert weiter."""
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Ticket öffnen", emoji="🎫",
                       style=discord.ButtonStyle.primary, custom_id="volt:ticket:open")
    async def open_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await ticket_allowed(interaction):
            return
        await interaction.response.send_message(
            "Welches Produkt möchtest du?", view=ProjectSelectView(), ephemeral=True)


# ===============================================================
# TICKET: ADMIN-PANEL (nur OWNER_ID)
# ===============================================================
class PriceModal(discord.ui.Modal, title="Projekt annehmen"):
    price = discord.ui.TextInput(label="Kosten (Standard: kostenlos)",
                                 default="kostenlos", max_length=60)

    def __init__(self, ticket_id: int, paid: bool = False):
        super().__init__()
        self.ticket_id = ticket_id
        self.paid = paid
        if paid:  # anderer Server: nicht kostenlos, Preis wird eingetragen
            self.price.label = "Kosten (anderer Server, nicht kostenlos)"
            self.price.default = None
            self.price.placeholder = "z. B. 20 €"

    async def on_submit(self, interaction: discord.Interaction):
        ticket = await get_ticket(interaction.channel.id)
        if not ticket or ticket["id"] != self.ticket_id:
            return await interaction.response.send_message("❌ Ticket nicht gefunden.", ephemeral=True)
        e = emb("💼 Bestätigung für dein Projekt",
                f"**Projekt:** {ticket['project_name']}\n**Kosten:** {self.price.value}\n\n"
                f"Bestätige, um zu starten, oder lehne ab.\n"
                + ("Für Server außerhalb von Narco City ist das Angebot nicht kostenlos."
                   if self.paid else "Für Narco City ist alles kostenlos – Spenden sind freiwillig. 💛"))
        await interaction.response.defer(ephemeral=True)
        if ticket["status"] == "waiting":  # direkt aus der Warteliste angenommen
            await apply_status(interaction.guild, interaction.channel, ticket, "open")
        msg = await interaction.channel.send(
            content=f"<@{ticket['user_id']}>", embed=e, view=OfferView())
        await pool.execute("UPDATE tickets SET price=$1, status='offered', offer_message_id=$2 WHERE id=$3",
                           self.price.value, msg.id, ticket["id"])
        invalidate_site_cache()
        await interaction.followup.send("✅ Bestätigung gesendet.", ephemeral=True)
        await notify_ticket_owner(
            interaction.guild, ticket, "💼 Dein Projekt wartet auf dich",
            f"Für **{ticket['project_name']}** liegt eine Bestätigung bereit. "
            f"Schau ins Ticket und bestätige oder lehne ab.", force=True, author=interaction.user)


class NoteModal(discord.ui.Modal, title="Interne Notiz"):
    note = discord.ui.TextInput(label="Notiz (nur für Admin-Logs)",
                                style=discord.TextStyle.paragraph, max_length=1000)

    def __init__(self, ticket):
        super().__init__()
        self.ticket = ticket

    async def on_submit(self, interaction: discord.Interaction):
        await log(interaction.guild, "ticket-logs",
                  emb(f"📝 Notiz zu Ticket #{self.ticket['id']} ({self.ticket['project_name']})",
                      self.note.value))
        await interaction.response.send_message("✅ Notiz in #ticket-logs gespeichert (für den Kunden unsichtbar).",
                                                ephemeral=True)


class DeleteConfirm(discord.ui.View):
    def __init__(self, ticket):
        super().__init__(timeout=60)
        self.ticket = ticket

    @discord.ui.button(label="Endgültig löschen", style=discord.ButtonStyle.danger, emoji="🗑️")
    async def go(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(content="⏳ Speichere Transcript und lösche …", view=None)
        channel = interaction.channel
        try:
            f = await make_transcript(channel, self.ticket)
            await log(interaction.guild, "ticket-logs",
                      emb("🗑️ Ticket gelöscht", f"#{self.ticket['id']} · {self.ticket['project_name']}"), file=f)
            await pool.execute("UPDATE tickets SET status='deleted' WHERE id=$1", self.ticket["id"])
            await free_slot(self.ticket["id"])
            await channel.delete(reason="VOLT Ticket gelöscht")
        except discord.HTTPException as e:
            await interaction.followup.send(f"❌ Fehler: {e}", ephemeral=True)


async def change_status(interaction: discord.Interaction, status: str, reason: str = None):
    ticket = await get_ticket(interaction.channel.id)
    if not ticket:
        return await interaction.response.send_message("❌ Kein Ticket in der Datenbank.", ephemeral=True)
    prev = ticket["status"]
    if status in ("running", "maintenance", "paused") and prev in ("open", "offered", "rejected", "waiting"):
        return await interaction.response.send_message(
            "❌ Erst muss der Kunde das Angebot bestätigen.", ephemeral=True)

    await interaction.response.defer(ephemeral=True)
    if reason:
        await pool.execute("UPDATE tickets SET reject_reason=$1 WHERE id=$2", reason, ticket["id"])
    _, delayed = await apply_status(interaction.guild, interaction.channel, ticket, status)

    emoji, _, label = STATUS[status]
    member = interaction.guild.get_member(ticket["user_id"])
    worked = await work_seconds(ticket["id"])
    status_e = emb(f"{emoji} Status: {label}", STATUS_TEXT.get(status, ""))
    if reason:
        status_e.add_field(name="Grund", value=reason[:1024], inline=False)
    if status in ("running", "archived") and worked > 0:
        status_e.add_field(name="⏱️ Arbeitszeit", value=fmt_dur(worked))
    await interaction.channel.send(content=member.mention if member else None, embed=status_e)
    await log(interaction.guild, "ticket-logs",
              emb(f"{emoji} Status geändert", f"#{ticket['id']} · {ticket['project_name']} → **{label}**"
                  + (f"\nGrund: {reason}" if reason else "")
                  + (f"\nArbeitszeit bisher: {fmt_dur(worked)}" if worked > 0 else "")))
    review_open = status == "running" and not await has_review(ticket["id"])
    await notify_ticket_owner(interaction.guild, ticket, f"{emoji} Neuer Status: {label}",
                              STATUS_TEXT.get(status, "Der Status deines Projekts hat sich geändert.")
                              + (f"\n\n**Grund:** {reason}" if reason else "")
                              + ("\n\n⭐ Wenn du zufrieden bist, kannst du dein Projekt jetzt im Ticket bewerten."
                                 if review_open else ""),
                              force=True, author=interaction.user)

    if review_open:
        # Projekt ist live: Kunde wird direkt um eine Bewertung gebeten (DM kam schon mit dem Status)
        await request_review(interaction.guild, interaction.channel, ticket, dm=False)

    if status == "archived":
        try:
            f = await make_transcript(interaction.channel, ticket)
            await log(interaction.guild, "ticket-logs",
                      emb("📦 Ticket archiviert", f"#{ticket['id']} · {ticket['project_name']}"), file=f)
        except discord.HTTPException:
            pass
        if prev in ACTIVE_STATES:
            # Noch keine Bewertung? Dann zum Abschluss nochmal freundlich fragen
            await request_review(interaction.guild, interaction.channel, ticket, dm=False)
    await interaction.followup.send(
        "✅ Status aktualisiert." + (f" Den Kanalnamen zieht der Bot in ca. {max(1, round(delayed / 60))} Min "
                                    f"automatisch nach (Discord-Limit)." if delayed else ""), ephemeral=True)


class AdminPanelView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != OWNER_ID:
            await interaction.response.send_message("❌ Keine Berechtigung.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="Annehmen", emoji="✅", style=discord.ButtonStyle.success,
                       custom_id="volt:t:accept", row=0)
    async def accept(self, interaction, button):
        ticket = await get_ticket(interaction.channel.id)
        if not ticket or ticket["status"] not in ("open", "offered", "waiting"):
            return await interaction.response.send_message(
                "❌ Dieses Ticket ist schon angenommen oder geschlossen.", ephemeral=True)
        await interaction.response.send_modal(PriceModal(ticket["id"], paid=is_other_server(ticket)))

    @discord.ui.button(label="Läuft", emoji="🟢", style=discord.ButtonStyle.secondary,
                       custom_id="volt:t:running", row=0)
    async def running(self, interaction, button):
        await change_status(interaction, "running")

    @discord.ui.button(label="Wartung", emoji="🟠", style=discord.ButtonStyle.secondary,
                       custom_id="volt:t:maint", row=0)
    async def maint(self, interaction, button):
        await change_status(interaction, "maintenance")

    @discord.ui.button(label="Pausiert", emoji="⏳", style=discord.ButtonStyle.secondary,
                       custom_id="volt:t:paused", row=0)
    async def paused(self, interaction, button):
        await change_status(interaction, "paused")

    @discord.ui.button(label="Archivieren", emoji="📦", style=discord.ButtonStyle.primary,
                       custom_id="volt:t:archive", row=0)
    async def archive(self, interaction, button):
        await change_status(interaction, "archived")

    @discord.ui.button(label="Ablehnen", emoji="🔴", style=discord.ButtonStyle.danger,
                       custom_id="volt:t:reject", row=1)
    async def reject(self, interaction, button):
        ticket = await get_ticket(interaction.channel.id)
        if not ticket:
            return await interaction.response.send_message("❌ Kein Ticket.", ephemeral=True)
        await interaction.response.send_modal(RejectModal())

    @discord.ui.button(label="Notiz", emoji="📝", style=discord.ButtonStyle.secondary,
                       custom_id="volt:t:note", row=1)
    async def note(self, interaction, button):
        ticket = await get_ticket(interaction.channel.id)
        if not ticket:
            return await interaction.response.send_message("❌ Kein Ticket.", ephemeral=True)
        await interaction.response.send_modal(NoteModal(ticket))

    @discord.ui.button(label="Transcript", emoji="📄", style=discord.ButtonStyle.secondary,
                       custom_id="volt:t:transcript", row=1)
    async def transcript(self, interaction, button):
        ticket = await get_ticket(interaction.channel.id)
        if not ticket:
            return await interaction.response.send_message("❌ Kein Ticket.", ephemeral=True)
        await interaction.response.defer(ephemeral=True)
        f = await make_transcript(interaction.channel, ticket)
        await log(interaction.guild, "ticket-logs",
                  emb("📄 Transcript", f"#{ticket['id']} · {ticket['project_name']}"), file=f)
        await interaction.followup.send("✅ Transcript in #ticket-logs gespeichert.", ephemeral=True)

    @discord.ui.button(label="Löschen", emoji="🗑️", style=discord.ButtonStyle.danger,
                       custom_id="volt:t:delete", row=1)
    async def delete(self, interaction, button):
        ticket = await get_ticket(interaction.channel.id)
        if not ticket:
            return await interaction.response.send_message("❌ Kein Ticket.", ephemeral=True)
        await interaction.response.send_message(
            "Ticket mit Transcript sichern und löschen?", view=DeleteConfirm(ticket), ephemeral=True)

    @discord.ui.button(label="Sperren", emoji="🚫", style=discord.ButtonStyle.secondary,
                       custom_id="volt:t:blacklist", row=1)
    async def ban(self, interaction, button):
        ticket = await get_ticket(interaction.channel.id)
        if not ticket:
            return await interaction.response.send_message("❌ Kein Ticket.", ephemeral=True)
        await interaction.response.send_modal(BlacklistModal(ticket["user_id"]))


class RejectModal(discord.ui.Modal, title="Ticket ablehnen"):
    grund = discord.ui.TextInput(label="Grund der Ablehnung (sieht der Kunde)", style=discord.TextStyle.paragraph,
                                 min_length=3, max_length=500,
                                 placeholder="z. B. Wir betreuen ausschließlich Narco City / Angaben fehlen")

    async def on_submit(self, interaction: discord.Interaction):
        await change_status(interaction, "rejected", reason=self.grund.value.strip())


class BlacklistModal(discord.ui.Modal, title="Für Tickets sperren"):
    tage = discord.ui.TextInput(label="Dauer in Tagen (0 = dauerhaft)", default="7", max_length=4)
    grund = discord.ui.TextInput(label="Grund (sieht der User)", style=discord.TextStyle.paragraph,
                                 min_length=3, max_length=300)

    def __init__(self, user_id: int):
        super().__init__()
        self.user_id = user_id

    async def on_submit(self, interaction: discord.Interaction):
        try:
            days = int(self.tage.value.strip())
            if days < 0:
                raise ValueError
        except ValueError:
            return await interaction.response.send_message("❌ Dauer bitte als Zahl in Tagen (0 = dauerhaft).",
                                                           ephemeral=True)
        await interaction.response.defer(ephemeral=True)
        user = interaction.guild.get_member(self.user_id) or await bot.fetch_user(self.user_id)
        until = await blacklist_user(interaction.guild, user, days, self.grund.value.strip(), interaction.user)
        await interaction.channel.send(embed=emb("🚫 Für Tickets gesperrt",
                                                 f"{user.mention} kann {bl_until_text(until)} keine neuen Tickets "
                                                 f"öffnen.\n**Grund:** {self.grund.value.strip()}", 0xE74C3C))
        await interaction.followup.send("✅ Gesperrt.", ephemeral=True)


# ===============================================================
# TICKET: ANGEBOT (nur Ersteller)
# ===============================================================
class OfferView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        if DONATION_URL:
            self.add_item(discord.ui.Button(label="Freiwillig spenden", emoji="💛",
                                            style=discord.ButtonStyle.link, url=DONATION_URL))

    async def _check(self, interaction: discord.Interaction):
        ticket = await get_ticket(interaction.channel.id)
        if not ticket or interaction.user.id != ticket["user_id"]:
            await interaction.response.send_message(
                "❌ Nur der Ticket-Ersteller kann das Angebot beantworten.", ephemeral=True)
            return None
        if ticket["status"] != "offered" or ticket["offer_message_id"] != interaction.message.id:
            await interaction.response.send_message("❌ Dieses Angebot ist nicht mehr aktuell.", ephemeral=True)
            return None
        return ticket

    @discord.ui.button(label="Bestätigen", emoji="✅", style=discord.ButtonStyle.success,
                       custom_id="volt:offer:confirm")
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        ticket = await self._check(interaction)
        if not ticket:
            return
        await interaction.response.defer()
        await apply_status(interaction.guild, interaction.channel, ticket, "progress")
        kunde = find_role(interaction.guild, "kunde")
        if kunde:
            await interaction.user.add_roles(kunde, reason="Angebot bestätigt")
        await interaction.message.edit(view=None)
        await interaction.channel.send(embed=emb(
            "🔵 Angebot bestätigt",
            f"{interaction.user.mention} hat das Angebot ({ticket['price']}) bestätigt.\n"
            f"Das Projekt ist jetzt **in Bearbeitung** und du hast die Rolle **Kunde**."))
        await log(interaction.guild, "ticket-logs",
                  emb("🔵 Angebot bestätigt", f"#{ticket['id']} · {ticket['project_name']} · {ticket['price']}"))

    @discord.ui.button(label="Ablehnen", emoji="❌", style=discord.ButtonStyle.danger,
                       custom_id="volt:offer:decline")
    async def decline(self, interaction: discord.Interaction, button: discord.ui.Button):
        ticket = await self._check(interaction)
        if not ticket:
            return
        await interaction.response.defer()
        await apply_status(interaction.guild, interaction.channel, ticket, "rejected")
        await interaction.message.edit(view=None)
        await interaction.channel.send(embed=emb(
            "🔴 Angebot abgelehnt", "Das Ticket wurde geschlossen. Du kannst jederzeit ein neues öffnen.",
            0xE74C3C))
        await log(interaction.guild, "ticket-logs",
                  emb("🔴 Angebot abgelehnt", f"#{ticket['id']} · {ticket['project_name']}", 0xE74C3C))


# ===============================================================
# BEWERTUNGEN
# ===============================================================
REVIEW_PANEL_FOOTER = "VOLT • Bewertungsübersicht"


def rating_label(avg, count: int) -> str:
    """Zufriedenheit als Text, wird im Discord und auf der Website angezeigt."""
    if not count or avg is None:
        return "Noch keine Bewertungen"
    if avg >= 4.5:
        return "Sehr zufrieden"
    if avg >= 3.5:
        return "Überwiegend zufrieden"
    if avg >= 2.5:
        return "Gemischt"
    if avg >= 1.5:
        return "Überwiegend unzufrieden"
    return "Unzufrieden"


async def review_summary():
    row = await pool.fetchrow("SELECT count(*) AS n, avg(stars) AS a FROM reviews")
    count = int(row["n"] or 0)
    avg = float(row["a"]) if row["a"] is not None else None
    dist = {i: 0 for i in range(1, 6)}
    for r in await pool.fetch("SELECT stars, count(*) AS n FROM reviews GROUP BY stars"):
        if r["stars"] in dist:
            dist[r["stars"]] = int(r["n"])
    return count, avg, dist


async def review_panel_embed() -> discord.Embed:
    count, avg, dist = await review_summary()
    if not count:
        e = discord.Embed(
            title="⭐ Bewertungen",
            description="Hier erscheinen die Bewertungen unserer Kunden nach Projektabschluss.\n\n"
                        "Noch keine Bewertungen vorhanden. Projekt fertig und noch nicht bewertet? "
                        "Nutze **/bewerten**.",
            color=BRAND_COLOR)
    else:
        lines = []
        for i in range(5, 0, -1):
            filled = round(dist[i] / count * 10)
            lines.append(f"`{i}★` {'█' * filled}{'░' * (10 - filled)} {dist[i]}")
        e = discord.Embed(
            title=f"⭐ {avg:.1f}/5 · {rating_label(avg, count)}",
            description=f"Aus **{count}** Bewertung{'en' if count != 1 else ''}\n\n" + "\n".join(lines) +
                        "\n\nProjekt fertig und noch nicht bewertet? Nutze **/bewerten**.",
            color=BRAND_COLOR)
    e.set_footer(text=REVIEW_PANEL_FOOTER)
    return e


async def refresh_review_panel(guild: discord.Guild):
    """Übersicht oben in #bewertungen aktualisieren, ohne die Bewertungen darunter zu löschen."""
    ch = find_channel(guild, "bewertungen")
    if not ch:
        return
    embed = await review_panel_embed()
    try:
        async for m in ch.history(limit=20, oldest_first=True):
            if m.author.id != guild.me.id or not m.embeds:
                continue
            first = m.embeds[0]
            is_panel = (first.footer and first.footer.text == REVIEW_PANEL_FOOTER) or \
                       (first.title == "⭐ Bewertungen" and (first.description or "").startswith("Hier erscheinen"))
            if is_panel:
                await m.edit(embed=embed)
                return
        await ch.send(embed=embed)
    except discord.HTTPException:
        pass


class ReviewModal(discord.ui.Modal, title="Deine Bewertung"):
    comment = discord.ui.TextInput(label="Kommentar (optional)", style=discord.TextStyle.paragraph,
                                   required=False, max_length=500)

    def __init__(self, ticket, stars: int):
        super().__init__()
        self.ticket, self.stars = ticket, stars

    async def on_submit(self, interaction: discord.Interaction):
        rid = await pool.fetchval(
            """INSERT INTO reviews (ticket_id,user_id,stars,comment) VALUES ($1,$2,$3,$4)
               ON CONFLICT (ticket_id) DO NOTHING RETURNING id""",
            self.ticket["id"], interaction.user.id, self.stars, self.comment.value or None)
        if rid is None:
            return await interaction.response.send_message(
                "Du hast dieses Projekt bereits bewertet.", ephemeral=True)
        e = emb(f"{'⭐' * self.stars}  ({self.stars}/5)", self.comment.value or "*Kein Kommentar*")
        e.add_field(name="Projekt", value=self.ticket["project_type"] or "–")
        e.set_author(name=interaction.user.display_name,
                     icon_url=interaction.user.display_avatar.url)
        e.set_footer(text=f"{BRAND} • Bewertung #{rid}")
        ch = find_channel(interaction.guild, "bewertungen")
        if ch:
            try:  # Nachricht merken, damit sie beim Löschen der Bewertung mit verschwindet
                msg = await ch.send(embed=e)
                await pool.execute("UPDATE reviews SET message_id=$1 WHERE id=$2", msg.id, rid)
            except discord.HTTPException:
                pass
        await interaction.response.send_message("💛 Danke für deine Bewertung!", ephemeral=True)
        invalidate_site_cache()
        await refresh_review_panel(interaction.guild)


class StarsView(discord.ui.View):
    """Sterne wählen für /bewerten (außerhalb des Ticket-Channels)."""

    def __init__(self, ticket):
        super().__init__(timeout=180)
        self.ticket = ticket

    @discord.ui.select(placeholder="Sterne wählen (1–5)",
                       options=[discord.SelectOption(label="⭐" * i, value=str(i)) for i in range(5, 0, -1)])
    async def pick(self, interaction: discord.Interaction, select: discord.ui.Select):
        await interaction.response.send_modal(ReviewModal(self.ticket, int(select.values[0])))


class ReviewProjectSelect(discord.ui.Select):
    def __init__(self, rows):
        super().__init__(placeholder="Welches Projekt willst du bewerten?", options=[
            discord.SelectOption(label=(r["project_name"] or f"Projekt #{r['id']}")[:100],
                                 description=(r["project_type"] or "–")[:100], value=str(r["id"]))
            for r in rows[:25]])

    async def callback(self, interaction: discord.Interaction):
        ticket = await pool.fetchrow("SELECT * FROM tickets WHERE id=$1 AND user_id=$2",
                                     int(self.values[0]), interaction.user.id)
        if not ticket:
            return await interaction.response.send_message("❌ Projekt nicht gefunden.", ephemeral=True)
        await interaction.response.send_message(
            f"Wie zufrieden warst du mit **{ticket['project_name']}**?", view=StarsView(ticket), ephemeral=True)


class ReviewProjectView(discord.ui.View):
    def __init__(self, rows):
        super().__init__(timeout=180)
        self.add_item(ReviewProjectSelect(rows))


class ReviewView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.select(custom_id="volt:review:stars", placeholder="Sterne wählen (1–5)",
                       options=[discord.SelectOption(label="⭐" * i, value=str(i)) for i in range(5, 0, -1)])
    async def pick(self, interaction: discord.Interaction, select: discord.ui.Select):
        ticket = await get_ticket(interaction.channel.id)
        if not ticket or interaction.user.id != ticket["user_id"]:
            return await interaction.response.send_message(
                "❌ Nur der Kunde dieses Projekts kann bewerten.", ephemeral=True)
        await interaction.response.send_modal(ReviewModal(ticket, int(select.values[0])))


# ===============================================================
# VOLT-DESIGN
# Eigenes Icon-Set als Server-Emojis, Kanalnamen, Rollenfarben, Rollen-Icons
# und Banner. Läuft einmal nach einem Update mit neuer DESIGN_VERSION (oder
# per /design). Nichts wird gelöscht: bestehende Kanäle und Rollen werden nur
# umbenannt bzw. umgefärbt, fehlende Icons werden hochgeladen.
# ===============================================================
DESIGN_VERSION = "2026-11-12d"
ICON_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "web", "assets", "icons")
BANNER_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "web", "assets", "img", "discord-banner.png")
ICON_EMOJIS: dict[str, discord.Emoji] = {}   # Icon-Name (ohne „v_“) -> Server-Emoji
APP_EMOJIS: dict[str, discord.Emoji] = {}    # Icon-Name -> App-Emoji (gehört dem Bot, belegt keine Server-Plätze)


def icon_meta() -> dict:
    try:
        with open(os.path.join(ICON_DIR, "icons.json"), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {"order": [], "icons": {}}


def refresh_icon_map(guild: discord.Guild | None):
    if guild is None:
        return
    ICON_EMOJIS.clear()
    for e in guild.emojis:
        if e.name.startswith("v_"):
            ICON_EMOJIS[e.name[2:]] = e


def ic(key: str, fallback: str = "") -> str:
    """Icon als Emoji-Text für Embeds: Server-Emoji, sonst App-Emoji, sonst das normale Emoji."""
    e = ICON_EMOJIS.get(key) or APP_EMOJIS.get(key)
    return str(e) if e else fallback


def ic_emoji(key: str, fallback: str):
    """Icon für Buttons und Auswahlmenüs."""
    return ICON_EMOJIS.get(key) or APP_EMOJIS.get(key) or fallback


_app_emojis_synced = False


async def sync_app_emojis():
    """Alle Icons als App-Emojis hochladen (bis 2000 möglich) – so gibt es auch die Icons, für die auf dem
    Server kein Emoji-Platz mehr frei ist. Einmal pro Start, im Hintergrund."""
    global _app_emojis_synced
    if _app_emojis_synced:
        return
    _app_emojis_synced = True
    try:
        existing = {e.name: e for e in await bot.fetch_application_emojis()}
    except Exception as ex:
        print("App-Emojis nicht lesbar:", repr(ex))
        return
    for name, e in existing.items():
        if name.startswith("v_"):
            APP_EMOJIS[name[2:]] = e
    created = 0
    for key in icon_meta().get("order", []):
        if key in APP_EMOJIS:
            continue
        data = _icon_png(key)
        if data is None:
            continue
        try:
            APP_EMOJIS[key] = await bot.create_application_emoji(name=f"v_{key}", image=data)
            created += 1
        except discord.HTTPException as ex:
            print(f"App-Emoji v_{key} nicht hochgeladen:", ex)
        await asyncio.sleep(0.6)
    print(f"VOLT-Icons als App-Emojis: {len(APP_EMOJIS)} bereit, {created} neu")


def _icon_png(key: str) -> bytes | None:
    try:
        with open(os.path.join(ICON_DIR, "discord", f"v_{key}.png"), "rb") as f:
            return f.read()
    except OSError:
        return None


async def sync_icon_emojis(guild: discord.Guild) -> tuple[int, int]:
    """Lädt fehlende Icons als Server-Emojis hoch. Die wichtigsten zuerst (Logo, Ränge, Kanäle,
    Produkte, dann Module) und nur so viele, wie Emoji-Plätze frei sind."""
    refresh_icon_map(guild)
    free = guild.emoji_limit - sum(1 for e in guild.emojis if not e.animated)
    created = missing = 0
    for key in icon_meta().get("order", []):
        if key in ICON_EMOJIS:
            continue
        data = _icon_png(key)
        if free <= 0 or data is None:
            missing += 1
            continue
        try:
            emoji = await guild.create_custom_emoji(name=f"v_{key}", image=data, reason="VOLT Icon-Set")
            ICON_EMOJIS[key] = emoji
            created += 1
            free -= 1
        except discord.HTTPException as ex:
            print(f"Icon v_{key} nicht hochgeladen:", ex)
            missing += 1
    return created, missing


def _design_targets():
    """Aus STRUCTURE: Schlüsselwort -> neuer Name (Kategorien) und Kanalname ohne Emoji -> neuer Name."""
    cats, chans = {}, {}
    for cat_name, _, channels in STRUCTURE:
        cats[cat_name.split(" ", 1)[1]] = cat_name
        for entry in channels:
            if entry[1] == "text" and SEP in entry[0]:
                chans[entry[0].split(SEP, 1)[1]] = entry[0]
    cats["WARTELISTE"] = "🕓 WARTELISTE"
    return cats, chans


SEP_CHARS = re.compile(r"\s*[│|┃｜︱]\s*")   # alle Varianten von „|“ werden zu „・“
NAME_START = re.compile(r"^[^0-9a-zA-ZäöüÄÖÜß]+")   # Emoji und Trenner vor dem eigentlichen Namen
# Weitere eigene Kanäle auf dem VOLT-Server: Emoji passend zum Icon-Set
EXTRA_CHANNEL_EMOJI = {
    "fraktion-dashboard": "🏠", "volt-bot": "🤖", "volt-studio": "📺", "volt-studio-tester-chat": "🧪",
    "routen-manager": "📍", "fussball-manager": "⚽", "vorschläge": "💡", "chat": "💬", "preisliste": "🏷️",
    "kosten-übersicht": "💳", "changelogs": "📝", "ticket": "🎫", "backups": "🗃️", "to-do-liste": "📌",
    "Warteraum": "⏳", "VOLT · Werkstatt": "🛠️", "ATLAXX · Privat": "🔒", "Privat VC": "🔒",
}
# Weitere eigene Rollen: Emoji passend zum Icon-Set bzw. zur Website (💛 = Spenden)
EXTRA_ROLE_EMOJI = {"Spender": "💛", "Tester": "🧪", "Partner": "🤝"}


def swap_sep(name: str) -> str:
    return SEP_CHARS.sub(SEP, name)


async def apply_design(guild: discord.Guild) -> dict:
    st = {"kat": 0, "kanal": 0, "ticket": 0, "trenner": 0, "rollen": 0, "rollen_icons": 0, "banner": None,
          "fehler": 0, "andere": [], "andere_rollen": []}
    cats, chans = _design_targets()
    done: set[int] = set()   # in diesem Lauf schon geändert (der Cache kennt den neuen Namen erst etwas später)

    async def rename(obj, name, key):
        try:
            await obj.edit(name=name, reason="VOLT Design")
            st[key] += 1
            done.add(obj.id)
            if isinstance(obj, discord.TextChannel):
                rename_log[obj.id].append(time.time())
        except discord.HTTPException as ex:
            st["fehler"] += 1
            print(f"Design: {obj.name} nicht umbenannt:", ex)

    # Kategorien: Schlüsselwort im alten Namen entscheidet (die Ticket-Logik sucht nach denselben Wörtern)
    for c in guild.categories:
        for word, new in sorted(cats.items(), key=lambda kv: -len(kv[0])):
            if word in c.name.upper():
                if c.name != new:
                    await rename(c, new, "kat")
                break

    # Feste Kanäle: nur wenn der Name ohne Emoji/Trenner genau passt (Kunden-Kanäle bleiben unberührt)
    for ch in guild.text_channels:
        rest = NAME_START.sub("", ch.name)
        new = chans.get(rest)
        if new and ch.name != new:
            await rename(ch, new, "kanal")

    # Ticket-Kanäle: Status-Emoji + neuer Trenner
    ticket_ids = set()
    for t in await pool.fetch("SELECT channel_id, slug, status FROM tickets WHERE status <> 'deleted'"):
        ch = guild.get_channel(t["channel_id"])
        if not isinstance(ch, discord.TextChannel) or t["status"] not in STATUS or not t["slug"]:
            continue
        ticket_ids.add(ch.id)
        new = f"{STATUS[t['status']][0]}{SEP}{t['slug']}"
        if ch.name != new and not rename_wait(ch.id):
            await rename(ch, new, "ticket")

    # Alle übrigen Kanäle und Kategorien: eigene Kanäle bekommen ihr Emoji, jedes „|“ / „│“ wird zu „・“
    for ch in guild.channels:
        if ch.id in done:
            continue
        rest = NAME_START.sub("", ch.name)
        new = f"{EXTRA_CHANNEL_EMOJI[rest]}{SEP}{rest}" if rest in EXTRA_CHANNEL_EMOJI else swap_sep(ch.name)
        if new != ch.name and not rename_wait(ch.id):
            await rename(ch, new, "trenner")
        is_known = rest in chans or rest in EXTRA_CHANNEL_EMOJI
        if not isinstance(ch, discord.CategoryChannel) and ch.id not in ticket_ids and not is_known \
                and not ch.name.startswith(("👥 Mitglieder:", "⭐ Bewertungen:")) and "Status:" not in ch.name:
            st["andere"].append(new)

    # Rollen: Name (Emoji passend zum Icon-Set), Farbe aus der VOLT-Palette,
    # Rollen-Icons wenn der Server sie kann (Boost Stufe 2)
    icons_ok = "ROLE_ICONS" in guild.features
    for key, name, color, _, _ in ROLES:
        role = find_role(guild, key)
        if role is None or role >= guild.me.top_role:
            continue
        kw = {}
        if role.name != name:
            kw["name"] = name
        if role.colour.value != color:
            kw["colour"] = discord.Colour(color)
        if icons_ok:
            data = _icon_png(ROLE_ICON.get(key, ""))
            if data:
                kw["display_icon"] = data
        if kw:
            try:
                await role.edit(reason="VOLT Design", **kw)
                st["rollen"] += 1
                st["rollen_icons"] += 1 if "display_icon" in kw else 0
                done.add(role.id)
            except discord.HTTPException as ex:
                st["fehler"] += 1
                print(f"Design: Rolle {role.name} nicht geändert:", ex)
    # weitere Rollen mit „|“ im Namen
    own = role_names(*ROLE_NAMES)
    for role in guild.roles:
        if role.id in done or role.is_default() or role.managed or role >= guild.me.top_role:
            continue
        new = swap_sep(role.name)
        rest = NAME_START.sub("", role.name)
        if rest in EXTRA_ROLE_EMOJI:
            new = f"{EXTRA_ROLE_EMOJI[rest]} {rest}"
        elif role.name not in own:
            st["andere_rollen"].append(new)
        if new != role.name:
            try:
                await role.edit(name=new, reason="VOLT Design")
                st["rollen"] += 1
            except discord.HTTPException as ex:
                st["fehler"] += 1
                print(f"Design: Rolle {role.name} nicht umbenannt:", ex)

    # Server-Banner (geht erst ab Boost Stufe 2)
    if "BANNER" in guild.features:
        try:
            with open(BANNER_FILE, "rb") as f:
                await guild.edit(banner=f.read(), reason="VOLT Design")
            st["banner"] = "gesetzt"
        except (OSError, discord.HTTPException) as ex:
            st["banner"] = f"nicht gesetzt ({ex})"
    else:
        st["banner"] = "braucht Server-Boost Stufe 2"
    return st


async def run_design(guild: discord.Guild) -> str:
    created, missing = await sync_icon_emojis(guild)
    st = await apply_design(guild)
    await post_panels(guild)   # Panels mit den neuen Icons neu posten
    await set_setting("design_version", DESIGN_VERSION)
    await set_setting("panels_version", PANELS_VERSION)
    msg = (f"Icons: {created} hochgeladen, {len(ICON_EMOJIS)} aktiv"
           + (f", {missing} ohne freien Emoji-Platz" if missing else "") + "\n"
           f"Umbenannt: {st['kat']} Kategorien, {st['kanal']} Kanäle, {st['ticket']} Ticket-Kanäle, "
           f"{st['trenner']} weitere mit neuem Trenner\n"
           f"Rollen angepasst: {st['rollen']}" + (f" (davon {st['rollen_icons']} mit Icon)" if st['rollen_icons'] else "")
           + f"\nBanner: {st['banner']}" + (f"\nFehler: {st['fehler']}" if st["fehler"] else ""))
    print("VOLT-Design angewendet:\n" + msg)
    if st["andere"]:
        print("Weitere Kanäle (eigene Emojis bleiben):", " / ".join(st["andere"]))
    if st["andere_rollen"]:
        print("Weitere Rollen:", " / ".join(st["andere_rollen"]))
    await log(guild, "admin-logs", emb(f"{ic('volt', '⚡')} VOLT-Design angewendet", msg))
    return msg


# ===============================================================
# PANELS (Texte in den Channels)
# ===============================================================
RULES = (
    "**1.** Sei respektvoll. Kein Hass, keine Beleidigungen, keine Diskriminierung.\n"
    "**2.** Keine Fremdwerbung und keine fremden Discord-Einladungen.\n"
    "**3.** Kein Spam, keine Massen-Erwähnungen.\n"
    "**4.** Tickets nur für ernst gemeinte Anfragen.\n"
    "**5.** Teile **niemals** Bot-Tokens, Passwörter oder Zahlungsdaten.\n"
    "**6.** Halte dich an die Discord-Nutzungsbedingungen und Richtlinien.\n"
    "**7.** Den Anweisungen des Teams ist Folge zu leisten.\n\n"
    "Verstöße führen zu Verwarnung, Timeout oder Bann.\n"
    "Klicke im Channel **#verify** auf **Regeln akzeptieren**, um den Server freizuschalten."
)
PRODUCT_ICON = {"familien-dashboard": "familie", "fussball-manager": "fussball", "routen-system": "routen"}


def p_icon(p: dict) -> str:
    return ic(PRODUCT_ICON.get(p["key"], ""), p["emoji"])


def product_embed(p: dict) -> discord.Embed:
    e = discord.Embed(title=f"{p_icon(p)} {p['name']}", url=product_url(p["key"]),
                      description=f"**{p['tag']}** · {p['short']}\n\n" + "\n".join(f"⚡ {x}" for x in p["points"]) +
                      f"\n\n💛 **0 €** · Spenden freiwillig, klären wir auf Discord\n🔎 {p['demo']} auf **{SITE_LABEL}**",
                      color=BRAND_COLOR)
    e.set_image(url=f"{SITE_URL}/assets/img/products/{p['key']}.jpg?v=4")
    e.set_footer(text=BRAND)
    return e


def product_view(guild: discord.Guild, p: dict) -> discord.ui.View:
    v = discord.ui.View(timeout=None)
    v.add_item(discord.ui.Button(label="Vorschau ansehen", emoji="🔎", style=discord.ButtonStyle.link,
                                 url=product_url(p["key"])))
    order = find_channel(guild, "bestellen")
    if order:
        v.add_item(discord.ui.Button(label="Jetzt anfragen", emoji=ic_emoji("bestellen", "🛒"), style=discord.ButtonStyle.link,
                                     url=channel_url(guild, order)))
    return v


async def honeypot_embed() -> discord.Embed:
    n = await pool.fetchval("SELECT value FROM stats WHERE key='honeypot_bans'") or 0
    e = discord.Embed(
        title=f"{ic('autoban', ic('stop', '🚨'))} WICHTIGER HINWEIS",
        description=(
            "**Dieser Kanal dient lediglich dazu, gehackte Spam-Accounts automatisch zu bannen!**\n\n"
            "Das bedeutet:\n"
            "**Wer hier reinschreibt, wird ohne Möglichkeit auf Entbannung permanent von diesem Discord gebannt!**\n\n"
            f"{ic('stop', '🚫')} **ALSO NICHT HIER REINSCHREIBEN!!!** {ic('stop', '🚫')}\n\n"
            "Wer hier dennoch reinschreibt, ist selbst schuld."),
        color=0xFF4D5E)
    e.add_field(name=f"{ic('statistik', '📊')} Statistik",
                value=f"Bereits **{n}** gehackte Discord-Nutzer wurden durch dieses System gebannt.",
                inline=False)
    return e


async def refresh_honeypot_panel(guild: discord.Guild):
    ch = find_channel(guild, "nicht-schreiben")
    if not ch:
        return
    async for m in ch.history(limit=20):
        if m.author.id == guild.me.id and m.embeds:
            await m.edit(embed=await honeypot_embed())
            return


async def purge_own(ch, limit: int = 50):
    try:
        await ch.purge(limit=limit, check=lambda m: m.author.id == ch.guild.me.id)
    except discord.HTTPException:
        pass


async def send_panel(guild: discord.Guild, key: str, embed: discord.Embed, view=None):
    ch = find_channel(guild, key)
    if not ch:
        return
    await purge_own(ch)
    await ch.send(embed=embed, view=view)


def order_embed(guild: discord.Guild) -> discord.Embed:
    lines = [f"{p_icon(p)} **{p['name']}** · {p['tag']}\n{p['short']} [Vorschau ansehen]({product_url(p['key'])})"
             for p in PRODUCTS]
    lines.append("💡 **Individuelle Anfrage**\nEtwas anderes oder eine Erweiterung für dein System.")
    e = emb(f"{ic('bestellen', '🛒')} Bestellen",
            "Wähle unten dein Produkt aus und beschreib deine Wünsche. Dein Ticket sieht nur du und der Owner.\n\n"
            + "\n\n".join(lines) +
            "\n\n🌴 **Für Narco City kostenlos.** Spenden sind freiwillig und werden im Ticket geklärt.\n"
            "🌐 **Projekte für andere Server** können wir leider nicht annehmen.\n\n"
            "❔ **Nur eine Frage?** Klick auf **Support / Frage**. Ohne Fragebogen, egal von welchem Server – "
            "schreib einfach dein Anliegen rein.")
    return e


async def post_products_panel(guild: discord.Guild):
    ch = find_channel(guild, "produkte") or find_channel(guild, "preisliste")
    if not ch:
        return
    await purge_own(ch)
    order = find_channel(guild, "bestellen")
    head = emb(f"{ic('produkte', '🛍️')} Unsere Produkte",
               "Jedes Produkt besteht aus Dashboard und eigenem Discord-Bot und wird für eure Familie eingerichtet.\n"
               f"Zu jedem Produkt gibt es eine **Vorschau zum Durchklicken** auf **[{SITE_LABEL}]({SITE_URL}/#produkte)**.\n\n"
               "🌴 **Für Narco City kostenlos** · Spenden freiwillig, klären wir auf Discord\n"
               + (f"🛒 Anfragen in {order.mention}" if order else "🛒 Anfragen per Ticket"))
    await ch.send(embed=head)
    for p in PRODUCTS:
        await ch.send(embed=product_embed(p), view=product_view(guild, p))


async def post_website_panel(guild: discord.Guild):
    ch = find_channel(guild, "website") or find_channel(guild, "webseite")
    if not ch:
        return
    e = emb(f"{ic('website', '🌐')} {SITE_LABEL}",
            "Die Website von **VOLT – Discord Solutions**.\n\n"
            "📊 **Live-Status:** Werkbank, Wartezeit, Auslastung und Systemstatus\n"
            "🔎 **Alle Produkte** mit Vorschau zum Durchklicken\n"
            "👪 **Familien-Dashboard** mit klickbarer Demo\n"
            "⭐ **Bewertungen** von Kunden\n"
            "🇩🇪 **Made in Germany** · für Narco City kostenlos\n\n"
            f"👉 **{SITE_URL}**")
    e.set_image(url=f"{SITE_URL}/assets/img/volt-banner-og.jpg?v=4")
    v = volt_link_view()
    v.add_item(discord.ui.Button(label="Live-Status", emoji="📊", style=discord.ButtonStyle.link,
                                 url=f"{SITE_URL}/#status", row=1))
    await purge_own(ch)
    await ch.send(embed=e, view=v)


async def post_panels(guild: discord.Guild):
    await send_panel(guild, "regeln", emb(f"{ic('regeln', '📜')} Serverregeln", RULES))
    await send_panel(guild, "verify", emb(f"{ic('verify', '✅')} Verifizierung",
                                          "Lies die Regeln in #regeln und klicke unten, um sie zu akzeptieren."),
                     VerifyView())
    # Willkommen: kein fester Kasten mehr, dort stehen jetzt die Willkommenskarten neuer Mitglieder
    await cleanup_old_welcome_panel(guild)
    hp = find_channel(guild, "nicht-schreiben")
    if hp:
        try:  # Schreibrecht fuer alle setzen, damit die Falle funktioniert
            await hp.edit(overwrites=build_overwrites(guild, "honeypot"))
        except discord.HTTPException:
            pass
    await send_panel(guild, "nicht-schreiben", await honeypot_embed())
    await update_monitor(guild, fresh=True)        # Uptime-Kanal (oder server-status)
    await update_status_panel(guild, fresh=True)   # server-status, falls es einen eigenen Uptime-Kanal gibt
    await post_website_panel(guild)
    await post_products_panel(guild)               # Produkte-Kanal (früher Preisliste)
    kosten = find_channel(guild, "kosten")         # Kosten-Übersicht ist überflüssig: Kanal wird geleert
    if kosten:
        await purge_own(kosten)
    await send_panel(guild, "faq", emb(f"{ic('faq', '❓')} Häufige Fragen",
                                       "Wähle unten eine Frage aus.\nDeine Frage ist nicht dabei? Öffne ein **Support-Ticket**, "
                                       "ohne Fragebogen und egal von welchem Server."), FaqView())
    await send_panel(guild, "bestellen", order_embed(guild), TicketPanelView())
    # Nicht purgen: sonst würden die geposteten Bewertungen mitgelöscht
    await refresh_review_panel(guild)


# ===============================================================
# WARNS / MODERATION
# ===============================================================
async def add_warn(guild: discord.Guild, member: discord.Member, mod_id, reason: str):
    await pool.execute("INSERT INTO warns (user_id,mod_id,reason) VALUES ($1,$2,$3)",
                       member.id, mod_id, reason)
    count = await pool.fetchval("SELECT count(*) FROM warns WHERE user_id=$1", member.id)
    action = "–"
    try:
        if count >= 5:
            await guild.ban(member, reason=f"5 Warns: {reason}")
            action = "🔨 Bann (5 Warns)"
        elif count >= 3:
            await member.timeout(dt.timedelta(days=1), reason=f"{count} Warns")
            action = "⏳ Timeout 24h (ab 3 Warns)"
    except discord.HTTPException:
        action = "⚠️ Aktion fehlgeschlagen (Rechte?)"
    await log(guild, "mod-logs", emb("⚠️ Warn", f"{member.mention} · Warn #{count}\nGrund: {reason}\nAktion: {action}",
                                   0xE67E22))
    return count, action


def team_check():
    async def pred(interaction: discord.Interaction):
        return isinstance(interaction.user, discord.Member) and has_team_role(interaction.user)
    return app_commands.check(pred)


def owner_check():
    async def pred(interaction: discord.Interaction):
        return interaction.user.id == OWNER_ID
    return app_commands.check(pred)


@bot.tree.error
async def on_app_error(interaction: discord.Interaction, error):
    if isinstance(error, app_commands.CheckFailure):
        msg = "❌ Keine Berechtigung."
    elif isinstance(error, app_commands.CommandNotFound):
        msg = ("❌ Diesen Befehl gibt es nicht mehr. Discord aktualisiert die Befehlsliste gerade – "
               "drück Strg+R (am Handy App neu starten) und nutze /hilfe.")
    else:
        msg = f"❌ Fehler: {error}"
        print("Command-Fehler:", repr(error))
    if interaction.response.is_done():
        await interaction.followup.send(msg, ephemeral=True)
    else:
        await interaction.response.send_message(msg, ephemeral=True)


@bot.tree.command(name="warn", description="User verwarnen (3 Warns = Timeout, 5 = Bann)")
@app_commands.guild_only()
@app_commands.default_permissions(moderate_members=True)
@team_check()
async def warn_cmd(interaction: discord.Interaction, user: discord.Member, grund: str):
    if not can_moderate(interaction.user, user):
        return await interaction.response.send_message("❌ Diesen User kannst du nicht verwarnen.", ephemeral=True)
    count, action = await add_warn(interaction.guild, user, interaction.user.id, grund)
    try:
        await user.send(f"⚠️ Du wurdest auf **{interaction.guild.name}** verwarnt: {grund} (Warn #{count})")
    except discord.HTTPException:
        pass
    await interaction.response.send_message(f"✅ {user.mention} verwarnt (Warn #{count}). {action}", ephemeral=True)


@bot.tree.command(name="warns", description="Warns eines Users anzeigen")
@app_commands.guild_only()
@app_commands.default_permissions(moderate_members=True)
@team_check()
async def warns_cmd(interaction: discord.Interaction, user: discord.Member):
    rows = await pool.fetch("SELECT * FROM warns WHERE user_id=$1 ORDER BY id", user.id)
    if not rows:
        return await interaction.response.send_message("Keine Warns. ✅", ephemeral=True)
    text = "\n".join(f"#{i+1} · {str(r['created_at'])[:10]} · {r['reason']}" for i, r in enumerate(rows))
    await interaction.response.send_message(embed=emb(f"Warns von {user.display_name}", text), ephemeral=True)


@bot.tree.command(name="clearwarns", description="Alle Warns eines Users löschen")
@app_commands.guild_only()
@app_commands.default_permissions(moderate_members=True)
@team_check()
async def clearwarns_cmd(interaction: discord.Interaction, user: discord.Member):
    await pool.execute("DELETE FROM warns WHERE user_id=$1", user.id)
    await interaction.response.send_message(f"✅ Warns von {user.mention} gelöscht.", ephemeral=True)
    await log(interaction.guild, "mod-logs", emb("🧹 Warns gelöscht", f"{user.mention} durch {interaction.user.mention}"))


@bot.tree.command(name="timeout", description="User in den Timeout schicken")
@app_commands.guild_only()
@app_commands.default_permissions(moderate_members=True)
@team_check()
@app_commands.describe(minuten="Dauer in Minuten (max. 40320)")
async def timeout_cmd(interaction: discord.Interaction, user: discord.Member, minuten: int, grund: str = "–"):
    if not can_moderate(interaction.user, user):
        return await interaction.response.send_message("❌ Nicht möglich.", ephemeral=True)
    await user.timeout(dt.timedelta(minutes=max(1, min(minuten, 40320))), reason=grund)
    await interaction.response.send_message(f"✅ {user.mention} {minuten} Min. im Timeout.", ephemeral=True)
    await log(interaction.guild, "mod-logs",
              emb("⏳ Timeout", f"{user.mention} · {minuten} Min · {grund}\nDurch {interaction.user.mention}"))


@bot.tree.command(name="kick", description="User kicken")
@app_commands.guild_only()
@app_commands.default_permissions(moderate_members=True)
@team_check()
async def kick_cmd(interaction: discord.Interaction, user: discord.Member, grund: str = "–"):
    if not can_moderate(interaction.user, user):
        return await interaction.response.send_message("❌ Nicht möglich.", ephemeral=True)
    await user.kick(reason=grund)
    await interaction.response.send_message(f"✅ {user} gekickt.", ephemeral=True)
    await log(interaction.guild, "mod-logs",
              emb("👢 Kick", f"{user} · {grund}\nDurch {interaction.user.mention}"))


@bot.tree.command(name="ban", description="User bannen")
@app_commands.guild_only()
@app_commands.default_permissions(moderate_members=True)
@team_check()
async def ban_cmd(interaction: discord.Interaction, user: discord.Member, grund: str = "–"):
    if not can_moderate(interaction.user, user):
        return await interaction.response.send_message("❌ Nicht möglich.", ephemeral=True)
    await interaction.guild.ban(user, reason=grund)
    await interaction.response.send_message(f"✅ {user} gebannt.", ephemeral=True)
    await log(interaction.guild, "mod-logs",
              emb("🔨 Bann", f"{user} · {grund}\nDurch {interaction.user.mention}", 0xE74C3C))


@bot.tree.command(name="unban", description="User per ID entbannen")
@app_commands.guild_only()
@app_commands.default_permissions(moderate_members=True)
@team_check()
async def unban_cmd(interaction: discord.Interaction, user_id: str):
    try:
        await interaction.guild.unban(discord.Object(id=int(user_id)))
    except (ValueError, discord.HTTPException):
        return await interaction.response.send_message("❌ ID ungültig oder nicht gebannt.", ephemeral=True)
    await interaction.response.send_message("✅ Entbannt.", ephemeral=True)
    await log(interaction.guild, "mod-logs", emb("♻️ Entbannt", f"ID {user_id} durch {interaction.user.mention}"))


# ---- Blacklist ------------------------------------------------
blacklist = app_commands.Group(name="blacklist", description="Ticket-Blacklist (nur Owner)",
                               guild_only=True, default_permissions=discord.Permissions(administrator=True))


@blacklist.command(name="add", description="User für eine bestimmte Zeit von Tickets sperren")
@app_commands.describe(user="Wer gesperrt wird", dauer="Wie lange die Sperre gilt",
                       grund="Grund – bekommt der User per DM und beim Öffnen eines Tickets angezeigt")
@app_commands.choices(dauer=[app_commands.Choice(name=n, value=d) for n, d in BL_DURATIONS])
@owner_check()
async def bl_add(interaction: discord.Interaction, user: discord.User, dauer: app_commands.Choice[int], grund: str):
    await interaction.response.defer(ephemeral=True)
    until = await blacklist_user(interaction.guild, user, dauer.value, grund, interaction.user)
    await interaction.followup.send(f"🚫 {user.mention} ist {bl_until_text(until)} für Tickets gesperrt.\n"
                                    f"**Grund:** {grund}", ephemeral=True)


@blacklist.command(name="remove", description="Sperre aufheben")
@owner_check()
async def bl_remove(interaction: discord.Interaction, user: discord.User):
    await pool.execute("DELETE FROM blacklist WHERE user_id=$1", user.id)
    await interaction.response.send_message(f"✅ {user} entsperrt.", ephemeral=True)
    await log(interaction.guild, "mod-logs", emb("✅ Ticket-Sperre aufgehoben", f"{user.mention}"))


@blacklist.command(name="list", description="Gesperrte User anzeigen")
@owner_check()
async def bl_list(interaction: discord.Interaction):
    await pool.execute("DELETE FROM blacklist WHERE until IS NOT NULL AND until<=$1", int(time.time()))
    rows = await pool.fetch("SELECT * FROM blacklist ORDER BY until IS NULL, until")
    text = "\n".join(f"<@{r['user_id']}> · {bl_until_text(r['until'])}\n└ {r['reason'] or '–'}" for r in rows) or "Leer."
    await interaction.response.send_message(embed=emb("🚫 Blacklist", text), ephemeral=True)


bot.tree.add_command(blacklist)


# ---- Extras ---------------------------------------------------
@bot.tree.command(name="projekt", description="Status deiner Projekte anzeigen")
@app_commands.guild_only()
async def projekt_cmd(interaction: discord.Interaction):
    rows = await pool.fetch(
        "SELECT * FROM tickets WHERE user_id=$1 AND status<>'deleted' ORDER BY id DESC LIMIT 10",
        interaction.user.id)
    if not rows:
        return await interaction.response.send_message("Du hast noch keine Projekte.", ephemeral=True)
    lines = []
    for r in rows:
        emoji, _, label = STATUS.get(r["status"], ("❔", "", r["status"]))
        lines.append(f"{emoji} **{r['project_name']}** · {label} · <#{r['channel_id']}>"
                     + (f" · {r['price']}" if r["price"] else ""))
    await interaction.response.send_message(embed=emb("📋 Deine Projekte", "\n".join(lines)), ephemeral=True)


@bot.tree.command(name="benachrichtigen", description="Einem User eine DM-Benachrichtigung schicken (Team)")
@app_commands.guild_only()
@app_commands.default_permissions(moderate_members=True)
@team_check()
@app_commands.describe(user="Wer soll die DM bekommen?", nachricht="Was soll in der DM stehen?")
async def notify_cmd(interaction: discord.Interaction, user: discord.Member,
                     nachricht: app_commands.Range[str, 1, 1000]):
    if user.bot:
        return await interaction.response.send_message("❌ Bots kann man nicht benachrichtigen.", ephemeral=True)
    # Im Ticket des Users benutzt -> dieses Ticket verlinken, sonst sein neuestes offenes Ticket
    ticket = await get_ticket(interaction.channel.id)
    if not ticket or ticket["user_id"] != user.id:
        ticket = await pool.fetchrow(
            "SELECT * FROM tickets WHERE user_id=$1 AND status NOT IN ('archived','rejected','deleted') "
            "ORDER BY id DESC LIMIT 1", user.id)
    e = emb("📬 Nachricht vom VOLT-Team", nachricht)
    e.set_author(name=f"{interaction.user.display_name} · VOLT-Team", icon_url=interaction.user.display_avatar.url)
    view = None
    if ticket:
        e.add_field(name="Dein Ticket", value=f"#{ticket['id']} · {ticket['project_name']}", inline=False)
        view = ticket_link_view(interaction.guild.id, ticket["channel_id"])
    try:
        await user.send(embed=e, view=view)
    except discord.HTTPException:
        return await interaction.response.send_message(
            f"❌ {user.mention} hat DMs geschlossen. Schreib am besten direkt im Ticket.", ephemeral=True)
    await interaction.response.send_message(
        f"✅ DM an {user.mention} gesendet" + (" (mit Link zum Ticket)." if ticket else "."), ephemeral=True)
    await log(interaction.guild, "ticket-logs", emb(
        "📬 DM gesendet", f"An {user.mention} durch {interaction.user.mention}\n\n{nachricht[:500]}"))


@bot.tree.command(name="dm-benachrichtigungen",
                  description="DMs bei Antworten in deinem Ticket an- oder ausschalten")
@app_commands.guild_only()
@app_commands.describe(status="an oder aus")
@app_commands.choices(status=[app_commands.Choice(name="an", value="an"),
                              app_commands.Choice(name="aus", value="aus")])
async def dm_toggle_cmd(interaction: discord.Interaction, status: app_commands.Choice[str]):
    if status.value == "aus":
        await pool.execute("INSERT INTO dm_optout (user_id) VALUES ($1) ON CONFLICT (user_id) DO NOTHING",
                           interaction.user.id)
        msg = "🔕 Du bekommst keine automatischen DMs mehr, wenn das Team in deinem Ticket antwortet."
    else:
        await pool.execute("DELETE FROM dm_optout WHERE user_id=$1", interaction.user.id)
        msg = "🔔 An! Du bekommst eine DM mit Link, sobald das Team in deinem Ticket antwortet."
    await interaction.response.send_message(msg, ephemeral=True)


# ---- Werkbank & Zeit (nur Owner, im Ticket) ---------------------
@bot.tree.command(name="platz", description="Ticket auf die Werkbank legen, Zeit startet (nur Owner, im Ticket)")
@app_commands.guild_only()
@app_commands.default_permissions(administrator=True)
@owner_check()
@app_commands.describe(nummer="Platz 1, Platz 2 oder frei")
@app_commands.choices(nummer=[app_commands.Choice(name="Platz 1", value="1"),
                              app_commands.Choice(name="Platz 2", value="2"),
                              app_commands.Choice(name="frei (von der Werkbank nehmen)", value="frei")])
async def platz_cmd(interaction: discord.Interaction, nummer: app_commands.Choice[str]):
    ticket = await get_ticket(interaction.channel.id)
    if not ticket or ticket["status"] == "deleted":
        return await interaction.response.send_message("❌ Das geht nur in einem Ticket.", ephemeral=True)
    if nummer.value == "frei":
        await free_slot(ticket["id"])
        total = await work_seconds(ticket["id"])
        await interaction.response.send_message(
            f"✅ **{ticket['project_name']}** ist von der Werkbank genommen, Zeit gestoppt. "
            f"Arbeitszeit bisher: **{fmt_dur(total)}**", ephemeral=True)
        return await log(interaction.guild, "ticket-logs", emb(
            "🧰 Platz frei", f"#{ticket['id']} · {ticket['project_name']} · bisher {fmt_dur(total)}"))
    if ticket["status"] in ("open", "offered", "waiting"):
        return await interaction.response.send_message(
            "❌ Erst muss der Kunde bestätigen, dann kommt das Projekt auf die Werkbank.", ephemeral=True)
    if ticket["status"] in ("archived", "rejected"):
        return await interaction.response.send_message("❌ Dieses Ticket ist geschlossen.", ephemeral=True)
    n = int(nummer.value)
    if n > MAX_PARALLEL:
        return await interaction.response.send_message(f"❌ Es gibt nur {MAX_PARALLEL} Plätze.", ephemeral=True)

    await interaction.response.defer(ephemeral=True)
    moved = ""
    other = await pool.fetchrow(
        "SELECT * FROM tickets WHERE slot=$1 AND id<>$2 AND status NOT IN ('archived','rejected','deleted')",
        n, ticket["id"])
    if other:
        await free_slot(other["id"])
        moved = (f"\n↪️ **{other['project_name']}** (#{other['id']}) lag dort und ist jetzt wieder in der "
                 f"Warteschlange, seine Zeit ist gestoppt.")
    await pool.execute("UPDATE tickets SET slot=$1 WHERE id=$2", n, ticket["id"])
    if ticket["status"] == "paused":
        await apply_status(interaction.guild, interaction.channel, ticket, "progress")
    await start_timer(ticket["id"])
    invalidate_site_cache()
    total = await work_seconds(ticket["id"])

    member = interaction.guild.get_member(ticket["user_id"])
    await interaction.channel.send(
        content=member.mention if member else None,
        embed=emb("🔧 Ich arbeite jetzt an deinem Projekt",
                  f"**{ticket['project_name']}** liegt auf **Platz {n}** der Werkbank. "
                  f"Den Stand siehst du auch live auf der Website."))
    await notify_ticket_owner(interaction.guild, ticket, "🔧 Dein Projekt ist auf der Werkbank",
                              f"Ich arbeite jetzt an **{ticket['project_name']}** (Platz {n}).",
                              force=True, author=interaction.user)
    await log(interaction.guild, "ticket-logs", emb(
        f"🧰 Platz {n} belegt", f"#{ticket['id']} · {ticket['project_name']} · Zeit läuft (bisher {fmt_dur(total)})"))
    await interaction.followup.send(f"✅ Platz {n} belegt, die Zeit läuft (bisher {fmt_dur(total)}).{moved}",
                                    ephemeral=True)


@bot.tree.command(name="zeit", description="Arbeitszeit im Ticket pausieren, weiterlaufen lassen oder anzeigen (nur Owner)")
@app_commands.guild_only()
@app_commands.default_permissions(administrator=True)
@owner_check()
@app_commands.choices(aktion=[app_commands.Choice(name="pause", value="pause"),
                              app_commands.Choice(name="weiter", value="weiter"),
                              app_commands.Choice(name="anzeigen", value="anzeigen")])
async def zeit_cmd(interaction: discord.Interaction, aktion: app_commands.Choice[str]):
    ticket = await get_ticket(interaction.channel.id)
    if not ticket or ticket["status"] == "deleted":
        return await interaction.response.send_message("❌ Das geht nur in einem Ticket.", ephemeral=True)
    tid = ticket["id"]
    running = await timer_running(tid)
    if aktion.value == "pause":
        if not running:
            return await interaction.response.send_message("⏸️ Die Zeit läuft gerade nicht.", ephemeral=True)
        await stop_timer(tid)
        invalidate_site_cache()
        msg = f"⏸️ Zeit gestoppt. Gesamt bisher: **{fmt_dur(await work_seconds(tid))}**"
    elif aktion.value == "weiter":
        if not ticket["slot"]:
            return await interaction.response.send_message(
                "❌ Leg das Ticket erst mit `/platz 1` oder `/platz 2` auf die Werkbank.", ephemeral=True)
        if running:
            return await interaction.response.send_message("▶️ Die Zeit läuft schon.", ephemeral=True)
        await start_timer(tid)
        invalidate_site_cache()
        msg = f"▶️ Zeit läuft weiter. Gesamt bisher: **{fmt_dur(await work_seconds(tid))}**"
    else:
        sessions = await pool.fetchval("SELECT count(*) FROM work_sessions WHERE ticket_id=$1", tid) or 0
        msg = (f"⏱️ **{ticket['project_name']}**\nArbeitszeit: **{fmt_dur(await work_seconds(tid))}** "
               f"in {sessions} Abschnitt{'en' if sessions != 1 else ''}\n"
               f"Werkbank: {('Platz ' + str(ticket['slot'])) if ticket['slot'] else 'nicht belegt'} · "
               f"Uhr: {'läuft ▶️' if running else 'steht ⏸️'}")
    await interaction.response.send_message(msg, ephemeral=True)


@bot.tree.command(name="bewertung-anfragen", description="Kunden um eine Bewertung bitten (nur Owner)")
@app_commands.guild_only()
@app_commands.default_permissions(administrator=True)
@owner_check()
@app_commands.choices(ziel=[app_commands.Choice(name="dieses Ticket", value="dieses"),
                            app_commands.Choice(name="alle laufenden Projekte ohne Bewertung", value="alle")])
async def review_request_cmd(interaction: discord.Interaction, ziel: app_commands.Choice[str]):
    if ziel.value == "dieses":
        ticket = await get_ticket(interaction.channel.id)
        if not ticket:
            return await interaction.response.send_message("❌ Das geht nur in einem Ticket.", ephemeral=True)
        if ticket["status"] not in ("running", "maintenance", "archived"):
            return await interaction.response.send_message(
                "❌ Bewerten geht erst, wenn das Projekt läuft.", ephemeral=True)
        await interaction.response.defer(ephemeral=True)
        ok = await request_review(interaction.guild, interaction.channel, ticket, by=interaction.user)
        return await interaction.followup.send(
            "✅ Bewertungs-Anfrage gesendet." if ok else "Dieses Projekt ist schon bewertet.", ephemeral=True)
    await interaction.response.defer(ephemeral=True)
    rows = await pool.fetch(
        "SELECT * FROM tickets WHERE status IN ('running','maintenance') "
        "AND id NOT IN (SELECT ticket_id FROM reviews WHERE ticket_id IS NOT NULL)")
    sent = 0
    for t in rows:
        ch = interaction.guild.get_channel(t["channel_id"])
        if ch and await request_review(interaction.guild, ch, t, by=interaction.user):
            sent += 1
    await interaction.followup.send(f"✅ {sent} von {len(rows)} laufenden Projekten um eine Bewertung gebeten.",
                                    ephemeral=True)


@bot.tree.command(name="bewerten", description="Ein fertiges Projekt bewerten (1–5 Sterne)")
@app_commands.guild_only()
async def bewerten_cmd(interaction: discord.Interaction):
    rows = await pool.fetch(
        """SELECT t.* FROM tickets t LEFT JOIN reviews r ON r.ticket_id = t.id
           WHERE t.user_id=$1 AND r.id IS NULL AND (
             t.status IN ('running','maintenance') OR
             (t.status='archived' AND (t.accepted_at IS NOT NULL OR t.live_at IS NOT NULL OR t.price IS NOT NULL)))
           ORDER BY t.id DESC LIMIT 25""",
        interaction.user.id)
    if not rows:
        return await interaction.response.send_message(
            "Du hast kein laufendes oder fertiges Projekt, das noch nicht bewertet ist.", ephemeral=True)
    await interaction.response.send_message("Welches Projekt möchtest du bewerten?",
                                            view=ReviewProjectView(rows), ephemeral=True)


# ---- Bewertungen verwalten (nur Owner) -------------------------
async def delete_review(guild: discord.Guild, rid: int, by: discord.abc.User):
    """Löscht eine Bewertung aus der Datenbank, die Nachricht in #bewertungen und aktualisiert Website + Übersicht."""
    row = await pool.fetchrow(
        "SELECT r.*, t.project_name FROM reviews r LEFT JOIN tickets t ON t.id = r.ticket_id WHERE r.id=$1", rid)
    if not row:
        return None, False
    await pool.execute("DELETE FROM reviews WHERE id=$1", rid)
    invalidate_site_cache()
    msg_gone = False
    ch = find_channel(guild, "bewertungen")
    if ch:
        try:
            if row["message_id"]:
                await (await ch.fetch_message(row["message_id"])).delete()
                msg_gone = True
            else:  # ältere Bewertungen: Nachricht über die Nummer im Footer suchen
                async for m in ch.history(limit=300):
                    if m.author.id == guild.me.id and m.embeds and \
                            (m.embeds[0].footer.text or "").endswith(f"Bewertung #{rid}"):
                        await m.delete()
                        msg_gone = True
                        break
        except discord.HTTPException:
            pass
    await refresh_review_panel(guild)
    await log(guild, "mod-logs", emb("🗑️ Bewertung gelöscht",
                                     f"#{rid} · {row['stars']}/5 · {row['project_name'] or 'Projekt'}\n"
                                     f"Kommentar: {(row['comment'] or '–')[:300]}\nDurch {by.mention}"))
    return row, msg_gone


def review_line(r) -> str:
    text = (r["comment"] or "ohne Kommentar").replace("\n", " ")
    return f"#{r['id']} · {'⭐' * int(r['stars'] or 0)} · {r['project_name'] or 'Projekt'} · {text}"


class ReviewDeleteConfirm(discord.ui.View):
    def __init__(self, rid: int):
        super().__init__(timeout=120)
        self.rid = rid

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != OWNER_ID:
            await interaction.response.send_message("❌ Keine Berechtigung.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="Ja, löschen", emoji="🗑️", style=discord.ButtonStyle.danger)
    async def yes(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        row, gone = await delete_review(interaction.guild, self.rid, interaction.user)
        if not row:
            text = f"❌ Bewertung #{self.rid} gibt es nicht mehr."
        else:
            text = (f"✅ Bewertung #{self.rid} ({row['stars']}/5) gelöscht. Website und Übersicht sind aktualisiert"
                    + (", die Nachricht in #bewertungen ist auch weg." if gone else
                       ". Die Nachricht in #bewertungen habe ich nicht gefunden, lösch sie bitte selbst."))
        await interaction.edit_original_response(content=text, embed=None, view=None)
        self.stop()

    @discord.ui.button(label="Abbrechen", style=discord.ButtonStyle.secondary)
    async def no(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(content="Abgebrochen, nichts gelöscht.", embed=None, view=None)
        self.stop()


async def ask_delete_review(interaction: discord.Interaction, rid: int):
    row = await pool.fetchrow(
        "SELECT r.*, t.project_name FROM reviews r LEFT JOIN tickets t ON t.id = r.ticket_id WHERE r.id=$1", rid)
    if not row:
        return await interaction.response.send_message(f"❌ Bewertung #{rid} gibt es nicht.", ephemeral=True)
    e = emb(f"🗑️ Bewertung #{rid} löschen?", review_line(row)[:4000])
    member = interaction.guild.get_member(row["user_id"]) if row["user_id"] else None
    e.add_field(name="Von", value=member.mention if member else f"User-ID {row['user_id']}")
    e.add_field(name="Datum", value=str(row["created_at"] or "–")[:16])
    await interaction.response.send_message(
        "Wird aus der Datenbank, aus #bewertungen und von der Website entfernt.",
        embed=e, view=ReviewDeleteConfirm(rid), ephemeral=True)


async def review_autocomplete(interaction: discord.Interaction, current: str):
    rows = await pool.fetch(
        "SELECT r.id, r.stars, r.comment, t.project_name FROM reviews r "
        "LEFT JOIN tickets t ON t.id = r.ticket_id ORDER BY r.id DESC LIMIT 100")
    cur = (current or "").lower().lstrip("#")
    out = []
    for r in rows:
        line = review_line(r)
        if cur and cur not in line.lower():
            continue
        out.append(app_commands.Choice(name=line[:100], value=int(r["id"])))
        if len(out) == 25:
            break
    return out


@bot.tree.command(name="bewertung-loeschen", description="Eine Bewertung löschen (nur Owner)")
@app_commands.guild_only()
@app_commands.default_permissions(administrator=True)
@owner_check()
@app_commands.describe(bewertung="Tippen zum Suchen: Nummer, Sterne, Projekt oder Kommentar")
@app_commands.autocomplete(bewertung=review_autocomplete)
async def review_delete_cmd(interaction: discord.Interaction, bewertung: int):
    await ask_delete_review(interaction, bewertung)


@bot.tree.command(name="bewertungen-liste", description="Alle Bewertungen mit Nummer anzeigen (nur Owner)")
@app_commands.guild_only()
@app_commands.default_permissions(administrator=True)
@owner_check()
async def review_list_cmd(interaction: discord.Interaction):
    rows = await pool.fetch(
        "SELECT r.*, t.project_name FROM reviews r LEFT JOIN tickets t ON t.id = r.ticket_id ORDER BY r.id DESC LIMIT 25")
    if not rows:
        return await interaction.response.send_message("Noch keine Bewertungen.", ephemeral=True)
    lines = [review_line(r)[:150] for r in rows]
    count, avg, _ = await review_summary()
    e = emb(f"⭐ Bewertungen · {avg:.1f}/5 aus {count}", "\n".join(lines)[:4000])
    e.set_footer(text="Löschen: /bewertung-loeschen oder Rechtsklick auf die Bewertung → Apps → Bewertung löschen")
    await interaction.response.send_message(embed=e, ephemeral=True)


@bot.tree.context_menu(name="Bewertung löschen")
@app_commands.guild_only()
@app_commands.default_permissions(administrator=True)
async def review_delete_ctx(interaction: discord.Interaction, message: discord.Message):
    if interaction.user.id != OWNER_ID:
        return await interaction.response.send_message("❌ Keine Berechtigung.", ephemeral=True)
    rid = None
    if message.embeds:
        m = re.search(r"Bewertung #(\d+)", message.embeds[0].footer.text or "")
        if m:
            rid = int(m.group(1))
    if rid is None:
        rid = await pool.fetchval("SELECT id FROM reviews WHERE message_id=$1", message.id)
    if rid is None:
        return await interaction.response.send_message(
            "❌ Das ist keine Bewertung, die ich zuordnen kann. Nutze /bewertungen-liste.", ephemeral=True)
    await ask_delete_review(interaction, rid)


@bot.tree.command(name="spenden", description="Freiwillig unterstützen")
async def spenden_cmd(interaction: discord.Interaction):
    if DONATION_URL:
        return await interaction.response.send_message(
            embed=emb("💛 Danke!", "Spenden sind komplett freiwillig und helfen, den Service für Narco City kostenlos zu halten."),
            view=donate_view(), ephemeral=True)
    order = find_channel(interaction.guild, "bestellen") if interaction.guild else None
    await interaction.response.send_message(embed=emb(
        "💛 Danke, dass du unterstützen willst!",
        "Für Narco City ist bei VOLT alles kostenlos, Spenden sind komplett freiwillig.\n\n"
        "Spenden klären wir direkt hier auf Discord: Schreib einfach in dein Ticket"
        + (f" oder öffne in {order.mention} eine **Individuelle Anfrage**." if order else ".")), ephemeral=True)


@bot.tree.command(name="panels", description="Info-/Verify-/Ticket-Panels neu posten (nur Owner)")
@app_commands.guild_only()
@app_commands.default_permissions(administrator=True)
@owner_check()
async def panels_cmd(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    await post_panels(interaction.guild)
    await interaction.followup.send("✅ Panels aktualisiert.", ephemeral=True)


@bot.tree.command(name="design", description="VOLT-Design anwenden: Icons, Kanalnamen, Rollenfarben, Banner (nichts wird gelöscht)")
@app_commands.guild_only()
@app_commands.default_permissions(administrator=True)
@owner_check()
async def design_cmd(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True, thinking=True)
    msg = await run_design(interaction.guild)
    await interaction.followup.send(f"✅ Design angewendet.\n{msg}", ephemeral=True)


# ===============================================================
# ARBEITSSTATUS & UPTIME-MONITOR
# /status online|störung|wartung, /störung, /wartungsmodus setzen den
# Arbeitsstatus. Der Monitor prüft jede Minute die Website (und weitere
# Dienste per /uptime) und aktualisiert EINE Nachricht im Uptime-Kanal,
# ohne neue Statusmeldungen zu spammen.
# ===============================================================
WORK_STATES = {
    #            Symbol  Titel                  kurz       Farbe       Discord-Status
    "online":   ("🟢", "Alle Systeme laufen", "Online", C_ONLINE, discord.Status.online),
    "wartung":  ("🟠", "Wartungsmodus", "Wartung", C_WARTUNG, discord.Status.idle),
    "stoerung": ("🔴", "Störung", "Störung", C_STOERUNG, discord.Status.dnd),
}
WORK_DEFAULT_NOTE = {"online": "Alles läuft.", "wartung": "Alle Systeme werden aktualisiert.",
                     "stoerung": "Wir arbeiten daran, dass alles schnell wieder läuft."}
_work = {"state": "online", "note": "", "since": time.time()}
_mon = {"channel_id": None, "message_id": None, "started": None, "targets": {}, "extra": [],
        "panel_channel_id": None, "panel_message_id": None}
_mon_lock = asyncio.Lock()
MAX_EXTRA_TARGETS = 8


def main_guild():
    if GUILD_ID:
        return bot.get_guild(GUILD_ID)
    return bot.guilds[0] if bot.guilds else None


async def load_status_state():
    w = await get_setting("work_status")
    if isinstance(w, dict) and w.get("state") in WORK_STATES:
        _work.update(w)
    m = await get_setting("monitor")
    if isinstance(m, dict):
        _mon.update({k: v for k, v in m.items() if k in _mon})
    if not _mon.get("started"):
        _mon["started"] = time.time()


async def save_monitor():
    await set_setting("monitor", _mon)


def monitor_targets() -> list:
    out = []
    if SITE_ENABLED:
        out.append({"name": SITE_HOST, "url": f"{SITE_URL}/health", "link": SITE_URL, "main": True})
    for t in _mon.get("extra") or []:
        out.append({"name": t["name"], "url": t["url"], "link": t["url"], "main": False})
    return out


def fmt_long(sec) -> str:
    """8 Tage, 03:41:31"""
    sec = max(0, int(sec or 0))
    d, rest = divmod(sec, 86400)
    h, rest = divmod(rest, 3600)
    m, s_ = divmod(rest, 60)
    clock = f"{h:02d}:{m:02d}:{s_:02d}"
    if d:
        return f"{d} {'Tag' if d == 1 else 'Tage'}, {clock}"
    return clock


def overall_state() -> str:
    if _work["state"] == "wartung":
        return "wartung"
    downs = [t for t in monitor_targets() if (_mon["targets"].get(t["name"]) or {}).get("up") is False]
    vs = (_mon.get("vsys") or {}).get("state")
    if _work["state"] == "stoerung" or downs or vs == "stoerung":
        return "stoerung"
    if vs in ("eingeschraenkt", "wartung"):
        return "teilweise"
    return "online"


def _pct(st) -> str:
    if not st or not st.get("total"):
        return "–"
    v = st["ok"] / st["total"] * 100
    return ("100" if v >= 99.995 else f"{v:.2f}".replace(".", ",")) + " %"


def system_summary() -> dict:
    """Für die Website: nur Zustand und Zahlen, keine Adressen von weiteren Diensten."""
    targets = monitor_targets()
    main = _mon["targets"].get(targets[0]["name"]) if targets else None
    state = overall_state()
    label = {"online": "Alle Systeme laufen", "wartung": "Wartungsmodus", "stoerung": "Störung",
             "teilweise": "Teilweise eingeschränkt"}[state]
    if state == "stoerung" and _work["state"] != "stoerung":
        label = "Eingeschränkt erreichbar"
    iso = lambda t: dt.datetime.fromtimestamp(t, dt.timezone.utc).isoformat(timespec="seconds") if t else None
    return {
        "state": state, "label": label,
        "note": clean_comment(_work.get("note") or ""),
        "since": iso(_work.get("since")),
        "uptime": round(main["ok"] / main["total"] * 100, 2) if main and main.get("total") else None,
        "ms": main.get("ms") if main else None,
        "checked": iso(main.get("checked")) if main else None,
        "up": sum(1 for t in targets if (_mon["targets"].get(t["name"]) or {}).get("up") is not False),
        "total": len(targets),
        "vsys": VSYS_TEXT.get((_mon.get("vsys") or {}).get("state"), VSYS_TEXT[None])[1],
        "vsys_state": (_mon.get("vsys") or {}).get("state"),
    }


def monitor_embed() -> discord.Embed:
    state = overall_state()
    targets = monitor_targets()
    downs = [t for t in targets if (_mon["targets"].get(t["name"]) or {}).get("up") is False]
    if state == "online":
        title, color = "🟢 Alle Systeme sind erreichbar", C_ONLINE
    elif state == "wartung":
        title, color = "🟠 Wartungsmodus – alle Systeme werden aktualisiert", C_WARTUNG
    elif state == "teilweise":
        title, color = "🟠 VOLT System eingeschränkt – wir behalten es im Blick", C_WARTUNG
    elif _work["state"] == "stoerung":
        title, color = "🔴 Störung – wir arbeiten daran", C_STOERUNG
    elif (_mon.get("vsys") or {}).get("state") == "stoerung" and not downs:
        title, color = "🔴 Störung im VOLT System", C_STOERUNG
    else:
        title, color = f"🔴 {len(downs)} {'Dienst' if len(downs) == 1 else 'Dienste'} nicht erreichbar", C_STOERUNG
    text = (f"Der Status von **[{SITE_HOST}]({SITE_URL})** wird automatisch überwacht.\n"
            f"Diese Nachricht wird live aktualisiert – es werden keine neuen Statusmeldungen gespammt.")
    if _work.get("note"):
        text += f"\n\n📝 **Hinweis:** {_work['note']}"
    e = discord.Embed(title=title, description=text, color=color, timestamp=discord.utils.utcnow())
    if bot.user:
        e.set_author(name="VOLT • Service Monitor", icon_url=bot.user.display_avatar.url)
        e.set_thumbnail(url=bot.user.display_avatar.url)
    now = time.time()
    if targets:
        t0 = targets[0]
        st = _mon["targets"].get(t0["name"]) or {}
        up = st.get("up")
        status_txt = ("🟢 **Online**" if up else "🔴 **Offline**" if up is False else "⏳ **Wird geprüft**")
        code = f"\nHTTP {st['code']}" if st.get("code") else ("\nkeine Antwort" if up is False else "")
        e.add_field(name="Service", value=f"🌐 [{t0['name']}]({t0['link']})")
        e.add_field(name="Aktueller Status", value=status_txt + code)
        e.add_field(name="Antwortzeit", value=f"📡 {st['ms']} ms" if st.get("ms") is not None else "📡 –")
        e.add_field(name="Monitor-Uptime", value=f"⏱️ {fmt_long(now - (_mon.get('started') or now))}")
        e.add_field(name="Zustand besteht seit", value=f"🕒 {fmt_long(now - st['since'])}" if st.get("since") else "🕒 –")
        e.add_field(name="Letzter Service-Check",
                    value=f"🔄 <t:{int(st['checked'])}:R>" if st.get("checked") else "🔄 gleich")
        e.add_field(name="Erreichbarkeit", value=f"📈 {_pct(st)}")
    vs = _mon.get("vsys") or {}
    vi, vt = VSYS_TEXT.get(vs.get("state"), VSYS_TEXT[None])
    e.add_field(name="VOLT System", value=f"{vi} {vt}" + (f"\nseit <t:{int(vs['since'])}:R>" if vs.get("since") else ""))
    icon, wtitle, short, _, _ = WORK_STATES[_work["state"]]
    e.add_field(name="Arbeitsstatus", value=f"{icon} {short}\ngesetzt <t:{int(_work['since'])}:R>")
    extra = targets[1:]
    if extra:
        lines = []
        for t in extra:
            st = _mon["targets"].get(t["name"]) or {}
            dot = "🟢" if st.get("up") else "🔴" if st.get("up") is False else "⏳"
            bits = [f"HTTP {st['code']}" if st.get("code") else ("keine Antwort" if st.get("up") is False else "wird geprüft")]
            if st.get("ms") is not None and st.get("up"):
                bits.append(f"{st['ms']} ms")
            bits.append(_pct(st))
            lines.append(f"{dot} **[{t['name']}]({t['link']})** · " + " · ".join(bits))
        e.add_field(name="Weitere Dienste", value="\n".join(lines)[:1024], inline=False)
    e.set_footer(text=f"VOLT • Live-Status • Check alle {MONITOR_INTERVAL} Sek. • {SITE_LABEL}")
    return e


def monitor_view() -> discord.ui.View:
    v = discord.ui.View(timeout=None)
    v.add_item(discord.ui.Button(label="Website öffnen", emoji="🌐", style=discord.ButtonStyle.link, url=SITE_URL))
    v.add_item(discord.ui.Button(label="Live-Status", emoji="📊", style=discord.ButtonStyle.link, url=f"{SITE_URL}/#status"))
    return v


def monitor_channel(guild: discord.Guild):
    if _mon.get("channel_id"):
        ch = guild.get_channel(_mon["channel_id"])
        if ch:
            return ch
    return find_channel(guild, "uptime") or find_channel(guild, "server-status")


async def update_monitor(guild: discord.Guild, *, fresh: bool = False):
    """Bearbeitet die eine Monitor-Nachricht. Fehlt sie, wird sie neu gepostet."""
    if guild is None:
        return
    ch = monitor_channel(guild)
    if ch is None:
        return
    async with _mon_lock:
        if not fresh and _mon.get("message_id") and _mon.get("channel_id") == ch.id:
            try:
                await ch.get_partial_message(_mon["message_id"]).edit(embed=monitor_embed(), view=monitor_view())
                return
            except discord.NotFound:
                pass
            except discord.HTTPException as ex:
                print("Uptime-Monitor: Bearbeiten fehlgeschlagen:", ex)
                return
        try:
            await ch.purge(limit=30, check=lambda m: m.author.id == guild.me.id)
        except discord.HTTPException:
            pass
        try:
            msg = await ch.send(embed=monitor_embed(), view=monitor_view())
        except discord.HTTPException as ex:
            print("Uptime-Monitor: Senden fehlgeschlagen:", ex)
            return
        _mon["channel_id"], _mon["message_id"] = ch.id, msg.id
        await save_monitor()


def status_panel_embed() -> discord.Embed:
    icon, title, short, color, _ = WORK_STATES[_work["state"]]
    e = discord.Embed(title=f"{icon} Status: {short}", color=color, timestamp=discord.utils.utcnow(),
                      description=(_work.get("note") or WORK_DEFAULT_NOTE[_work["state"]]))
    e.add_field(name="Seit", value=f"<t:{int(_work['since'])}:R>")
    e.add_field(name="Live-Check", value=f"[{SITE_HOST}]({SITE_URL}/#status)")
    e.set_footer(text=BRAND)
    return e


async def update_status_panel(guild: discord.Guild, *, fresh: bool = False):
    """Im server-status-Kanal steht der Arbeitsstatus, wenn der Monitor in einem eigenen Uptime-Kanal läuft."""
    if guild is None:
        return
    ch = find_channel(guild, "server-status")
    mon = monitor_channel(guild)
    if ch is None or (mon and mon.id == ch.id):
        return
    if not fresh and _mon.get("panel_message_id") and _mon.get("panel_channel_id") == ch.id:
        try:
            await ch.get_partial_message(_mon["panel_message_id"]).edit(embed=status_panel_embed(), view=monitor_view())
            return
        except discord.NotFound:
            pass
        except discord.HTTPException:
            return
    try:
        await ch.purge(limit=30, check=lambda m: m.author.id == guild.me.id)
    except discord.HTTPException:
        pass
    try:
        msg = await ch.send(embed=status_panel_embed(), view=monitor_view())
    except discord.HTTPException:
        return
    _mon["panel_channel_id"], _mon["panel_message_id"] = ch.id, msg.id
    await save_monitor()


def status_voice_name() -> str:
    icon, _, short, _, _ = WORK_STATES[_work["state"]]
    return f"{icon} Status: {short}"


async def rename_status_voice(guild: discord.Guild):
    if guild is None:
        return
    new = status_voice_name()
    for ch in guild.voice_channels:
        if "Status:" in ch.name and ch.name != new:
            try:
                await ch.edit(name=new, reason="VOLT Arbeitsstatus")
            except discord.HTTPException:
                pass  # Discord-Limit: update_stats zieht den Namen später nach


async def apply_presence():
    icon, _, short, _, dstatus = WORK_STATES[_work["state"]]
    text = f"⚡ {SITE_LABEL}" if _work["state"] == "online" else f"{icon} {short} · {SITE_LABEL}"
    try:
        await bot.change_presence(status=dstatus, activity=discord.CustomActivity(name=text))
    except discord.HTTPException:
        pass


async def set_work_status(state: str, note: str = None):
    _work.update(state=state, note=(note or "").strip()[:300], since=time.time())
    await set_setting("work_status", _work)
    invalidate_site_cache()
    await apply_presence()
    g = main_guild()
    await update_monitor(g)
    await update_status_panel(g)
    asyncio.create_task(rename_status_voice(g))  # Umbenennen kann bei Discord dauern, Befehl wartet nicht


async def check_url(session: aiohttp.ClientSession, url: str):
    t0 = time.perf_counter()
    try:
        async with session.get(url, allow_redirects=True, headers={"User-Agent": f"Mozilla/5.0 (compatible; VOLT-Uptime/1.0; +{SITE_URL})"}) as r:
            await r.content.read(65536)
            return r.status < 400, r.status, int((time.perf_counter() - t0) * 1000)
    except Exception:
        return False, None, None


async def run_checks():
    targets = monitor_targets()
    if not targets:
        return []
    timeout = aiohttp.ClientTimeout(total=10)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        results = await asyncio.gather(*(check_url(session, t["url"]) for t in targets))
        await check_volt_system(session)
    now = time.time()
    changes = []
    for t, (ok, code, ms) in zip(targets, results):
        st = _mon["targets"].setdefault(t["name"], {"up": None, "since": now, "ok": 0, "total": 0, "fails": 0})
        st["total"] += 1
        st["checked"], st["code"], st["ms"] = now, code, ms
        if ok:
            st["ok"] += 1
            st["fails"] = 0
            new_up = True
        else:
            st["fails"] = st.get("fails", 0) + 1
            new_up = False if st["fails"] >= 2 else st["up"]   # ein einzelner Aussetzer zählt noch nicht
        if new_up is not None and new_up != st["up"]:
            if st["up"] is not None:
                changes.append((t, new_up, now - st["since"]))
            st["up"], st["since"] = new_up, now
    # Dienste, die entfernt wurden, nicht ewig mitschleppen
    names = {t["name"] for t in targets}
    for k in [k for k in _mon["targets"] if k not in names]:
        _mon["targets"].pop(k, None)
    await save_monitor()
    return changes


VSYS_TEXT = {"ok": ("🟢", "Betriebsbereit"), "eingeschraenkt": ("🟠", "Eingeschränkt"),
             "wartung": ("🔧", "Wartung"), "stoerung": ("🔴", "Störung"), None: ("⏳", "wird geprüft")}


def _vsys_rank(status: str) -> int:
    s_ = (status or "").upper()
    if "OUTAGE" in s_:
        return 3
    if "DEGRADED" in s_:
        return 2
    if "MAINTENANCE" in s_:
        return 1
    return 0


async def check_volt_system(session: aiohttp.ClientSession):
    """Zustand der Server-Plattform (nur die Teile, die laufende Bots betreffen). Unklare Antwort = nichts ändern."""
    try:
        async with session.get(VOLT_SYSTEM_URL, headers={"User-Agent": f"VOLT-Uptime/1.0 (+{SITE_URL})"}) as r:
            if r.status != 200:
                return
            data = await r.json(content_type=None)
    except Exception:
        return
    leaves = []
    for g in (data.get("components") or []) if isinstance(data, dict) else []:
        if VOLT_SYSTEM_REGION.lower() in str(g.get("name", "")).lower():
            for c in g.get("components") or []:
                if str(c.get("name", "")).startswith(VOLT_SYSTEM_PARTS):
                    leaves.append(str(c.get("status", "")))
    if not leaves:
        return
    rank = max(_vsys_rank(x) for x in leaves)
    new = {0: "ok", 1: "wartung", 2: "eingeschraenkt"}.get(rank, "stoerung")
    vs = _mon.setdefault("vsys", {})
    now = time.time()
    if vs.get("state") != new:
        vs["since"] = now
    vs["state"], vs["checked"] = new, now


async def notify_owner_changes(changes):
    if not changes:
        return
    try:
        owner = bot.get_user(OWNER_ID) or await bot.fetch_user(OWNER_ID)
    except discord.HTTPException:
        return
    for t, up, lasted in changes:
        if up:
            e = emb(f"🟢 {t['name']} ist wieder erreichbar", f"Ausfall hat {fmt_long(lasted)} gedauert.", C_ONLINE)
        else:
            e = emb(f"🔴 {t['name']} ist nicht erreichbar",
                    f"Zwei Checks hintereinander ohne Antwort.\nAdresse: {t['link']}", C_STOERUNG)
        try:
            await owner.send(embed=e)
        except discord.HTTPException:
            pass


@tasks.loop(seconds=MONITOR_INTERVAL)
async def uptime_monitor():
    try:
        changes = await run_checks()
        await refresh_bots_cache()
        bot_changes = await check_bot_changes()
        await save_monitor()
        invalidate_site_cache()
        await update_monitor(main_guild())
        await notify_owner_changes(changes)
        await notify_bot_changes(bot_changes)
    except Exception as ex:  # der Monitor darf nie stehen bleiben
        print("Uptime-Monitor Fehler:", repr(ex))


@uptime_monitor.before_loop
async def _before_monitor():
    await bot.wait_until_ready()
    await asyncio.sleep(5)  # Website kurz hochfahren lassen


STATUS_CHOICES = [
    app_commands.Choice(name="online · alles läuft 🟢", value="online"),
    app_commands.Choice(name="störung 🔴", value="stoerung"),
    app_commands.Choice(name="wartung · alle Systeme werden aktualisiert 🟠", value="wartung"),
]


def status_reply() -> str:
    icon, title, short, _, _ = WORK_STATES[_work["state"]]
    where = monitor_channel(main_guild()) if main_guild() else None
    end = "" if _work["state"] == "online" else "\nZurück auf grün mit `/status online`."
    return (f"{icon} Status ist jetzt **{short}**" + (f": {_work['note']}" if _work.get("note") else "") +
            f"\nAktualisiert: Bot-Status, Website, {where.mention if where else 'Uptime-Monitor'}" + end)


@bot.tree.command(name="status", description="Arbeitsstatus setzen: online, Störung oder Wartung (nur Owner)")
@app_commands.guild_only()
@app_commands.default_permissions(administrator=True)
@owner_check()
@app_commands.describe(zustand="online, störung oder wartung", hinweis="Optional: kurzer Text, z. B. was gerade los ist")
@app_commands.choices(zustand=STATUS_CHOICES)
async def status_cmd(interaction: discord.Interaction, zustand: app_commands.Choice[str], hinweis: str = None):
    await interaction.response.defer(ephemeral=True)
    await set_work_status(zustand.value, hinweis)
    await interaction.followup.send(status_reply(), ephemeral=True)


@bot.tree.command(name="störung", description="Störung melden: Bot, Website und Uptime-Kanal zeigen rot (nur Owner)")
@app_commands.guild_only()
@app_commands.default_permissions(administrator=True)
@owner_check()
@app_commands.describe(hinweis="Optional: was ist los?")
async def stoerung_cmd(interaction: discord.Interaction, hinweis: str = None):
    await interaction.response.defer(ephemeral=True)
    await set_work_status("stoerung", hinweis)
    await interaction.followup.send(status_reply(), ephemeral=True)


@bot.tree.command(name="wartungsmodus", description="Wartung: alle Systeme werden aktualisiert (nur Owner)")
@app_commands.guild_only()
@app_commands.default_permissions(administrator=True)
@owner_check()
@app_commands.describe(hinweis="Optional: z. B. wie lange es ungefähr dauert")
async def wartung_cmd(interaction: discord.Interaction, hinweis: str = None):
    await interaction.response.defer(ephemeral=True)
    await set_work_status("wartung", hinweis or WORK_DEFAULT_NOTE["wartung"])
    await interaction.followup.send(status_reply(), ephemeral=True)


uptime_group = app_commands.Group(name="uptime", description="Uptime-Monitor verwalten (nur Owner)",
                                  guild_only=True, default_permissions=discord.Permissions(administrator=True))


@uptime_group.command(name="hier", description="Uptime-Monitor ab jetzt in diesem Kanal anzeigen")
@owner_check()
async def uptime_here_cmd(interaction: discord.Interaction):
    if not isinstance(interaction.channel, discord.TextChannel):
        return await interaction.response.send_message("❌ Das geht nur in einem Textkanal.", ephemeral=True)
    await interaction.response.defer(ephemeral=True)
    old = interaction.guild.get_channel(_mon.get("channel_id") or 0)
    if old and old.id != interaction.channel.id and _mon.get("message_id"):
        try:
            await old.get_partial_message(_mon["message_id"]).delete()
        except discord.HTTPException:
            pass
    _mon["channel_id"], _mon["message_id"] = interaction.channel.id, None
    await update_monitor(interaction.guild, fresh=True)
    await update_status_panel(interaction.guild)
    await interaction.followup.send(f"✅ Der Uptime-Monitor läuft jetzt in {interaction.channel.mention}.", ephemeral=True)


@uptime_group.command(name="hinzufügen", description="Weiteren Dienst überwachen, z. B. ein Dashboard")
@owner_check()
@app_commands.describe(name="Anzeigename, z. B. dash.voltstudio.work", url="Adresse mit https://")
async def uptime_add_cmd(interaction: discord.Interaction, name: str, url: str):
    name, url = name.strip()[:40], url.strip()
    if not re.match(r"^https?://[^\s/$.?#][^\s]*$", url, re.I) or len(url) > 200:
        return await interaction.response.send_message("❌ Bitte eine gültige Adresse mit https:// angeben.", ephemeral=True)
    extra = _mon.setdefault("extra", [])
    if any(t["name"].lower() == name.lower() for t in extra) or name.lower() == SITE_HOST.lower():
        return await interaction.response.send_message("❌ Diesen Namen gibt es schon.", ephemeral=True)
    if len(extra) >= MAX_EXTRA_TARGETS:
        return await interaction.response.send_message(f"❌ Maximal {MAX_EXTRA_TARGETS} weitere Dienste.", ephemeral=True)
    await interaction.response.defer(ephemeral=True)
    extra.append({"name": name, "url": url})
    await save_monitor()
    await run_checks()
    await update_monitor(interaction.guild)
    st = _mon["targets"].get(name) or {}
    await interaction.followup.send(
        f"✅ **{name}** wird jetzt überwacht. Erster Check: "
        + (f"HTTP {st['code']}, {st['ms']} ms" if st.get("code") else "keine Antwort (ab 2 Fehlversuchen gilt er als offline)"),
        ephemeral=True)


async def uptime_name_autocomplete(interaction: discord.Interaction, current: str):
    return [app_commands.Choice(name=t["name"], value=t["name"])
            for t in (_mon.get("extra") or []) if current.lower() in t["name"].lower()][:25]


@uptime_group.command(name="entfernen", description="Dienst aus dem Uptime-Monitor entfernen")
@owner_check()
@app_commands.autocomplete(name=uptime_name_autocomplete)
async def uptime_remove_cmd(interaction: discord.Interaction, name: str):
    extra = _mon.get("extra") or []
    keep = [t for t in extra if t["name"] != name]
    if len(keep) == len(extra):
        return await interaction.response.send_message("❌ Diesen Dienst gibt es nicht. Die Website selbst bleibt immer drin.",
                                                       ephemeral=True)
    await interaction.response.defer(ephemeral=True)
    _mon["extra"] = keep
    _mon["targets"].pop(name, None)
    await save_monitor()
    await update_monitor(interaction.guild)
    await interaction.followup.send(f"✅ **{name}** wird nicht mehr überwacht.", ephemeral=True)


@uptime_group.command(name="jetzt-prüfen", description="Alle Dienste sofort prüfen")
@owner_check()
async def uptime_now_cmd(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    changes = await run_checks()
    await refresh_bots_cache()
    invalidate_site_cache()
    await update_monitor(interaction.guild)
    await notify_owner_changes(changes)
    lines = []
    for t in monitor_targets():
        st = _mon["targets"].get(t["name"]) or {}
        lines.append(f"{'🟢' if st.get('up') else '🔴' if st.get('up') is False else '⏳'} {t['name']}: "
                     + (f"HTTP {st['code']} · {st['ms']} ms" if st.get("code") else "keine Antwort"))
    vi, vt = VSYS_TEXT.get((_mon.get("vsys") or {}).get("state"), VSYS_TEXT[None])
    lines.append(f"{vi} VOLT System: {vt}")
    await interaction.followup.send("\n".join(lines) or "Keine Dienste.", ephemeral=True)


bot.tree.add_command(uptime_group)


# ===============================================================
# BOT-STATUS (Kunden-Bots melden sich per volt_credit.py)
# Jeder Bot schickt jede Minute einen Herzschlag an /api/heartbeat.
# Kommt 3 Minuten nichts, gilt er als offline. Angezeigt wird das auf
# der Website (Live-Status) und im Uptime-Kanal.
# ===============================================================
BOT_OFFLINE_AFTER = 180          # Sekunden ohne Meldung = offline
BOT_HEARTBEAT_INTERVAL = 60
PROCESS_START = time.time()
BOT_PRODUCTS = [("👪 Familien-Dashboard", "Familien-Dashboard"), ("⚽ Fussball-Manager", "Fussball-Manager"),
                ("🗺️ Routen Manager", "Routen Manager"), ("📺 Streamer-Bot", "Streamer-Bot"),
                ("🤖 Sonstiger Bot", "Bot")]


def _key_hash(key: str) -> str:
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


def _bot_up(r, now=None) -> bool:
    now = now or time.time()
    return bool(r["last_seen"] and now - r["last_seen"] <= BOT_OFFLINE_AFTER and r["discord_ok"] != 0)


def _bot_public_name(r) -> str:
    return r["name"] if r["public"] else f"Kunden-Bot · {r['product'] or 'Bot'}"


def _bot_pct(r, now=None):
    now = now or time.time()
    if not r["first_seen"]:
        return None
    span = now - r["first_seen"]
    if span < 60:
        return 100.0 if _bot_up(r, now) else None
    return round(min(100.0, (r["online_s"] or 0) / span * 100), 2)


async def all_bots():
    return await pool.fetch("SELECT * FROM bots ORDER BY name COLLATE NOCASE")


async def bots_summary() -> dict:
    """Für Website und Monitor. Nicht öffentliche Bots erscheinen nur als 'Kunden-Bot'."""
    now = time.time()
    out = []
    for r in await all_bots():
        up = _bot_up(r, now)
        state = "online" if up else ("wartet" if not r["last_seen"] else "offline")
        out.append({"name": _bot_public_name(r), "product": r["product"] or "Bot", "state": state,
                    "ping": r["ping"] if up else None, "uptime": _bot_pct(r, now),
                    "last": dt.datetime.fromtimestamp(r["last_seen"], dt.timezone.utc).isoformat(timespec="seconds")
                    if r["last_seen"] else None})
    return {"online": sum(1 for b in out if b["state"] == "online"), "total": len(out), "list": out[:40]}


_bots_cache = {"list": [], "online": 0, "total": 0}


async def refresh_bots_cache():
    try:
        _bots_cache.update(await bots_summary())
    except Exception as ex:
        print("Bot-Status Fehler:", repr(ex))


async def check_bot_changes():
    """Online/offline-Wechsel erkennen (für DM an den Owner). Direkt nach einem Neustart von VOLT ADMIN nicht,
    weil die Bots sich dann erst wieder melden müssen."""
    if time.time() - PROCESS_START < BOT_OFFLINE_AFTER + 30:
        prev = {}
    else:
        prev = _mon.setdefault("bots_up", {})
    changes = []
    now = time.time()
    state = {}
    for r in await all_bots():
        if not r["last_seen"]:
            continue
        up = _bot_up(r, now)
        state[str(r["id"])] = up
        old = prev.get(str(r["id"]))
        if old is not None and old != up:
            changes.append((r, up))
    _mon["bots_up"] = state
    return changes


async def notify_bot_changes(changes):
    if not changes:
        return
    try:
        owner = bot.get_user(OWNER_ID) or await bot.fetch_user(OWNER_ID)
    except discord.HTTPException:
        return
    for r, up in changes:
        if up:
            e = emb(f"🟢 Bot {r['name']} ist wieder online", f"{r['product'] or 'Bot'} · meldet sich wieder.", C_ONLINE)
        else:
            e = emb(f"🔴 Bot {r['name']} ist offline",
                    f"Seit <t:{int(r['last_seen'])}:R> keine Meldung mehr"
                    + (" (Bot läuft, aber ist von Discord getrennt)." if r["discord_ok"] == 0 and
                       time.time() - r["last_seen"] <= BOT_OFFLINE_AFTER else ".")
                    + "\nSchau ins Railway-Log des Bots.", C_STOERUNG)
        try:
            await owner.send(embed=e)
        except discord.HTTPException:
            pass


def bots_field_text() -> str:
    lines = []
    for b in _bots_cache["list"]:
        dot = {"online": "🟢", "offline": "🔴", "wartet": "⏳"}[b["state"]]
        bits = []
        if b["state"] == "online":
            if b["ping"] is not None:
                bits.append(f"{b['ping']} ms")
        elif b["state"] == "wartet":
            bits.append("wartet auf erste Meldung")
        else:
            bits.append("offline")
        if b["uptime"] is not None:
            bits.append(f"{b['uptime']:.2f} %".replace(".", ",").replace(",00 %", " %"))
        lines.append(f"{dot} **{b['name']}** · " + " · ".join(bits))
    text = "\n".join(lines)
    if len(text) > 1000:
        text = text[:990].rsplit("\n", 1)[0] + f"\n… und weitere ({_bots_cache['total']} gesamt)"
    return text


async def api_heartbeat(request: web.Request) -> web.Response:
    nostore = {"Cache-Control": "no-store"}
    if pool is None:
        return web.json_response({"ok": False}, status=503, headers=nostore)
    if (request.content_length or 0) > 4096:
        return web.json_response({"ok": False, "error": "zu groß"}, status=413, headers=nostore)
    try:
        data = await request.json()
        if not isinstance(data, dict):
            data = {}
    except Exception:
        data = {}
    auth = request.headers.get("Authorization", "")
    key = auth[7:].strip() if auth.lower().startswith("bearer ") else str(data.get("key") or "").strip()
    if not key or len(key) > 200:
        return web.json_response({"ok": False, "error": "Schlüssel fehlt"}, status=401, headers=nostore)
    r = await pool.fetchrow("SELECT * FROM bots WHERE key_hash=$1", _key_hash(key))
    if r is None:
        return web.json_response({"ok": False, "error": "Schlüssel unbekannt"}, status=401, headers=nostore)
    now = time.time()
    last = r["last_seen"]
    if last and now - last < 15:  # zu oft: annehmen, aber nicht zählen
        return web.json_response({"ok": True, "name": r["name"], "interval": BOT_HEARTBEAT_INTERVAL}, headers=nostore)

    def num(v, lo, hi):
        try:
            v = int(v)
        except (TypeError, ValueError):
            return None
        return max(lo, min(hi, v))
    add = (now - last) if last and now - last <= BOT_OFFLINE_AFTER else 0
    await pool.execute(
        "UPDATE bots SET last_seen=$1, first_seen=COALESCE(first_seen, $1), online_s=online_s+$2, beats=beats+1, "
        "guilds=$3, ping=$4, uptime_s=$5, discord_ok=$6, bot_user=$7 WHERE id=$8",
        now, add, num(data.get("guilds"), 0, 100000), num(data.get("ping_ms"), 0, 60000),
        num(data.get("uptime_s"), 0, 10 ** 9), 0 if data.get("discord_ok") is False else 1,
        str(data.get("bot_name") or "")[:80] or None, r["id"])
    if not last or now - last > BOT_OFFLINE_AFTER:
        invalidate_site_cache()  # war offline oder neu: Website sofort aktualisieren
    return web.json_response({"ok": True, "name": r["name"], "interval": BOT_HEARTBEAT_INTERVAL}, headers=nostore)


# ---------- Verwaltung per HTTP (nur mit VOLT_ADMIN_KEY) ----------
async def _admin_ok(request: web.Request) -> bool:
    if not ADMIN_API_KEY:
        return False
    given = request.headers.get("X-Volt-Admin", "")
    return bool(given) and hmac.compare_digest(given.encode(), ADMIN_API_KEY.encode())


async def api_admin_bots(request: web.Request) -> web.Response:
    nostore = {"Cache-Control": "no-store"}
    if pool is None or not await _admin_ok(request):
        return web.json_response({"ok": False}, status=403, headers=nostore)
    try:
        data = await request.json()
    except Exception:
        data = {}
    name = re.sub(r"\s+", " ", str(data.get("name") or "")).strip()[:40]
    product = str(data.get("product") or "Bot")[:40]
    if not name:
        return web.json_response({"ok": False, "error": "name fehlt"}, status=400, headers=nostore)
    key = "volt_" + secrets.token_urlsafe(24)
    row = await pool.fetchrow("SELECT id FROM bots WHERE lower(name)=lower($1)", name)
    if row:
        await pool.execute("UPDATE bots SET key_hash=$1, product=$2, public=$3 WHERE id=$4",
                           _key_hash(key), product, 0 if data.get("public") is False else 1, row["id"])
    else:
        await pool.execute("INSERT INTO bots (name, product, key_hash, public) VALUES ($1, $2, $3, $4)",
                           name, product, _key_hash(key), 0 if data.get("public") is False else 1)
    await refresh_bots_cache()
    invalidate_site_cache()
    return web.json_response({"ok": True, "name": name, "key": key, "updated": bool(row)}, headers=nostore)


async def api_admin_uptime(request: web.Request) -> web.Response:
    nostore = {"Cache-Control": "no-store"}
    if pool is None or not await _admin_ok(request):
        return web.json_response({"ok": False}, status=403, headers=nostore)
    try:
        data = await request.json()
    except Exception:
        data = {}
    name, url = str(data.get("name") or "").strip()[:40], str(data.get("url") or "").strip()
    if not name or not re.match(r"^https?://[^\s/$.?#][^\s]*$", url, re.I) or len(url) > 200:
        return web.json_response({"ok": False, "error": "name/url ungültig"}, status=400, headers=nostore)
    extra = [t for t in (_mon.get("extra") or []) if t["name"].lower() != name.lower()]
    if len(extra) >= MAX_EXTRA_TARGETS:
        return web.json_response({"ok": False, "error": "zu viele Dienste"}, status=400, headers=nostore)
    extra.append({"name": name, "url": url})
    _mon["extra"] = extra
    await save_monitor()
    return web.json_response({"ok": True, "name": name}, headers=nostore)


# ===============================================================
# ABSTURZ-MELDUNG PER DM
# Jedes Projekt im VOLT System meldet Absturz, vollen Arbeitsspeicher und
# fehlgeschlagene Updates an /api/system-hook. Angenommen wird nur, was aus
# dem eigenen Workspace kommt (Railway-Variable VOLT_HOOK_WORKSPACE). Der
# Owner bekommt eine DM; läuft der Dienst danach wieder, kommt eine Entwarnung.
# Gleiche Meldung für denselben Dienst höchstens alle 15 Minuten, insgesamt
# höchstens 20 DMs pro Stunde.
# ===============================================================
HOOK_WORKSPACE = os.environ.get("VOLT_HOOK_WORKSPACE", "").strip()
HOOK_REPEAT = 15 * 60
HOOK_MAX_PER_HOUR = 20
HOOK_FAIL = {
    "Deployment.crashed": ("💥", "ist abgestürzt",
                           "Der Dienst ist im laufenden Betrieb abgestürzt. Das VOLT System startet ihn automatisch neu."),
    "Deployment.oom_killed": ("🧠", "hatte zu wenig Arbeitsspeicher",
                              "Der Dienst wurde beendet, weil der Arbeitsspeicher voll war. Er wird automatisch neu gestartet."),
    "Deployment.failed": ("🛠️", "Update fehlgeschlagen",
                          "Das neue Update ließ sich nicht bauen oder starten. Die vorherige Version bleibt aktiv."),
}
HOOK_OK = {"Deployment.deployed", "Deployment.redeployed", "Deployment.restarted", "Deployment.resumed"}
HOOK_OLD_STATUS = {"CRASHED": "Deployment.crashed", "FAILED": "Deployment.failed", "SUCCESS": "Deployment.deployed"}
_hook = {"down": {}, "last": {}, "sent": deque()}


def _hook_event(data: dict):
    """Railway-Meldung → (Typ, Infos) oder None, wenn sie nicht von uns kommt oder uninteressant ist."""
    res = data.get("resource") if isinstance(data.get("resource"), dict) else {}
    pick = lambda k: res.get(k) if isinstance(res.get(k), dict) else {}  # noqa: E731
    ws, proj, env, svc = pick("workspace"), pick("project"), pick("environment"), pick("service")
    if not HOOK_WORKSPACE or not hmac.compare_digest(str(ws.get("id") or "").encode(), HOOK_WORKSPACE.encode()):
        return None
    if env.get("isEphemeral"):
        return ""
    kind = str(data.get("type") or "")
    if kind == "DEPLOY":  # altes Format
        kind = HOOK_OLD_STATUS.get(str(data.get("status") or "").upper(), "")
    if kind not in HOOK_FAIL and kind not in HOOK_OK:
        return ""
    details = data.get("details") if isinstance(data.get("details"), dict) else {}
    return kind, {
        "project": str(proj.get("name") or "Projekt")[:80], "project_id": str(proj.get("id") or "")[:64],
        "service": str(svc.get("name") or proj.get("name") or "Dienst")[:80], "service_id": str(svc.get("id") or "")[:64],
        "env": str(env.get("name") or "")[:40], "env_id": str(env.get("id") or "")[:64],
        "commit": str(details.get("commitMessage") or "").strip().split("\n", 1)[0][:120],
    }


def _hook_link(info: dict) -> str:
    if not info["project_id"]:
        return ""
    url = f"https://railway.com/project/{info['project_id']}"
    if info["service_id"]:
        url += f"/service/{info['service_id']}"
    if info["env_id"]:
        url += f"?environmentId={info['env_id']}"
    return url


def _hook_embed(kind: str, info: dict):
    """Baut die DM. None = nichts schicken (Wiederholung oder normales Update ohne vorherigen Ausfall)."""
    now = time.time()
    key = info["service_id"] or info["service"]
    down = _hook["down"]
    if kind in HOOK_FAIL:
        state = None
        if kind != "Deployment.failed":  # fehlgeschlagenes Update: alte Version läuft weiter, also kein Ausfall
            state = down.setdefault(key, {"since": now, "count": 0})
            state["count"] += 1
        last = _hook["last"].get((key, kind), 0)
        if now - last < HOOK_REPEAT:
            return None
        _hook["last"][(key, kind)] = now
        icon, what, text = HOOK_FAIL[kind]
        e = emb(f"{icon} {info['service']} {what}", text, C_STOERUNG)
        if state and state["count"] > 1:
            e.add_field(name="Ausfälle", value=f"{state['count']}× seit <t:{int(state['since'])}:R>", inline=True)
    else:
        state = down.pop(key, None)
        if not state or now - state["since"] > 24 * 3600:
            return None
        e = emb(f"🟢 {info['service']} läuft wieder", f"Ausfall hat etwa {fmt_long(now - state['since'])} gedauert.",
                C_ONLINE)
    e.add_field(name="Projekt", value=info["project"], inline=True)
    if info["env"] and info["env"] != "production":
        e.add_field(name="Umgebung", value=info["env"], inline=True)
    if info["commit"]:
        e.add_field(name="Letztes Update", value=info["commit"], inline=False)
    link = _hook_link(info)
    if link:
        e.add_field(name="Log", value=f"[Im VOLT System öffnen]({link})", inline=False)
    return e


async def _hook_send(e: discord.Embed):
    sent = _hook["sent"]
    now = time.time()
    while sent and now - sent[0] > 3600:
        sent.popleft()
    if len(sent) >= HOOK_MAX_PER_HOUR:
        print("Absturz-Meldung: Limit pro Stunde erreicht, DM ausgelassen:", e.title)
        return
    sent.append(now)
    try:
        owner = bot.get_user(OWNER_ID) or await bot.fetch_user(OWNER_ID)
        await owner.send(embed=e)
    except discord.HTTPException as ex:
        print("Absturz-Meldung: DM ging nicht raus:", repr(ex))


async def api_system_hook(request: web.Request) -> web.Response:
    nostore = {"Cache-Control": "no-store"}
    if (request.content_length or 0) > 65536:
        return web.json_response({"ok": False}, status=413, headers=nostore)
    try:
        data = await request.json()
        if not isinstance(data, dict):
            raise ValueError
    except Exception:
        return web.json_response({"ok": False}, status=400, headers=nostore)
    ev = _hook_event(data)
    if ev is None:
        return web.json_response({"ok": False}, status=403, headers=nostore)
    if ev:
        kind, info = ev
        if kind in HOOK_FAIL:
            print(f"Absturz-Meldung: {kind} · {info['project']} / {info['service']}")
        e = _hook_embed(kind, info)
        if e is not None:
            asyncio.create_task(_hook_send(e))
    return web.json_response({"ok": True}, headers=nostore)


# ---------- Befehle ----------
bots_group = app_commands.Group(name="bots", description="Bots, die ihren Status an die Website melden (nur Owner)",
                                guild_only=True, default_permissions=discord.Permissions(administrator=True))


async def bot_name_autocomplete(interaction: discord.Interaction, current: str):
    rows = await pool.fetch("SELECT name FROM bots ORDER BY name COLLATE NOCASE")
    return [app_commands.Choice(name=r["name"], value=r["name"])
            for r in rows if current.lower() in r["name"].lower()][:25]


def setup_text(name: str, key: str) -> str:
    return (f"✅ **{name}** ist angelegt. So meldet sich der Bot:\n\n"
            f"**1.** Datei `volt_credit.py` neben die bot.py des Bots legen\n"
            f"**2.** In Railway beim Bot unter *Variables* eintragen:\n"
            f"```\nVOLT_STATUS_KEY={key}\n```"
            f"**3.** In der bot.py direkt unter der Zeile, in der der Bot erstellt wird:\n"
            f"```py\nfrom volt_credit import volt_start\nvolt_start(bot)\n```"
            f"Nach dem Neustart steht im Railway-Log `[VOLT] Status aktiv` und der Bot erscheint "
            f"innerhalb einer Minute auf {SITE_LABEL} und im Uptime-Kanal.\n\n"
            f"⚠️ Den Schlüssel nur in Railway eintragen, nicht ins Ticket und nicht auf GitHub.")


@bots_group.command(name="hinzufügen", description="Neuen Bot anlegen und Schlüssel für die Statusmeldung bekommen")
@owner_check()
@app_commands.describe(name="Anzeigename, z. B. Morteco MC", produkt="Welches Produkt ist das?",
                       oeffentlich="Name auf der Website zeigen? Bei Nein steht dort nur 'Kunden-Bot'")
@app_commands.rename(oeffentlich="öffentlich")
@app_commands.choices(produkt=[app_commands.Choice(name=a, value=b) for a, b in BOT_PRODUCTS])
async def bots_add_cmd(interaction: discord.Interaction, name: str, produkt: app_commands.Choice[str],
                       oeffentlich: bool = True):
    name = re.sub(r"\s+", " ", name).strip()[:40]
    if not name:
        return await interaction.response.send_message("❌ Bitte einen Namen angeben.", ephemeral=True)
    if await pool.fetchval("SELECT 1 FROM bots WHERE lower(name)=lower($1)", name):
        return await interaction.response.send_message(
            "❌ Diesen Namen gibt es schon. Neuen Schlüssel gibt es mit `/bots neuer-schlüssel`.", ephemeral=True)
    key = "volt_" + secrets.token_urlsafe(24)
    await pool.execute("INSERT INTO bots (name, product, key_hash, public) VALUES ($1, $2, $3, $4)",
                       name, produkt.value, _key_hash(key), 1 if oeffentlich else 0)
    await refresh_bots_cache()
    invalidate_site_cache()
    await interaction.response.send_message(setup_text(name, key), ephemeral=True)


@bots_group.command(name="neuer-schlüssel", description="Neuen Schlüssel erzeugen (der alte gilt dann nicht mehr)")
@owner_check()
@app_commands.autocomplete(name=bot_name_autocomplete)
async def bots_rekey_cmd(interaction: discord.Interaction, name: str):
    r = await pool.fetchrow("SELECT id, name FROM bots WHERE name=$1", name)
    if not r:
        return await interaction.response.send_message("❌ Diesen Bot gibt es nicht.", ephemeral=True)
    key = "volt_" + secrets.token_urlsafe(24)
    await pool.execute("UPDATE bots SET key_hash=$1 WHERE id=$2", _key_hash(key), r["id"])
    await interaction.response.send_message(setup_text(r["name"], key), ephemeral=True)


@bots_group.command(name="entfernen", description="Bot aus der Statusanzeige entfernen")
@owner_check()
@app_commands.autocomplete(name=bot_name_autocomplete)
async def bots_remove_cmd(interaction: discord.Interaction, name: str):
    r = await pool.fetchrow("SELECT id FROM bots WHERE name=$1", name)
    if not r:
        return await interaction.response.send_message("❌ Diesen Bot gibt es nicht.", ephemeral=True)
    await pool.execute("DELETE FROM bots WHERE id=$1", r["id"])
    _mon.get("bots_up", {}).pop(str(r["id"]), None)
    await refresh_bots_cache()
    invalidate_site_cache()
    await update_monitor(interaction.guild)
    await interaction.response.send_message(f"✅ **{name}** wird nicht mehr angezeigt. Sein Schlüssel gilt nicht mehr.",
                                            ephemeral=True)


@bots_group.command(name="sichtbar", description="Namen des Bots auf der Website zeigen oder verstecken")
@owner_check()
@app_commands.autocomplete(name=bot_name_autocomplete)
async def bots_public_cmd(interaction: discord.Interaction, name: str, sichtbar: bool):
    r = await pool.fetchrow("SELECT id FROM bots WHERE name=$1", name)
    if not r:
        return await interaction.response.send_message("❌ Diesen Bot gibt es nicht.", ephemeral=True)
    await pool.execute("UPDATE bots SET public=$1 WHERE id=$2", 1 if sichtbar else 0, r["id"])
    await refresh_bots_cache()
    invalidate_site_cache()
    await update_monitor(interaction.guild)
    await interaction.response.send_message(
        f"✅ **{name}** steht jetzt " + ("mit Namen" if sichtbar else "nur als „Kunden-Bot“") + " auf der Website.",
        ephemeral=True)


@bots_group.command(name="liste", description="Alle Bots mit Status und letzter Meldung")
@owner_check()
async def bots_list_cmd(interaction: discord.Interaction):
    rows = await all_bots()
    if not rows:
        return await interaction.response.send_message("Noch keine Bots angelegt. Start mit `/bots hinzufügen`.",
                                                       ephemeral=True)
    now = time.time()
    lines = []
    for r in rows:
        up = _bot_up(r, now)
        dot = "🟢" if up else ("⏳" if not r["last_seen"] else "🔴")
        seen = f"<t:{int(r['last_seen'])}:R>" if r["last_seen"] else "noch nie"
        pct = _bot_pct(r, now)
        lines.append(f"{dot} **{r['name']}** · {r['product'] or 'Bot'}" + ("" if r["public"] else " · 🙈 versteckt")
                     + f"\n   letzte Meldung {seen}"
                     + (f" · {r['ping']} ms" if up and r["ping"] is not None else "")
                     + (f" · {r['guilds']} Server" if r["guilds"] is not None else "")
                     + (f" · {pct:.2f} %".replace(".", ",") if pct is not None else "")
                     + (f" · `{r['bot_user']}`" if r["bot_user"] else ""))
    e = emb("🤖 Bots mit Statusmeldung", "\n".join(lines)[:4000])
    await interaction.response.send_message(embed=e, ephemeral=True)


bot.tree.add_command(bots_group)


# ===============================================================
# WILLKOMMENSKARTEN
# Jeder neue User bekommt im Willkommens-Kanal eine eigene Karte:
# Profilbild im VOLT-Ring, Name, Mitgliedsnummer und Blitze, die aus
# der User-ID berechnet werden. Dadurch sieht jede Karte anders aus.
# Ohne Pillow gibt es eine schlichte Karte ohne Bild.
# ===============================================================
try:
    from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps
    HAS_PIL = True
except ImportError:  # requirements.txt: Pillow
    HAS_PIL = False
FONT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fonts")
CARD_W, CARD_H = 1100, 400
RED = (255, 184, 63)
# Nur Zeichen, die die Karten-Schrift sicher kann (Emojis usw. fallen weg, ł -> l, ș -> s)
CARD_OK = re.compile(r"[0-9A-Za-zÀ-ÖØ-öø-ÿ .,_\-'!?&+#]")


CARD_MAP = str.maketrans({"Ł": "L", "ł": "l", "Đ": "D", "đ": "d", "ı": "i", "Œ": "OE", "œ": "oe", "ẞ": "SS",
                          "Ħ": "H", "ħ": "h", "Ŧ": "T", "ŧ": "t"})


def card_text(text: str) -> str:
    out = []
    for ch in (text or "").translate(CARD_MAP):
        if CARD_OK.match(ch):
            out.append(ch)
        else:
            out.extend(c for c in unicodedata.normalize("NFKD", ch) if CARD_OK.match(c))
    return re.sub(r"\s+", " ", "".join(out)).strip()


def _font(name: str, size: int):
    try:
        return ImageFont.truetype(os.path.join(FONT_DIR, name), size)
    except OSError:
        try:
            return ImageFont.load_default(size)
        except TypeError:
            return ImageFont.load_default()


# VOLT-Logo als Polygone (aus dem Logo-SVG, Raster 0–100)
_LOGO_RING = ("M95.68 48.63L88.42 57.22L84.84 68.43L66.45 85.89L43.14 85.59L39.3 84.51L31.98 90.75L39.14 92.87L68.3 92.64L70.03 91.9L89.21 73.88L94.75 61.29L95.7 55.86Z"
              "M4.3 48.16L4.67 58.75L7.49 67.96L12.62 76.3L21.28 85.08L25.35 78.62L15.11 67.64L11.6 57.47Z"
              "M34.29 24.02L15.04 40.95L14.65 56.64L21.42 66.07L21.54 39.15Z"
              "M80.22 16L76.11 21.99L84.15 30.19L86.85 42.16L77.54 51.93L77.49 69.7L83.69 58.38L95.17 44.42L91.29 27.18L88.54 23.67Z"
              "M66.87 10.57L60.12 9.07L40.64 8.61L27.52 14.27L17.58 20.28L21.77 21.82L6.1 37.3L4.78 43.5L10.42 50.75L11.23 40.35L34.82 16.74L43.6 15.05L53.77 15.12L60.4 16.32Z")
_LOGO_BOLT = "M84.89 2L24.82 54.52L46.88 54.01L33.13 74.69L16.31 98L80.57 42.55L56.28 43.24Z"


def _polys(path: str, x: float, y: float, size: float):
    out = []
    for sub in path.split("M")[1:]:
        pts = []
        for pair in sub.rstrip("Z").split("L"):
            px, py = (float(v) for v in pair.split())
            pts.append((x + px * size / 100, y + py * size / 100))
        out.append(pts)
    return out


def _draw_logo(img, x: float, y: float, size: float):
    """Echtes VOLT-Logo: Ring Ivory, Blitz Amber mit leichtem Glühen."""
    W, H = img.size
    glow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow)
    for poly in _polys(_LOGO_BOLT, x, y, size):
        gd.polygon(poly, fill=(255, 184, 63, 170))
    img.alpha_composite(glow.filter(ImageFilter.GaussianBlur(max(2, size / 28))))
    d = ImageDraw.Draw(img)
    for poly in _polys(_LOGO_RING, x, y, size):
        d.polygon(poly, fill=(242, 239, 232, 255))
    for poly in _polys(_LOGO_BOLT, x, y, size):
        d.polygon(poly, fill=(255, 184, 63, 255))


def _spaced(draw, xy, text, font, fill, spacing):
    x, y = xy
    for ch in text:
        draw.text((x, y), ch, font=font, fill=fill)
        x += draw.textlength(ch, font=font) + spacing
    return x


def render_welcome_card(display_name: str, username: str, avatar: bytes, member_no: int, seed: int) -> io.BytesIO:
    """Willkommenskarte im VOLT-Look: Karte mit VOLT-Schnitt, Profilbild im Ivory-Ring mit
    VOLT-Logo, Name, Mitgliedsnummer groß als Kontur im Hintergrund. Keine Partikel, keine Zufallsblitze."""
    W, H = CARD_W, CARD_H
    CUT = 56
    base = Image.new("RGBA", (W, H), (16, 17, 18, 255))

    # ruhiges Amber-Glühen hinter dem Profilbild
    cx, cy, r = 196, 200, 116
    glow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ImageDraw.Draw(glow).ellipse((cx - 210, cy - 210, cx + 210, cy + 210), fill=(255, 184, 63, 46))
    base.alpha_composite(glow.filter(ImageFilter.GaussianBlur(80)))

    # Diagonale Linien in Bronze wie auf Website und Bannern
    stripes = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    sd = ImageDraw.Draw(stripes)
    for x in range(-H, W + H, 46):
        sd.line([(x, H), (x + int(H * 0.53), 0)], fill=(146, 115, 75, 34), width=1)
    base.alpha_composite(stripes)

    # Mitgliedsnummer groß als Kontur rechts im Hintergrund
    num = f"#{member_no}"
    big = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    bd = ImageDraw.Draw(big)
    f_big = _font("Saira-BlackItalic.ttf", 230)
    nw = bd.textlength(num, font=f_big)
    bd.text((W - nw - 40, 40), num, font=f_big, fill=(0, 0, 0, 0), stroke_width=2, stroke_fill=(146, 115, 75, 120))
    base.alpha_composite(big)

    # Profilbild im Ivory-Ring, außen Amber-Schein
    ring = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ImageDraw.Draw(ring).ellipse((cx - r - 9, cy - r - 9, cx + r + 9, cy + r + 9), outline=(255, 184, 63, 200), width=8)
    base.alpha_composite(ring.filter(ImageFilter.GaussianBlur(9)))
    d = ImageDraw.Draw(base)
    d.ellipse((cx - r - 7, cy - r - 7, cx + r + 7, cy + r + 7), fill=(16, 17, 18, 255), outline=(242, 239, 232, 255), width=5)
    try:
        av = Image.open(io.BytesIO(avatar)).convert("RGBA") if avatar else None
    except Exception:
        av = None
    if av is not None:
        av = ImageOps.fit(av, (2 * r, 2 * r), method=Image.LANCZOS)
        mask = Image.new("L", (2 * r, 2 * r), 0)
        ImageDraw.Draw(mask).ellipse((0, 0, 2 * r - 1, 2 * r - 1), fill=255)
        base.paste(av, (cx - r, cy - r), mask)
    else:
        _draw_logo(base, cx - 82, cy - 82, 164)

    # VOLT-Logo als Plakette unten rechts am Profilbild (ohne Profilbild steht das Logo schon im Kreis)
    if av is not None:
        bx, by, br = cx + 86, cy + 82, 42
        d = ImageDraw.Draw(base)
        d.ellipse((bx - br, by - br, bx + br, by + br), fill=(23, 24, 26, 255), outline=(58, 59, 63, 255), width=3)
        _draw_logo(base, bx - 30, by - 30, 60)

    # Text
    d = ImageDraw.Draw(base)
    tx = 372
    f_eye = _font("Rajdhani-Bold.ttf", 28)
    _spaced(d, (tx, 96), "WILLKOMMEN BEI VOLT", f_eye, RED + (255,), 6)
    name = card_text(display_name) or card_text(username) or "Neues Mitglied"
    name = "".join(c for c in name.upper() if CARD_OK.match(c))
    size = 90
    f_name = _font("Saira-BlackItalic.ttf", size)
    max_w = W - tx - 70
    while size > 40 and d.textlength(name, font=f_name) > max_w:
        size -= 4
        f_name = _font("Saira-BlackItalic.ttf", size)
    if d.textlength(name, font=f_name) > max_w:
        while len(name) > 4 and d.textlength(name + "…", font=f_name) > max_w:
            name = name[:-1]
        name = name.rstrip() + "…"
    d.text((tx, 234), name, font=f_name, fill=(242, 239, 232, 255), anchor="ls")  # gleiche Grundlinie, auch bei kleiner Schrift
    # schräger VOLT-Strich unter dem Namen
    sy = 252
    d.polygon([(tx + 8, sy), (tx + 84, sy), (tx + 76, sy + 8), (tx, sy + 8)], fill=RED + (255,))
    f_sub = _font("Barlow-SemiBold.ttf", 29)
    sub = f"Mitglied #{member_no}" + (f"  ·  @{username}" if username else "")
    d.text((tx, 280), sub, font=f_sub, fill=(220, 215, 204, 255))
    f_site = _font("Rajdhani-Bold.ttf", 22)
    _spaced(d, (tx, 326), SITE_LABEL.upper(), f_site, (184, 178, 166, 255), 4)

    # Karte mit VOLT-Schnitt oben rechts, dünner Rahmen, Amber-Kante am Schnitt
    shape = [(0, 0), (W - CUT, 0), (W - 1, CUT), (W - 1, H - 1), (0, H - 1)]
    mask = Image.new("L", (W, H), 0)
    ImageDraw.Draw(mask).polygon(shape, fill=255)
    card = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    card.paste(base, (0, 0), mask)
    cd = ImageDraw.Draw(card)
    cd.line(shape + [shape[0]], fill=(58, 59, 63, 255), width=2)
    cd.line([(W - CUT, 1), (W - 2, CUT)], fill=RED + (255,), width=4)
    out = io.BytesIO()
    card.save(out, "PNG", optimize=True)
    out.seek(0)
    return out


async def welcome_payload(member: discord.Member):
    """Embed, Datei und Buttons für die Willkommensnachricht."""
    guild = member.guild
    verify = find_channel(guild, "verify")
    regeln = find_channel(guild, "regeln")
    steps = []
    if regeln:
        steps.append(f"{ic('regeln', '📜')} Regeln lesen in {regeln.mention}")
    steps.append(f"{ic('verify', '✅')} Regeln akzeptieren in {verify.mention}" if verify
                 else f"{ic('verify', '✅')} Regeln akzeptieren")
    steps.append(f"{ic('produkte', '🔎')} Produkte mit Vorschau ansehen auf **[{SITE_LABEL}]({SITE_URL}/#produkte)**")
    bestellen = find_channel(guild, "bestellen")
    steps.append(f"{ic('bestellen', '🛒')} Danach in {bestellen.mention if bestellen else '**#bestellen**'} dein Produkt wählen")
    e = discord.Embed(
        title=f"{ic('volt', '⚡')} Willkommen, {member.display_name}!",
        description=(f"Schön, dass du da bist, {member.mention}! Du bist unser **{guild.member_count}. Mitglied**.\n\n"
                     + "\n".join(steps)),
        color=BRAND_COLOR, timestamp=discord.utils.utcnow())
    e.set_footer(text=BRAND)
    file = None
    if HAS_PIL:
        try:
            data = await member.display_avatar.replace(size=256, static_format="png").read()
        except (discord.HTTPException, ValueError):
            data = None
        try:
            png = await asyncio.to_thread(render_welcome_card, member.display_name, member.name, data,
                                          guild.member_count or 0, member.id)
            file = discord.File(png, filename="willkommen.png")
            e.set_image(url="attachment://willkommen.png")
        except Exception as ex:
            print("Willkommenskarte Fehler:", repr(ex))
    if file is None:
        e.set_thumbnail(url=member.display_avatar.url)
    v = discord.ui.View(timeout=None)
    v.add_item(discord.ui.Button(label="Produkte ansehen", emoji=ic_emoji("produkte", "🔎"), style=discord.ButtonStyle.link,
                                 url=f"{SITE_URL}/#produkte"))
    v.add_item(discord.ui.Button(label=SITE_LABEL, emoji=ic_emoji("website", "🌐"), style=discord.ButtonStyle.link, url=SITE_URL))
    return e, file, v


async def send_welcome(member: discord.Member):
    ch = find_channel(member.guild, "willkommen")
    if ch is None:
        return
    e, file, v = await welcome_payload(member)
    kw = {"file": file} if file else {}
    try:
        await ch.send(content=member.mention, embed=e, view=v,
                      allowed_mentions=discord.AllowedMentions(users=[member], roles=False, everyone=False), **kw)
    except discord.HTTPException as ex:
        print("Willkommensnachricht fehlgeschlagen:", ex)


async def cleanup_old_welcome_panel(guild: discord.Guild):
    """Der alte Willkommens-Kasten fliegt raus, die Willkommenskarten bleiben stehen."""
    ch = find_channel(guild, "willkommen")
    if ch is None:
        return
    try:
        async for m in ch.history(limit=100):
            if m.author.id == guild.me.id and m.embeds and (m.embeds[0].title or "").startswith("👋 Willkommen bei"):
                await m.delete()
    except discord.HTTPException:
        pass


@bot.tree.command(name="willkommen-test", description="Deine eigene Willkommenskarte ansehen (nur für dich sichtbar)")
@app_commands.guild_only()
@app_commands.default_permissions(administrator=True)
@owner_check()
async def welcome_test_cmd(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    e, file, v = await welcome_payload(interaction.user)
    kw = {"file": file} if file else {}
    await interaction.followup.send(
        content="So sieht die Willkommenskarte aus." + ("" if HAS_PIL else " (Ohne Bild: Pillow fehlt in requirements.txt)"),
        embed=e, view=v, ephemeral=True, **kw)


# ===============================================================
# SICHERHEITS-STATUS & HILFE
# ===============================================================
@bot.tree.command(name="security-status", description="Zeigt alle Schutzsysteme und ob der Bot richtig eingerichtet ist")
@app_commands.guild_only()
@app_commands.default_permissions(moderate_members=True)
@team_check()
async def security_status_cmd(interaction: discord.Interaction):
    guild = interaction.guild
    me = guild.me
    now = time.time()
    p = me.guild_permissions
    on, off = "🟢", "🔴"

    top_ok = me.top_role.position >= max(r.position for r in guild.roles if not r.managed or r == me.top_role)
    hp_bans = await pool.fetchval("SELECT value FROM stats WHERE key='honeypot_bans'") or 0
    bl = await pool.fetchval("SELECT count(*) FROM blacklist WHERE until IS NULL OR until>$1", int(time.time())) or 0
    warns = await pool.fetchval("SELECT count(*) FROM warns") or 0
    lock_left = int(raid_until - now) if raid_until > now else 0

    e = emb("🛡️ Sicherheits-Status", "Alle Schutzsysteme von VOLT ADMIN auf einen Blick.",
            0xE74C3C if lock_left else 0x2ECC71)
    e.add_field(name=f"{on if MIN_ACCOUNT_AGE_DAYS else off} Join-Gate",
                value=f"Accounts jünger als **{MIN_ACCOUNT_AGE_DAYS} Tage** werden gekickt" if MIN_ACCOUNT_AGE_DAYS
                else "aus (MIN_ACCOUNT_AGE_DAYS=0)", inline=False)
    e.add_field(name=f"{on} Anti-Raid",
                value=f"{RAID_JOINS} Joins in {RAID_WINDOW}s → {RAID_LOCKDOWN}s Kick-Modus\n"
                      + (f"⚠️ **Lockdown aktiv**, noch {lock_left}s" if lock_left else "Kein Raid erkannt"), inline=True)
    e.add_field(name=f"{on} Anti-Nuke",
                value=f"{NUKE_LIMIT} Löschungen/Bans in {NUKE_WINDOW}s → Bann", inline=True)
    e.add_field(name=f"{on} Anti-Spam", value="6 Nachrichten in 6s oder 5+ Erwähnungen → 10 Min Timeout", inline=False)
    e.add_field(name=f"{on} Link- & Invite-Filter", value="Fremde Invites: gelöscht + Warn\nLinks: nur Kunden & Tickets", inline=True)
    hp = find_channel(guild, "nicht-schreiben")
    e.add_field(name=f"{on if hp else off} Honeypot",
                value=(f"{hp.mention} · **{hp_bans}** Spam-Accounts gebannt" if hp else "Kanal fehlt – /panels oder /setup"),
                inline=True)
    e.add_field(name=f"{on} Rollen-Schutz", value="Owner-/Admin-Rolle vergibt nur der Owner", inline=True)
    e.add_field(name="📋 Zahlen", value=f"Warns gesamt: **{warns}** (3 → Timeout, 5 → Bann)\nBlacklist: **{bl}**", inline=True)

    need = {"Administrator": p.administrator, "Audit-Log sehen": p.view_audit_log, "Bannen": p.ban_members,
            "Kicken": p.kick_members, "Timeout": p.moderate_members, "Rollen verwalten": p.manage_roles,
            "Kanäle verwalten": p.manage_channels, "Nachrichten verwalten": p.manage_messages}
    perms = "\n".join(f"{on if v or p.administrator else off} {k}" for k, v in need.items())
    e.add_field(name="🔑 Bot-Rechte", value=perms, inline=True)
    e.add_field(name=f"{on if top_ok else off} Bot-Rolle",
                value="ganz oben ✅" if top_ok else "⚠️ **Nicht ganz oben!** Ziehe die Bot-Rolle in den "
                                                   "Servereinstellungen nach oben, sonst greift der Schutz nicht.", inline=True)
    logs = "\n".join(f"{on if find_channel(guild, k) else off} #{k}" for k in
                     ("mod-logs", "admin-logs", "ticket-logs", "join-leave-logs"))
    e.add_field(name="📜 Log-Kanäle", value=logs, inline=True)
    await interaction.response.send_message(embed=e, ephemeral=True)


@bot.tree.command(name="volt", description="Website und Produkte von VOLT")
async def volt_cmd(interaction: discord.Interaction):
    e = emb("⚡ VOLT – Discord Solutions",
            "Familien-Dashboards, Fussball-Manager und Routen Manager mit eigenem Discord-Bot, für Narco City kostenlos. "
            "Gebaut und betreut von einer Person, nur auf Spendenbasis.\n\n"
            f"🌐 **{SITE_LABEL}** – alle Produkte mit Vorschau und klickbarer Demo")
    await interaction.response.send_message(embed=e, view=volt_link_view(), ephemeral=True)


@bot.tree.command(name="hilfe", description="Alle Befehle von VOLT ADMIN")
@app_commands.guild_only()
async def help_cmd(interaction: discord.Interaction):
    user = interaction.user
    team = isinstance(user, discord.Member) and has_team_role(user)
    owner = user.id == OWNER_ID
    e = emb("📖 Befehle", "Alles, was du mit VOLT ADMIN machen kannst.")
    e.add_field(name="Für alle", inline=False, value=(
        "`/projekt` – Status deiner Projekte\n`/bewerten` – fertiges Projekt bewerten\n"
        "`/dm-benachrichtigungen` – DMs bei Ticket-Antworten an/aus\n`/spenden` – freiwillig unterstützen\n"
        "`/volt` – Website und Produkte\n`/hilfe` – diese Übersicht"))
    if team:
        e.add_field(name="Team", inline=False, value=(
            "`/warn` `/warns` `/clearwarns` – Verwarnungen\n`/timeout` `/kick` `/ban` `/unban` – Moderation\n"
            "`/benachrichtigen` – User per DM benachrichtigen\n`/security-status` – Schutzsysteme prüfen"))
    if owner:
        e.add_field(name="Owner", inline=False, value=(
            "`/platz 1|2|frei` – Ticket auf die Werkbank (startet die Zeit)\n"
            "`/zeit pause|weiter|anzeigen` – Arbeitszeit steuern\n"
            "`/bewertung-anfragen` – um Bewertung bitten\n"
            "`/bewertungen-liste` `/bewertung-loeschen` – Bewertungen verwalten\n"
            "Rechtsklick auf Bewertung → Apps → **Bewertung löschen**\n"
            "`/blacklist add|remove|list` – Ticket-Sperre mit Dauer\n`/panels` – Panels neu posten\n"
            "`/setup` – Server komplett neu aufbauen (löscht alles!)"))
        e.add_field(name="Status & Uptime", inline=False, value=(
            "`/status online|störung|wartung` – Arbeitsstatus setzen\n"
            "`/störung` · `/wartungsmodus` – Kurzbefehle, zurück mit `/status online`\n"
            "`/uptime hier` – Monitor in diesem Kanal anzeigen\n"
            "`/uptime hinzufügen|entfernen` – weitere Dienste überwachen\n"
            "`/uptime jetzt-prüfen` – sofort prüfen\n"
            "`/bots hinzufügen` – Bot anlegen, Schlüssel für volt_credit.py\n"
            "`/bots liste|entfernen|sichtbar|neuer-schlüssel` – Bots verwalten\n"
            "`/willkommen-test` – deine Willkommenskarte ansehen"))
    await interaction.response.send_message(embed=e, ephemeral=True)


# ===============================================================
# SETUP (loescht ALLES und baut neu)
# ===============================================================
async def run_full_setup(interaction: discord.Interaction) -> str:
    guild = interaction.guild
    current_channel_id = interaction.channel_id
    st = {"del_ch": 0, "del_roles": 0, "skipped": [], "rollen": 0, "kat": 0, "ch": 0}

    await pool.execute("UPDATE tickets SET status='deleted' WHERE status<>'deleted'")

    for ch in list(guild.channels):
        if ch.id == current_channel_id:
            continue
        try:
            await ch.delete(reason="VOLT Setup: Neuaufbau")
            st["del_ch"] += 1
        except discord.HTTPException:
            st["skipped"].append(f"Channel {ch.name}")

    for role in sorted(guild.roles, key=lambda r: r.position):
        if role.is_default() or role.managed or role >= guild.me.top_role:
            continue
        try:
            await role.delete(reason="VOLT Setup: Neuaufbau")
            st["del_roles"] += 1
        except discord.HTTPException:
            st["skipped"].append(f"Rolle {role.name}")

    ROLE_CACHE[guild.id] = {}
    for key, name, color, perms, hoist in ROLES:
        r = await guild.create_role(name=name, colour=discord.Colour(color),
                                    permissions=perms, hoist=hoist, reason="VOLT Setup")
        ROLE_CACHE[guild.id][key] = r
        st["rollen"] += 1

    for member in guild.members:
        try:
            if member.id == OWNER_ID:
                await member.add_roles(ROLE_CACHE[guild.id]["owner"], ROLE_CACHE[guild.id]["user"],
                                       reason="VOLT Setup")
            elif member.bot:
                await member.add_roles(ROLE_CACHE[guild.id]["bots"], reason="VOLT Setup")
            else:
                await member.add_roles(ROLE_CACHE[guild.id]["unverified"], reason="VOLT Setup")
        except discord.HTTPException:
            pass

    for cat_name, mode, channels in STRUCTURE:
        category = await guild.create_category(cat_name, overwrites=build_overwrites(guild, mode),
                                               reason="VOLT Setup")
        st["kat"] += 1
        for entry in channels:
            ch_name, kind = entry[0], entry[1]
            ch_mode = entry[2] if len(entry) > 2 else None
            if kind == "voice":
                name = f"👥 Mitglieder: {guild.member_count}" if ch_name.startswith("👥") else ch_name
                await guild.create_voice_channel(name, category=category)
            elif ch_mode:
                await guild.create_text_channel(
                    ch_name, category=category, overwrites=build_overwrites(guild, ch_mode))
            else:
                await guild.create_text_channel(ch_name, category=category)
            st["ch"] += 1

    await post_panels(guild)

    old = guild.get_channel(current_channel_id)
    if old:
        try:
            await old.delete(reason="VOLT Setup: Neuaufbau")
            st["del_ch"] += 1
        except discord.HTTPException:
            st["skipped"].append(f"Channel {old.name}")

    msg = (f"✅ Neuaufbau fertig.\nGelöscht: {st['del_ch']} Channels, {st['del_roles']} Rollen\n"
           f"Erstellt: {st['rollen']} Rollen, {st['kat']} Kategorien, {st['ch']} Channels\n"
           f"Panels (Regeln, Verify, Bestellen, FAQ …) wurden gepostet.\n\n"
           f"⚠️ Ziehe die Bot-Rolle in den Servereinstellungen ganz nach oben.")
    if st["skipped"]:
        msg += "\n\nNicht löschbar: " + ", ".join(st["skipped"][:10])
    return msg


class ConfirmWipe(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=60)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != OWNER_ID:
            await interaction.response.send_message("❌ Keine Berechtigung.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="Ja, alles löschen & neu aufbauen", style=discord.ButtonStyle.danger)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(content="⏳ Setup läuft, das dauert einige Minuten …", view=None)
        try:
            msg = await run_full_setup(interaction)
        except Exception as e:
            msg = f"❌ Fehler beim Setup: {e}"
        await interaction.followup.send(msg, ephemeral=True)
        self.stop()

    @discord.ui.button(label="Abbrechen", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(content="Abgebrochen.", view=None)
        self.stop()


@bot.tree.command(name="setup", description="LÖSCHT alle Channels & Rollen und baut den Server neu auf (nur Owner)")
@app_commands.guild_only()
@app_commands.default_permissions(administrator=True)
@owner_check()
async def setup_cmd(interaction: discord.Interaction):
    await interaction.response.send_message(
        "⚠️ **Achtung:** Das löscht **alle** Channels und **alle** Rollen und baut alles neu auf. "
        "Das kann nicht rückgängig gemacht werden.\n\nFortfahren?", view=ConfirmWipe(), ephemeral=True)


# ===============================================================
# SICHERHEIT
# ===============================================================
recent_joins: deque = deque()
raid_until = 0.0
spam_tracker: dict[int, deque] = defaultdict(lambda: deque(maxlen=10))
nuke_counts: dict[tuple, deque] = defaultdict(deque)
INVITE_RE = re.compile(r"(discord\.gg|discord(?:app)?\.com/invite)/\S+", re.I)
LINK_RE = re.compile(r"https?://\S+", re.I)


@bot.event
async def on_member_join(member: discord.Member):
    global raid_until
    guild = member.guild
    if member.bot:
        r = find_role(guild, "bots")
        if r:
            await member.add_roles(r, reason="Bot")
        return

    age_days = (discord.utils.utcnow() - member.created_at).days
    if MIN_ACCOUNT_AGE_DAYS and age_days < MIN_ACCOUNT_AGE_DAYS and member.id != OWNER_ID:
        try:
            await member.send(f"Dein Account ist zu neu für **{guild.name}** "
                              f"(mind. {MIN_ACCOUNT_AGE_DAYS} Tage). Versuche es später erneut.")
        except discord.HTTPException:
            pass
        await member.kick(reason="Account zu neu")
        return await log(guild, "admin-logs", emb("🛡️ Join-Gate", f"{member} gekickt (Account {age_days} Tage alt)",
                                                  0xE67E22))

    now = time.time()
    recent_joins.append((now, member))
    while recent_joins and now - recent_joins[0][0] > RAID_WINDOW:
        recent_joins.popleft()

    if now < raid_until or len(recent_joins) >= RAID_JOINS:
        if now >= raid_until:
            raid_until = now + RAID_LOCKDOWN
            await log(guild, "admin-logs", emb(
                "🚨 RAID erkannt",
                f"{len(recent_joins)} Joins in {RAID_WINDOW}s. Neue Mitglieder werden {RAID_LOCKDOWN}s lang gekickt.",
                0xE74C3C))
        victims = [m for _, m in recent_joins] if len(recent_joins) >= RAID_JOINS else [member]
        recent_joins.clear()
        for m in victims:
            if m.id == OWNER_ID:
                continue
            try:
                await m.kick(reason="Raid-Schutz")
            except discord.HTTPException:
                pass
        return

    unv = find_role(guild, "unverified")
    if unv:
        await member.add_roles(unv, reason="Neues Mitglied")
    await log(guild, "join-leave-logs", emb("📥 Beigetreten", f"{member.mention} · Account {age_days} Tage alt", 0x2ECC71))
    await send_welcome(member)


@bot.event
async def on_member_remove(member: discord.Member):
    await log(member.guild, "join-leave-logs", emb("📤 Verlassen", f"{member} ({member.id})", 0x95A5A6))


@bot.event
async def on_message(message: discord.Message):
    if message.author.bot or not message.guild or not isinstance(message.author, discord.Member):
        return
    member = message.author
    cat = message.channel.category
    in_ticket_cat = bool(cat and any(k in cat.name for k in TICKET_CATEGORY_KEYS))

    if has_team_role(member):
        # Team schreibt im Ticket -> Ersteller bekommt eine DM mit Link
        if in_ticket_cat:
            ticket = await get_ticket(message.channel.id)
            if ticket and ticket["user_id"] != member.id:
                preview = clean_comment(message.content)[:180] if message.content else ""
                if not preview and message.attachments:
                    preview = "📎 Datei angehängt"
                await notify_ticket_owner(
                    message.guild, ticket, "📬 Neue Antwort in deinem Ticket",
                    f"**{member.display_name}** hat in deinem Ticket geschrieben. Schau mal rein!"
                    + (f"\n\n> {preview}" if preview else ""), author=member)
        return

    if in_ticket_cat:
        # Kunde hat selbst geantwortet: nächste Team-Antwort meldet sich wieder sofort
        _dm_last.pop(message.channel.id, None)

    # Honeypot: wer hier schreibt, wird sofort gebannt
    hp = find_channel(message.guild, "nicht-schreiben")
    if hp and message.channel.id == hp.id:
        try:
            await message.guild.ban(member, reason="Honeypot: hat in #nicht-schreiben geschrieben",
                                    delete_message_seconds=3600)
            await pool.execute(
                "INSERT INTO stats (key,value) VALUES ('honeypot_bans',1) "
                "ON CONFLICT (key) DO UPDATE SET value=value+1")
            await log(message.guild, "mod-logs", emb(
                "🍯 Honeypot-Bann",
                f"{member} (ID {member.id}) hat in {hp.mention} geschrieben.\n"
                f"Inhalt: {message.content[:300] or '–'}", 0xE74C3C))
            await refresh_honeypot_panel(message.guild)
        except discord.HTTPException:
            try:
                await message.delete()
            except discord.HTTPException:
                pass
            await log(message.guild, "admin-logs", emb(
                "⚠️ Honeypot-Bann fehlgeschlagen",
                f"{member} konnte nicht gebannt werden (Rollen-Hierarchie?).", 0xE67E22))
        return

    # Invites: immer verboten
    if INVITE_RE.search(message.content):
        try:
            await message.delete()
        except discord.HTTPException:
            pass
        await message.channel.send(f"{member.mention} Fremde Einladungen sind nicht erlaubt. ⚠️", delete_after=8)
        return await add_warn(message.guild, member, bot.user.id, "Auto: Fremder Invite-Link")

    # Links: nur Kunden/Tickets duerfen
    in_ticket = (message.channel.category and
                 any(k in message.channel.category.name for k in TICKET_CATEGORY_KEYS))
    kunde = find_role(message.guild, "kunde")
    if LINK_RE.search(message.content) and not in_ticket and not (kunde and kunde in member.roles):
        try:
            await message.delete()
        except discord.HTTPException:
            pass
        return await message.channel.send(f"{member.mention} Links sind hier nicht erlaubt.", delete_after=6)

    # Spam / Massen-Mentions
    now = time.time()
    dq = spam_tracker[member.id]
    dq.append(now)
    spam = len([t for t in dq if now - t <= 6]) >= 6 or len(message.mentions) >= 5
    if spam:
        dq.clear()
        try:
            await member.timeout(dt.timedelta(minutes=10), reason="Anti-Spam")
            await message.channel.purge(limit=30, check=lambda m: m.author.id == member.id)
        except discord.HTTPException:
            pass
        await log(message.guild, "mod-logs", emb("🚫 Anti-Spam", f"{member.mention} · 10 Min Timeout", 0xE67E22))


async def check_nuke(guild: discord.Guild, action: discord.AuditLogAction, label: str):
    try:
        async for entry in guild.audit_logs(limit=1, action=action):
            if (discord.utils.utcnow() - entry.created_at).total_seconds() > 10:
                return
            ex = entry.user
            if ex is None or ex.id in (OWNER_ID, bot.user.id, guild.owner_id):
                return
            dq = nuke_counts[(guild.id, ex.id)]
            now = time.time()
            dq.append(now)
            while dq and now - dq[0] > NUKE_WINDOW:
                dq.popleft()
            if len(dq) >= NUKE_LIMIT:
                dq.clear()
                try:
                    await guild.ban(ex, reason=f"Anti-Nuke: Massen-{label}")
                    res = "gebannt"
                except discord.HTTPException:
                    res = "Bann fehlgeschlagen, bitte manuell prüfen!"
                await log(guild, "admin-logs", emb(
                    "🚨 ANTI-NUKE", f"{ex} (ID {ex.id}) hat massenhaft {label} ausgeführt → {res}", 0xE74C3C))
            return
    except discord.HTTPException:
        pass


@bot.event
async def on_guild_channel_delete(channel):
    await check_nuke(channel.guild, discord.AuditLogAction.channel_delete, "Channel-Löschungen")


@bot.event
async def on_guild_role_delete(role):
    await check_nuke(role.guild, discord.AuditLogAction.role_delete, "Rollen-Löschungen")


@bot.event
async def on_member_ban(guild, user):
    await check_nuke(guild, discord.AuditLogAction.ban, "Bans")


@bot.event
async def on_member_update(before: discord.Member, after: discord.Member):
    """Schutz: Owner-/Admin-Rolle darf nur vom Owner vergeben werden."""
    guild = after.guild
    protected = role_names("owner", "admin")
    gained = [r for r in after.roles if r not in before.roles and r.name in protected]
    if not gained:
        return
    try:
        async for entry in guild.audit_logs(limit=5, action=discord.AuditLogAction.member_role_update):
            if entry.target and entry.target.id == after.id and \
                    (discord.utils.utcnow() - entry.created_at).total_seconds() < 10:
                if entry.user.id in (OWNER_ID, bot.user.id, guild.owner_id):
                    return
                await after.remove_roles(*gained, reason="Rollen-Schutz")
                await log(guild, "admin-logs", emb(
                    "🛡️ Rollen-Schutz",
                    f"{entry.user.mention} wollte {after.mention} die Rolle {gained[0].name} geben. Rückgängig gemacht.",
                    0xE74C3C))
                return
    except discord.HTTPException:
        pass


# ===============================================================
# MOD-LOG VON A BIS Z
# Alles, was User oder Team ändern, landet in #mod-logs: Nachrichten
# (vorher/nachher), Namen, Avatare, Rollen, Voice, Kanäle, Rollen,
# Bans, Kicks, Invites, Threads, Emojis, Server, Webhooks, Reaktionen …
# ===============================================================
C_EDIT, C_DEL, C_NEW, C_UPD, C_VOICE, C_MEMBER = 0x3498DB, 0xE74C3C, 0x2ECC71, 0xE67E22, 0x9B59B6, 0x1ABC9C


def _cut(text, n: int = 1000) -> str:
    text = "" if text is None else str(text)
    return text if len(text) <= n else text[:n - 1] + "…"


def _who(u) -> str:
    if u is None:
        return "unbekannt"
    return f"{u.mention} · `{u}` · ID {u.id}"


def _is_log_channel(ch) -> bool:
    return ch is not None and "-logs" in (getattr(ch, "name", "") or "")


def _ts(d) -> str:
    return discord.utils.format_dt(d, "f") if d else "–"


async def audit_actor(guild: discord.Guild, action: discord.AuditLogAction, target_id: int = None, within: int = 20):
    """Wer hat es gemacht? Sucht den passenden, frischen Audit-Log-Eintrag."""
    try:
        async for entry in guild.audit_logs(limit=8, action=action):
            if (discord.utils.utcnow() - entry.created_at).total_seconds() > within:
                break
            if target_id is None or getattr(entry.target, "id", None) == target_id:
                return entry.user, entry.reason
    except discord.HTTPException:
        pass
    return None, None


async def modlog(guild: discord.Guild, title: str, desc: str = "", color: int = C_UPD,
                 fields=(), actor=None, reason=None, thumb: str = None):
    if guild is None:
        return
    e = discord.Embed(title=title, description=_cut(desc, 4000), color=color, timestamp=discord.utils.utcnow())
    for name, value, inline in fields:
        e.add_field(name=name, value=_cut(value or "–", 1024), inline=inline)
    if actor is not None:
        e.add_field(name="Durch", value=_who(actor) + (" 🤖" if actor.bot else ""), inline=False)
    if reason:
        e.add_field(name="Grund", value=_cut(reason, 1024), inline=False)
    if thumb:
        e.set_thumbnail(url=thumb)
    e.set_footer(text=f"{BRAND} • Mod-Log")
    await log(guild, "mod-logs", e)


PERM_DE = {
    "read_messages": "Kanal sehen", "view_channel": "Kanal sehen", "send_messages": "Nachrichten senden",
    "read_message_history": "Verlauf lesen", "manage_messages": "Nachrichten verwalten", "embed_links": "Links einbetten",
    "attach_files": "Dateien anhängen", "add_reactions": "Reaktionen", "mention_everyone": "@everyone erwähnen",
    "manage_channels": "Kanäle verwalten", "manage_roles": "Rollen verwalten", "manage_guild": "Server verwalten",
    "administrator": "Administrator", "ban_members": "Bannen", "kick_members": "Kicken",
    "moderate_members": "Timeout", "view_audit_log": "Audit-Log sehen", "manage_webhooks": "Webhooks verwalten",
    "create_instant_invite": "Einladungen erstellen", "connect": "Voice beitreten", "speak": "Sprechen",
    "mute_members": "Stummschalten", "deafen_members": "Taub schalten", "move_members": "Verschieben",
    "manage_nicknames": "Nicknames verwalten", "change_nickname": "Nickname ändern",
    "manage_threads": "Threads verwalten", "use_application_commands": "Befehle nutzen",
}


def _pname(n: str) -> str:
    return PERM_DE.get(n, n.replace("_", " "))


def _perm_diff(before: discord.Permissions, after: discord.Permissions) -> str:
    added = [n for n, v in after if v and not getattr(before, n)]
    removed = [n for n, v in after if not v and getattr(before, n)]
    out = []
    if added:
        out.append("➕ " + ", ".join(_pname(a) for a in added))
    if removed:
        out.append("➖ " + ", ".join(_pname(r) for r in removed))
    return "\n".join(out)


def _overwrite_diff(before: dict, after: dict) -> str:
    def label(t):
        return f"@{t.name}" if isinstance(t, discord.Role) else str(t)
    lines = []
    for t in set(before) | set(after):
        b, a = before.get(t), after.get(t)
        if b == a:
            continue
        if b is None:
            lines.append(f"➕ Rechte für {label(t)} angelegt")
        elif a is None:
            lines.append(f"➖ Rechte für {label(t)} entfernt")
        ch = []
        bd, ad = dict(b or discord.PermissionOverwrite()), dict(a or discord.PermissionOverwrite())
        for k, v in ad.items():
            if bd.get(k) != v:
                sym = {True: "✅", False: "❌", None: "➖"}
                ch.append(f"{_pname(k)} {sym[bd.get(k)]}→{sym[v]}")
        if ch:
            lines.append(f"{label(t)}: " + ", ".join(ch))
    return "\n".join(lines)


# ---- Nachrichten --------------------------------------------------
@bot.event
async def on_raw_message_edit(payload: discord.RawMessageUpdateEvent):
    if not payload.guild_id:
        return
    guild = bot.get_guild(payload.guild_id)
    if guild is None:
        return
    after = getattr(payload, "message", None)
    before = payload.cached_message
    author = after.author if after else (before.author if before else None)
    if author is None or author.bot:
        return
    channel = guild.get_channel_or_thread(payload.channel_id)
    if _is_log_channel(channel):
        return
    new = after.content if after else payload.data.get("content")
    old = before.content if before else None
    if new is None or (before is not None and old == new):
        return  # nur Embed/Vorschau aktualisiert, kein echter Edit
    link = f"https://discord.com/channels/{guild.id}/{payload.channel_id}/{payload.message_id}"
    await modlog(guild, "✏️ Nachricht bearbeitet", f"{author.mention} in <#{payload.channel_id}> · [Zur Nachricht]({link})",
                 C_EDIT, [("Vorher", old if before else "*nicht bekannt – Nachricht ist älter als der letzte Bot-Neustart*", False),
                          ("Nachher", new or "*leer*", False),
                          ("User", _who(author), False)], thumb=author.display_avatar.url)


@bot.event
async def on_raw_message_delete(payload: discord.RawMessageDeleteEvent):
    if not payload.guild_id:
        return
    guild = bot.get_guild(payload.guild_id)
    channel = guild.get_channel_or_thread(payload.channel_id) if guild else None
    if guild is None or _is_log_channel(channel):
        return
    msg = payload.cached_message
    if msg and msg.author.bot:
        return
    if msg is None:
        return await modlog(guild, "🗑️ Nachricht gelöscht", f"In <#{payload.channel_id}>", C_DEL,
                            [("Inhalt", "*nicht bekannt – Nachricht ist älter als der letzte Bot-Neustart*", False),
                             ("Nachrichten-ID", str(payload.message_id), False)])
    actor, _ = await audit_actor(guild, discord.AuditLogAction.message_delete, msg.author.id, within=10)
    files = "\n".join(f"📎 {a.filename} ({round(a.size / 1024)} KB)" for a in msg.attachments)
    fields = [("Inhalt", msg.content or "*kein Text*", False)]
    if files:
        fields.append(("Anhänge", files, False))
    if msg.stickers:
        fields.append(("Sticker", ", ".join(s.name for s in msg.stickers), False))
    fields += [("Geschrieben am", _ts(msg.created_at), True), ("User", _who(msg.author), False)]
    await modlog(guild, "🗑️ Nachricht gelöscht", f"Von {msg.author.mention} in {msg.channel.mention}", C_DEL,
                 fields, actor=actor if actor and actor.id != msg.author.id else None, thumb=msg.author.display_avatar.url)


@bot.event
async def on_raw_bulk_message_delete(payload: discord.RawBulkMessageDeleteEvent):
    guild = bot.get_guild(payload.guild_id) if payload.guild_id else None
    channel = guild.get_channel_or_thread(payload.channel_id) if guild else None
    if guild is None or _is_log_channel(channel):
        return
    actor, _ = await audit_actor(guild, discord.AuditLogAction.message_bulk_delete, within=15)
    lines = [f"**{m.author}**: {_cut(m.content or '[Anhang/Embed]', 150)}"
             for m in sorted(payload.cached_messages, key=lambda m: m.created_at) if not m.author.bot]
    await modlog(guild, f"🧹 {len(payload.message_ids)} Nachrichten auf einmal gelöscht", f"In <#{payload.channel_id}>",
                 C_DEL, [("Bekannte Inhalte", "\n".join(lines[-25:]) or "*keine im Speicher*", False)], actor=actor)


@bot.event
async def on_raw_reaction_add(payload: discord.RawReactionActionEvent):
    await _log_reaction(payload, "➕ Reaktion hinzugefügt", C_NEW)


@bot.event
async def on_raw_reaction_remove(payload: discord.RawReactionActionEvent):
    await _log_reaction(payload, "➖ Reaktion entfernt", C_DEL)


async def _log_reaction(payload, title, color):
    if not payload.guild_id:
        return
    guild = bot.get_guild(payload.guild_id)
    channel = guild.get_channel_or_thread(payload.channel_id) if guild else None
    user = guild.get_member(payload.user_id) if guild else None
    if guild is None or _is_log_channel(channel) or (user and user.bot):
        return
    link = f"https://discord.com/channels/{guild.id}/{payload.channel_id}/{payload.message_id}"
    who = user.mention if user else f"<@{payload.user_id}>"
    await modlog(guild, title, f"{payload.emoji} von {who} in <#{payload.channel_id}> · [Zur Nachricht]({link})", color)


@bot.event
async def on_guild_channel_pins_update(channel, last_pin):
    if _is_log_channel(channel):
        return
    actor, _ = await audit_actor(channel.guild, discord.AuditLogAction.message_pin, within=10)
    if actor is None:
        actor, _ = await audit_actor(channel.guild, discord.AuditLogAction.message_unpin, within=10)
    await modlog(channel.guild, "📌 Angepinnte Nachrichten geändert", f"In {channel.mention}", C_UPD, actor=actor)


# ---- Mitglieder ---------------------------------------------------
@bot.listen("on_member_join")
async def ml_member_join(member: discord.Member):
    age = (discord.utils.utcnow() - member.created_at).days
    actor = None
    if member.bot:
        actor, _ = await audit_actor(member.guild, discord.AuditLogAction.bot_add, member.id)
    await modlog(member.guild, "🤖 Bot hinzugefügt" if member.bot else "📥 Mitglied beigetreten",
                 _who(member), C_NEW,
                 [("Account erstellt", f"{_ts(member.created_at)} · {age} Tage alt" + (" ⚠️ sehr neu" if age < 7 else ""), False),
                  ("Mitglieder jetzt", str(member.guild.member_count), True)],
                 actor=actor, thumb=member.display_avatar.url)


@bot.listen("on_raw_member_remove")
async def ml_member_remove(payload: discord.RawMemberRemoveEvent):
    guild = bot.get_guild(payload.guild_id)
    user = payload.user
    if guild is None:
        return
    actor, reason = await audit_actor(guild, discord.AuditLogAction.kick, user.id, within=15)
    roles = ""
    if isinstance(user, discord.Member):
        roles = ", ".join(r.mention for r in user.roles if not r.is_default())
    fields = [("Rollen", roles or "–", False)]
    if isinstance(user, discord.Member) and user.joined_at:
        fields.append(("War dabei seit", _ts(user.joined_at), True))
    if actor:
        await modlog(guild, "👢 Mitglied gekickt", _who(user), C_DEL, fields, actor=actor, reason=reason,
                     thumb=user.display_avatar.url)
    else:
        await modlog(guild, "📤 Mitglied hat den Server verlassen", _who(user), C_DEL, fields, thumb=user.display_avatar.url)


@bot.listen("on_member_update")
async def ml_member_update(before: discord.Member, after: discord.Member):
    g = after.guild
    if before.nick != after.nick:
        actor, _ = await audit_actor(g, discord.AuditLogAction.member_update, after.id)
        await modlog(g, "🏷️ Server-Nickname geändert", _who(after), C_MEMBER,
                     [("Vorher", before.nick or f"*kein Nickname* ({before.name})", True),
                      ("Nachher", after.nick or f"*kein Nickname* ({after.name})", True)],
                     actor=actor if actor and actor.id != after.id else None, thumb=after.display_avatar.url)
    added = [r for r in after.roles if r not in before.roles]
    removed = [r for r in before.roles if r not in after.roles]
    if added or removed:
        actor, reason = await audit_actor(g, discord.AuditLogAction.member_role_update, after.id)
        f = []
        if added:
            f.append(("➕ Rolle bekommen", ", ".join(r.mention for r in added), False))
        if removed:
            f.append(("➖ Rolle entfernt", ", ".join(r.mention for r in removed), False))
        await modlog(g, "🎭 Rollen geändert", _who(after), C_MEMBER, f, actor=actor, reason=reason)
    if before.timed_out_until != after.timed_out_until:
        actor, reason = await audit_actor(g, discord.AuditLogAction.member_update, after.id)
        if after.timed_out_until and after.timed_out_until > discord.utils.utcnow():
            await modlog(g, "⏳ Timeout vergeben", _who(after), C_DEL,
                         [("Bis", _ts(after.timed_out_until), False)], actor=actor, reason=reason)
        else:
            await modlog(g, "✅ Timeout aufgehoben", _who(after), C_NEW, actor=actor, reason=reason)
    if before.guild_avatar != after.guild_avatar:
        await modlog(g, "🖼️ Server-Profilbild geändert", _who(after), C_MEMBER,
                     [("Vorher", before.guild_avatar.url if before.guild_avatar else "*keins*", False),
                      ("Nachher", after.guild_avatar.url if after.guild_avatar else "*keins*", False)],
                     thumb=after.guild_avatar.url if after.guild_avatar else None)
    if before.pending and not after.pending:
        await modlog(g, "📋 Regeln im Onboarding akzeptiert", _who(after), C_NEW)


@bot.event
async def on_user_update(before: discord.User, after: discord.User):
    changes = []
    if before.name != after.name:
        changes.append(("Username", f"`{before.name}` → `{after.name}`", False))
    if before.global_name != after.global_name:
        changes.append(("Anzeigename", f"{before.global_name or '–'} → {after.global_name or '–'}", False))
    if before.avatar != after.avatar:
        changes.append(("Profilbild", f"[Vorher]({before.display_avatar.url}) → [Nachher]({after.display_avatar.url})", False))
    if before.banner != getattr(after, "banner", None) and getattr(before, "banner", None) is not None:
        changes.append(("Banner", "geändert", False))
    if not changes:
        return
    for g in bot.guilds:
        if g.get_member(after.id):
            await modlog(g, "👤 Profil geändert", _who(after), C_MEMBER, changes, thumb=after.display_avatar.url)


@bot.event
async def on_voice_state_update(member: discord.Member, before: discord.VoiceState, after: discord.VoiceState):
    g = member.guild
    if before.channel != after.channel:
        if before.channel is None:
            return await modlog(g, "🔊 Voice betreten", f"{member.mention} → {after.channel.mention}", C_VOICE)
        if after.channel is None:
            actor, _ = await audit_actor(g, discord.AuditLogAction.member_disconnect, within=10)
            return await modlog(g, "🔇 Voice verlassen", f"{member.mention} ← {before.channel.mention}", C_VOICE,
                                actor=actor if actor and actor.id != member.id else None)
        actor, _ = await audit_actor(g, discord.AuditLogAction.member_move, within=10)
        return await modlog(g, "🔀 Voice gewechselt", f"{member.mention}: {before.channel.mention} → {after.channel.mention}",
                            C_VOICE, actor=actor if actor and actor.id != member.id else None)
    states = []
    for attr, on_txt, off_txt in (("mute", "vom Team stummgeschaltet", "Stummschaltung (Team) aufgehoben"),
                                  ("deaf", "vom Team taub geschaltet", "Taubschaltung (Team) aufgehoben"),
                                  ("self_mute", "Mikro aus", "Mikro an"), ("self_deaf", "Ton aus", "Ton an"),
                                  ("self_stream", "Bildschirm wird übertragen", "Übertragung beendet"),
                                  ("self_video", "Kamera an", "Kamera aus")):
        b, a = getattr(before, attr), getattr(after, attr)
        if b != a:
            states.append(on_txt if a else off_txt)
    if states and after.channel:
        actor = None
        if before.mute != after.mute or before.deaf != after.deaf:
            actor, _ = await audit_actor(g, discord.AuditLogAction.member_update, member.id)
        await modlog(g, "🎙️ Voice-Status", f"{member.mention} in {after.channel.mention}\n" + "\n".join(f"• {s}" for s in states),
                     C_VOICE, actor=actor)


@bot.listen("on_member_ban")
async def ml_ban(guild: discord.Guild, user):
    actor, reason = await audit_actor(guild, discord.AuditLogAction.ban, user.id)
    await modlog(guild, "🔨 Gebannt", _who(user), C_DEL, actor=actor, reason=reason, thumb=user.display_avatar.url)


@bot.event
async def on_member_unban(guild: discord.Guild, user):
    actor, reason = await audit_actor(guild, discord.AuditLogAction.unban, user.id)
    await modlog(guild, "♻️ Entbannt", _who(user), C_NEW, actor=actor, reason=reason)


# ---- Kanäle, Threads, Rollen -------------------------------------
@bot.event
async def on_guild_channel_create(channel):
    actor, _ = await audit_actor(channel.guild, discord.AuditLogAction.channel_create, channel.id)
    await modlog(channel.guild, "📁 Kanal erstellt", f"{channel.mention} · `{channel.name}`", C_NEW,
                 [("Typ", str(channel.type), True), ("Kategorie", channel.category.name if channel.category else "–", True)],
                 actor=actor)


@bot.listen("on_guild_channel_delete")
async def ml_channel_delete(channel):
    actor, _ = await audit_actor(channel.guild, discord.AuditLogAction.channel_delete, channel.id)
    await modlog(channel.guild, "🗑️ Kanal gelöscht", f"`{channel.name}`", C_DEL,
                 [("Typ", str(channel.type), True), ("Kategorie", channel.category.name if channel.category else "–", True)],
                 actor=actor)


@bot.event
async def on_guild_channel_update(before, after):
    if _is_log_channel(after) and before.name == after.name:
        return
    f = []
    if before.name != after.name:
        f.append(("Name", f"`{before.name}` → `{after.name}`", False))
    if getattr(before, "topic", None) != getattr(after, "topic", None):
        f.append(("Thema vorher", before.topic or "–", False))
        f.append(("Thema nachher", after.topic or "–", False))
    if before.category != after.category:
        f.append(("Kategorie", f"{before.category.name if before.category else '–'} → {after.category.name if after.category else '–'}", False))
    for attr, label in (("slowmode_delay", "Slowmode (s)"), ("nsfw", "NSFW"), ("bitrate", "Bitrate"),
                        ("user_limit", "User-Limit")):
        if getattr(before, attr, None) != getattr(after, attr, None):
            f.append((label, f"{getattr(before, attr, None)} → {getattr(after, attr, None)}", True))
    ow = _overwrite_diff(before.overwrites, after.overwrites)
    if ow:
        f.append(("Rechte", ow, False))
    if not f:
        return
    actor, _ = await audit_actor(after.guild, discord.AuditLogAction.channel_update, after.id)
    if actor is None and ow:
        for act in (discord.AuditLogAction.overwrite_update, discord.AuditLogAction.overwrite_create,
                    discord.AuditLogAction.overwrite_delete):
            actor, _ = await audit_actor(after.guild, act, after.id)
            if actor:
                break
    if actor and actor.id == bot.user.id:
        return  # eigene Ticket-Umbenennungen stehen schon in #ticket-logs
    await modlog(after.guild, "🛠️ Kanal geändert", after.mention, C_UPD, f, actor=actor)


@bot.event
async def on_thread_create(thread: discord.Thread):
    await modlog(thread.guild, "🧵 Thread erstellt", f"{thread.mention} in {thread.parent.mention if thread.parent else '–'}",
                 C_NEW, [("Erstellt von", _who(thread.owner) if thread.owner else f"<@{thread.owner_id}>", False)])


@bot.event
async def on_thread_delete(thread: discord.Thread):
    actor, _ = await audit_actor(thread.guild, discord.AuditLogAction.thread_delete, thread.id)
    await modlog(thread.guild, "🧵 Thread gelöscht", f"`{thread.name}`", C_DEL, actor=actor)


@bot.event
async def on_thread_update(before: discord.Thread, after: discord.Thread):
    f = []
    if before.name != after.name:
        f.append(("Name", f"`{before.name}` → `{after.name}`", False))
    if before.archived != after.archived:
        f.append(("Archiviert", "ja" if after.archived else "nein", True))
    if before.locked != after.locked:
        f.append(("Gesperrt", "ja" if after.locked else "nein", True))
    if f:
        await modlog(after.guild, "🧵 Thread geändert", after.mention, C_UPD, f)


@bot.event
async def on_guild_role_create(role: discord.Role):
    actor, _ = await audit_actor(role.guild, discord.AuditLogAction.role_create, role.id)
    await modlog(role.guild, "🎭 Rolle erstellt", f"{role.mention} · `{role.name}`", C_NEW, actor=actor)


@bot.listen("on_guild_role_delete")
async def ml_role_delete(role: discord.Role):
    actor, _ = await audit_actor(role.guild, discord.AuditLogAction.role_delete, role.id)
    await modlog(role.guild, "🗑️ Rolle gelöscht", f"`{role.name}`", C_DEL, actor=actor)


@bot.event
async def on_guild_role_update(before: discord.Role, after: discord.Role):
    f = []
    if before.name != after.name:
        f.append(("Name", f"`{before.name}` → `{after.name}`", False))
    if before.color != after.color:
        f.append(("Farbe", f"{before.color} → {after.color}", True))
    if before.hoist != after.hoist:
        f.append(("Getrennt anzeigen", "ja" if after.hoist else "nein", True))
    if before.mentionable != after.mentionable:
        f.append(("Erwähnbar", "ja" if after.mentionable else "nein", True))
    perms = _perm_diff(before.permissions, after.permissions)
    if perms:
        f.append(("Berechtigungen", perms, False))
    if not f:
        return  # nur Position verschoben
    actor, _ = await audit_actor(after.guild, discord.AuditLogAction.role_update, after.id)
    await modlog(after.guild, "🎭 Rolle geändert", after.mention, C_UPD, f, actor=actor)


# ---- Server, Invites, Emojis, Webhooks, Events, AutoMod -----------
@bot.event
async def on_guild_update(before: discord.Guild, after: discord.Guild):
    f = []
    for attr, label in (("name", "Name"), ("description", "Beschreibung"), ("verification_level", "Verifizierungsstufe"),
                        ("explicit_content_filter", "Inhaltsfilter"), ("default_notifications", "Benachrichtigungen"),
                        ("mfa_level", "2FA für Moderation"), ("afk_channel", "AFK-Kanal"), ("afk_timeout", "AFK-Zeit"),
                        ("system_channel", "Systemkanal"), ("rules_channel", "Regelkanal"), ("owner_id", "Owner-ID"),
                        ("preferred_locale", "Sprache")):
        b, a = getattr(before, attr, None), getattr(after, attr, None)
        if b != a:
            f.append((label, f"{b} → {a}", False))
    for attr, label in (("icon", "Server-Icon"), ("banner", "Server-Banner"), ("splash", "Einladungs-Hintergrund")):
        if getattr(before, attr, None) != getattr(after, attr, None):
            f.append((label, "geändert", True))
    if not f:
        return
    actor, _ = await audit_actor(after, discord.AuditLogAction.guild_update)
    await modlog(after, "⚙️ Server-Einstellungen geändert", "", C_UPD, f, actor=actor,
                 thumb=after.icon.url if after.icon else None)


@bot.event
async def on_invite_create(invite: discord.Invite):
    if invite.guild is None:
        return
    g = bot.get_guild(invite.guild.id)
    await modlog(g, "🔗 Einladung erstellt", f"`discord.gg/{invite.code}`", C_NEW,
                 [("Kanal", invite.channel.mention if invite.channel else "–", True),
                  ("Max. Nutzungen", str(invite.max_uses or "∞"), True),
                  ("Gültig", f"{invite.max_age // 3600} Std" if invite.max_age else "dauerhaft", True),
                  ("Temporär", "ja" if invite.temporary else "nein", True)],
                 actor=invite.inviter)


@bot.event
async def on_invite_delete(invite: discord.Invite):
    if invite.guild is None:
        return
    g = bot.get_guild(invite.guild.id)
    actor, _ = await audit_actor(g, discord.AuditLogAction.invite_delete)
    await modlog(g, "🔗 Einladung gelöscht", f"`discord.gg/{invite.code}`", C_DEL, actor=actor)


@bot.event
async def on_guild_emojis_update(guild: discord.Guild, before, after):
    if guild == main_guild():
        refresh_icon_map(guild)
    b, a = {e.id: e for e in before}, {e.id: e for e in after}
    f = []
    for i in a.keys() - b.keys():
        f.append(("➕ Emoji hinzugefügt", f"{a[i]} `:{a[i].name}:`", True))
    for i in b.keys() - a.keys():
        f.append(("➖ Emoji entfernt", f"`:{b[i].name}:`", True))
    for i in a.keys() & b.keys():
        if a[i].name != b[i].name:
            f.append(("✏️ Emoji umbenannt", f"`:{b[i].name}:` → `:{a[i].name}:`", True))
    if f:
        await modlog(guild, "😀 Emojis geändert", "", C_UPD, f)


@bot.event
async def on_guild_stickers_update(guild: discord.Guild, before, after):
    b, a = {s.id: s.name for s in before}, {s.id: s.name for s in after}
    f = [("➕ Sticker hinzugefügt", a[i], True) for i in a.keys() - b.keys()]
    f += [("➖ Sticker entfernt", b[i], True) for i in b.keys() - a.keys()]
    f += [("✏️ Sticker umbenannt", f"{b[i]} → {a[i]}", True) for i in a.keys() & b.keys() if a[i] != b[i]]
    if f:
        await modlog(guild, "🏷️ Sticker geändert", "", C_UPD, f)


@bot.event
async def on_webhooks_update(channel):
    actor = None
    for act in (discord.AuditLogAction.webhook_create, discord.AuditLogAction.webhook_update,
                discord.AuditLogAction.webhook_delete):
        actor, _ = await audit_actor(channel.guild, act)
        if actor:
            break
    await modlog(channel.guild, "🪝 Webhooks geändert", f"In {channel.mention} · bitte prüfen, falls unbekannt",
                 C_UPD, actor=actor)


@bot.event
async def on_scheduled_event_create(event: discord.ScheduledEvent):
    await modlog(event.guild, "📅 Event erstellt", f"**{event.name}**", C_NEW,
                 [("Start", _ts(event.start_time), True)], actor=event.creator)


@bot.event
async def on_scheduled_event_delete(event: discord.ScheduledEvent):
    await modlog(event.guild, "📅 Event gelöscht", f"**{event.name}**", C_DEL)


@bot.event
async def on_automod_action(execution: discord.AutoModAction):
    g = execution.guild
    member = g.get_member(execution.user_id)
    await modlog(g, "🤖 AutoMod hat eingegriffen", _who(member) if member else f"<@{execution.user_id}>", C_DEL,
                 [("Aktion", str(execution.action.type), True), ("Treffer", execution.matched_keyword or "–", True),
                  ("Inhalt", execution.content or "–", False)])


@bot.listen("on_app_command_completion")
async def ml_command_used(interaction: discord.Interaction, command):
    if interaction.guild is None:
        return
    opts = ""
    data = interaction.data or {}
    for o in data.get("options", []) or []:
        if "value" in o:
            opts += f" {o['name']}:{_cut(o['value'], 80)}"
        for sub in o.get("options", []) or []:
            if "value" in sub:
                opts += f" {sub['name']}:{_cut(sub['value'], 80)}"
    await modlog(interaction.guild, "⌨️ Befehl benutzt",
                 f"`/{command.qualified_name}{opts}` von {interaction.user.mention} in <#{interaction.channel_id}>", C_EDIT)


# ===============================================================
# STATISTIK-CHANNELS
# ===============================================================
@tasks.loop(minutes=10)
async def update_stats():
    cnt, avg = await pool.fetchrow("SELECT count(*), avg(stars) FROM reviews")
    for guild in bot.guilds:
        for ch in guild.voice_channels:
            new = None
            if ch.name.startswith("👥 Mitglieder:"):
                new = f"👥 Mitglieder: {guild.member_count}"
            elif ch.name.startswith("⭐ Bewertungen:"):
                new = (f"⭐ Bewertungen: {float(avg):.1f}/5 ({cnt})" if cnt
                       else "⭐ Bewertungen: bald verfügbar")
            elif "Status:" in ch.name:
                new = status_voice_name()
            if new and ch.name != new:
                try:
                    await ch.edit(name=new, reason="VOLT Statistik")
                except discord.HTTPException:
                    pass


@update_stats.before_loop
async def _before_stats():
    await bot.wait_until_ready()


# ===============================================================
# WEBSITE
# Läuft im selben Railway-Service wie der Bot und liest dieselbe
# Datenbank. Nach außen gehen NUR Zusammenfassungen: keine IDs,
# keine Namen, keine Ticket-Inhalte.
# ===============================================================
WEB_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "web")
WEB_PAGES = {"index", "volt-bot", "familien-dashboard", "fussball-manager", "routen-system", "impressum", "datenschutz", "bot-bedingungen"}
SITEMAP_PAGES = ("", "volt-bot", "familien-dashboard", "fussball-manager", "routen-system", "impressum", "datenschutz", "bot-bedingungen")
# Saubere Adressen ohne .html. Alte Adressen leiten dauerhaft weiter, damit geteilte Links nicht ins Leere laufen.
WEB_REDIRECTS = {"index": "/", "fraktion": "/familien-dashboard", "streamer": "/"}
STATS_TTL = 60          # Sekunden, so oft wird die Datenbank höchstens gelesen
COUNTS_TTL = 300        # Sekunden, so oft werden Mitglieder/Online von Discord geholt
_site = {"t": 0.0, "data": None, "counts_t": 0.0, "members": None, "online": None}
_site_lock = asyncio.Lock()
_site_runner = None
STRIP_RE = re.compile(r"<[@#][!&]?\d+>|<a?:\w+:\d+>|https?://\S+|discord(?:app)?\.(?:gg|com/invite)/\S+", re.I)

for _ext, _type in ((".woff2", "font/woff2"), (".webp", "image/webp"), (".svg", "image/svg+xml")):
    mimetypes.add_type(_type, _ext)

SITE_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=(), payment=()",
    "Content-Security-Policy": (
        "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; "
        "script-src 'self'; font-src 'self'; connect-src 'self'; object-src 'none'; "
        "base-uri 'self'; form-action 'none'; frame-ancestors 'none'"),
}


def invalidate_site_cache():
    _site["t"] = 0.0


def clean_comment(text) -> str:
    if not text:
        return ""
    text = STRIP_RE.sub("", str(text))
    text = re.sub(r"\s+", " ", text).strip()
    return text[:197].rstrip() + "…" if len(text) > 200 else text


async def refresh_guild_counts():
    now = time.time()
    if now - _site["counts_t"] < COUNTS_TTL:
        return
    _site["counts_t"] = now
    gid = GUILD_ID or (bot.guilds[0].id if bot.guilds else None)
    if not gid:
        return
    try:
        g = await bot.fetch_guild(gid, with_counts=True)
        _site["members"] = g.approximate_member_count
        _site["online"] = g.approximate_presence_count
    except discord.HTTPException:
        pass


async def build_site_stats() -> dict:
    rows = await pool.fetch("SELECT status, count(*) AS n FROM tickets WHERE status<>'deleted' GROUP BY status")
    c = defaultdict(int, {r["status"]: int(r["n"]) for r in rows})

    now = time.time()
    # Werkbank: welche Tickets liegen per /platz auf Platz 1/2, läuft die Uhr?
    slots = []
    busy_ids = set()
    for n in range(1, MAX_PARALLEL + 1):
        t = await pool.fetchrow(
            "SELECT id, project_type FROM tickets WHERE slot=$1 AND status NOT IN ('archived','rejected','deleted')", n)
        if not t:
            slots.append({"n": n, "busy": False})
            continue
        busy_ids.add(t["id"])
        slots.append({"n": n, "busy": True, "type": (t["project_type"] or "Projekt")[:40],
                      "running": await timer_running(t["id"]), "seconds": int(await work_seconds(t["id"]))})

    active = len(busy_ids)                          # gerade auf der Werkbank
    running = c["running"] + c["maintenance"]      # live beim Kunden
    new_requests = c["open"]                       # noch nicht bearbeitet
    accepted = await pool.fetchval(
        "SELECT count(*) FROM tickets WHERE status IN ('progress','paused') AND slot IS NULL") or 0
    queue = int(accepted) + new_requests           # bestätigt oder neu, aber noch nicht auf der Werkbank
    percent = round(active / MAX_PARALLEL * 100)
    if active >= MAX_PARALLEL and queue:
        label = "Warteschlange aktiv"
    elif percent >= 100:
        label = "Voll ausgelastet"
    elif percent >= 50:
        label = "Gut ausgelastet"
    else:
        label = "Freie Kapazität"
    backlog = active + queue
    wait_days = math.ceil(backlog / PROJECTS_PER_DAY) if backlog else 0

    b = await pool.fetchrow(
        "SELECT count(*) AS n, avg(julianday(live_at) - julianday(accepted_at)) AS d FROM tickets "
        "WHERE accepted_at IS NOT NULL AND live_at IS NOT NULL")
    samples = int(b["n"] or 0)
    build_days = round(max(float(b["d"]), 0.1), 1) if samples >= 3 and b["d"] is not None else None
    # Gestoppte Arbeitszeit pro fertigem Projekt (aus /platz + /zeit)
    w = await pool.fetchrow(
        "SELECT count(*) AS n, avg(s) AS a FROM (SELECT ws.ticket_id, sum(coalesce(ws.ended_at, $1) - ws.started_at) AS s "
        "FROM work_sessions ws JOIN tickets t ON t.id = ws.ticket_id "
        "WHERE t.status IN ('running','maintenance','archived') GROUP BY ws.ticket_id HAVING s > 60)", now)
    work_samples = int(w["n"] or 0)
    avg_work = int(w["a"]) if work_samples and w["a"] is not None else None

    count, avg, dist = await review_summary()
    latest = []
    for r in await pool.fetch(
            "SELECT r.stars, r.comment, r.created_at, t.project_type FROM reviews r "
            "LEFT JOIN tickets t ON t.id = r.ticket_id ORDER BY r.id DESC LIMIT 3"):
        latest.append({
            "stars": int(r["stars"] or 0),
            "text": clean_comment(r["comment"]),
            "type": (r["project_type"] or "Projekt")[:40],
            "month": str(r["created_at"] or "")[:7],
        })

    await refresh_guild_counts()
    return {
        "ok": True,
        "updated": discord.utils.utcnow().isoformat(timespec="seconds"),
        "invite": DISCORD_INVITE_URL,
        "discord": {"members": _site["members"], "online": _site["online"]},
        "system": system_summary(),
        "projects": {"running": running, "active": active, "paused": c["paused"],
                     "requests": new_requests, "done": c["archived"]},
        "workload": {"active": active, "capacity": MAX_PARALLEL, "percent": percent, "label": label,
                     "queue": queue, "wait_days": wait_days, "per_day": PROJECTS_PER_DAY, "slots": slots},
        "build": {"avg_days": build_days, "samples": samples,
                  "avg_work_seconds": avg_work, "work_samples": work_samples},
        "team": {"people": 1},
        "reviews": {"count": count, "avg": round(avg, 2) if avg is not None else None,
                    "label": rating_label(avg, count), "dist": {str(k): v for k, v in dist.items()},
                    "latest": latest},
    }


async def api_stats(request: web.Request) -> web.Response:
    if pool is None:
        return web.json_response({"ok": False}, status=503, headers={"Cache-Control": "no-store"})
    async with _site_lock:
        if _site["data"] is None or time.time() - _site["t"] > STATS_TTL:
            try:
                _site["data"] = await build_site_stats()
                _site["t"] = time.time()
            except Exception as e:  # nie Details nach außen geben
                print("Website-Statistik Fehler:", repr(e))
                if _site["data"] is None:
                    return web.json_response({"ok": False}, status=503, headers={"Cache-Control": "no-store"})
    return web.json_response(_site["data"], headers={"Cache-Control": "public, max-age=30"})


def _redirect(location: str, request: web.Request) -> web.Response:
    if request.query_string:
        location += "?" + request.query_string
    return web.Response(status=301, headers={"Location": location, "Cache-Control": "public, max-age=3600"})


async def site_page(request: web.Request) -> web.StreamResponse:
    name = request.match_info.get("name", "index")
    if name.endswith(".html"):  # alte Links mit .html -> saubere Adresse
        base = name[:-5]
        if base in WEB_REDIRECTS:
            return _redirect(WEB_REDIRECTS[base], request)
        if base in WEB_PAGES:
            return _redirect(f"/{base}", request)
        raise web.HTTPNotFound()
    if request.path != "/" and name in WEB_REDIRECTS:
        return _redirect(WEB_REDIRECTS[name], request)
    path = os.path.join(WEB_DIR, f"{name}.html")
    if name not in WEB_PAGES or not os.path.isfile(path):
        raise web.HTTPNotFound()
    return web.FileResponse(path, headers={"Cache-Control": "no-cache", "Content-Type": "text/html; charset=utf-8"})


async def site_slash(request: web.Request) -> web.Response:
    """/familien-dashboard/ -> /familien-dashboard"""
    name = request.match_info.get("name", "")
    if name in WEB_PAGES or name in WEB_REDIRECTS:
        return _redirect(WEB_REDIRECTS.get(name, f"/{name}"), request)
    raise web.HTTPNotFound()


@web.middleware
async def site_middleware(request: web.Request, handler):
    try:
        resp = await handler(request)
    except web.HTTPNotFound:
        resp = web.Response(status=404, content_type="text/html", text=(
            "<!doctype html><meta charset='utf-8'><title>Nicht gefunden · VOLT</title>"
            "<link rel='stylesheet' href='/assets/site.css'><main class='nf'><p class='eyebrow'>Fehler 404</p>"
            "<h1>Hier ist kein Strom.</h1><p>Diese Seite gibt es nicht.</p>"
            "<a class='btn btn-red' href='/'>Zur Startseite</a></main>"))
    except web.HTTPException as ex:
        resp = web.Response(status=ex.status, text=ex.reason or "Fehler")
    resp.headers.update(SITE_HEADERS)
    if request.path.startswith("/assets/") and resp.status == 200:
        resp.headers["Cache-Control"] = "public, max-age=86400"
        ext = os.path.splitext(request.path)[1].lower()
        fixed = {".woff2": "font/woff2", ".webp": "image/webp", ".svg": "image/svg+xml"}
        if ext in fixed:
            resp.headers["Content-Type"] = fixed[ext]
    return resp


async def site_robots(request: web.Request) -> web.Response:
    return web.Response(text=f"User-agent: *\nAllow: /\nDisallow: /api/\nSitemap: {SITE_URL}/sitemap.xml\n")


async def site_sitemap(request: web.Request) -> web.Response:
    urls = "".join(f"<url><loc>{SITE_URL}/{p}</loc></url>" for p in SITEMAP_PAGES)
    return web.Response(content_type="application/xml",
                        text=f'<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{urls}</urlset>')


async def site_health(request: web.Request) -> web.Response:
    return web.Response(text="ok", headers={"Cache-Control": "no-store"})


async def start_website():
    global _site_runner
    if not SITE_ENABLED:
        print("Website: SITE_ENABLED=0, Website bleibt aus.")
        return
    if not os.path.isdir(WEB_DIR):
        print(f"Website: Ordner 'web' fehlt (gesucht in {WEB_DIR}). Lege ihn neben bot.py ab.")
        return
    app = web.Application(middlewares=[site_middleware])
    app.router.add_get("/api/stats", api_stats)
    app.router.add_post("/api/heartbeat", api_heartbeat)
    app.router.add_post("/api/admin/bots", api_admin_bots)
    app.router.add_post("/api/admin/uptime", api_admin_uptime)
    app.router.add_post("/api/system-hook", api_system_hook)
    app.router.add_get("/health", site_health)
    app.router.add_get("/robots.txt", site_robots)
    app.router.add_get("/sitemap.xml", site_sitemap)
    app.router.add_static("/assets/", os.path.join(WEB_DIR, "assets"), show_index=False, follow_symlinks=False)
    app.router.add_get("/", site_page)
    app.router.add_get("/{name}", site_page)
    app.router.add_get("/{name}/", site_slash)
    _site_runner = web.AppRunner(app, access_log=None)
    await _site_runner.setup()
    await web.TCPSite(_site_runner, "0.0.0.0", SITE_PORT).start()
    src = "aus Railway-Variable PORT" if os.environ.get("PORT") else "Standard, PORT nicht gesetzt"
    print(f"Website läuft auf Port {SITE_PORT} ({src}) → {SITE_URL}")


async def migrate_db():
    cols = {r[1] for r in await pool.fetch("PRAGMA table_info(tickets)")}
    for col in ("accepted_at", "live_at", "ingame", "ranks", "has_discord"):
        if col not in cols:
            await pool.execute(f"ALTER TABLE tickets ADD COLUMN {col} TEXT")
    if "slot" not in cols:
        await pool.execute("ALTER TABLE tickets ADD COLUMN slot INTEGER")
    if "reject_reason" not in cols:
        await pool.execute("ALTER TABLE tickets ADD COLUMN reject_reason TEXT")
    bcols = {r[1] for r in await pool.fetch("PRAGMA table_info(blacklist)")}
    for col in ("until", "mod_id"):
        if col not in bcols:
            await pool.execute(f"ALTER TABLE blacklist ADD COLUMN {col} INTEGER")
    rcols = {r[1] for r in await pool.fetch("PRAGMA table_info(reviews)")}
    if "message_id" not in rcols:
        await pool.execute("ALTER TABLE reviews ADD COLUMN message_id INTEGER")
    # Umbenennung: Routen-System → Routen Manager (bestehende Tickets und Bot-Einträge mitnehmen)
    await pool.execute("UPDATE tickets SET project_type=$1 WHERE project_type=$2", "🗺️ Routen Manager", "🗺️ Routen-System")
    await pool.execute("UPDATE bots SET product=$1 WHERE product=$2", "Routen Manager", "Routen-System")


# ===============================================================
# START
# ===============================================================
@bot.event
async def setup_hook():
    global pool
    pool = DB(DB_PATH)
    await pool.connect()
    await migrate_db()
    print(f"Datenbank: {DB_PATH}")
    await load_status_state()
    await refresh_bots_cache()
    for v in (VerifyView(), TicketPanelView(), LegacyTicketButtonView(), AdminPanelView(), OfferView(),
              ReviewView(), FaqView(), SupportTicketView()):
        bot.add_view(v)
    if GUILD_ID:
        g = discord.Object(id=GUILD_ID)
        bot.tree.copy_global_to(guild=g)
        synced = await bot.tree.sync(guild=g)
        # Alte globale Befehle (z. B. /security-status vom alten Bot) bei Discord entfernen
        bot.tree.clear_commands(guild=None)
        await bot.tree.sync()
        print(f"{len(synced)} Befehle im Server {GUILD_ID} aktiv, alte globale Befehle entfernt.")
    else:
        synced = await bot.tree.sync()
        print(f"{len(synced)} globale Befehle aktiv.")
    update_stats.start()
    uptime_monitor.start()


_cleaned_guild_commands = False


async def sync_avatar():
    """Profilbild des Bots = VOLT-Logo, animiert. Wird nur gesetzt, wenn sich das Bild geändert hat
    (Discord begrenzt Profilbild-Änderungen). Klappt das GIF nicht, wird das Standbild genommen."""
    base = os.path.join(WEB_DIR, "assets", "img")
    try:
        with open(os.path.join(base, "volt-avatar.gif"), "rb") as f:
            gif = f.read()
        with open(os.path.join(base, "volt-logo.png"), "rb") as f:
            png = f.read()
    except OSError:
        return
    h = hashlib.sha256(gif + png).hexdigest()[:16]
    if await get_setting("avatar_hash") == h:
        return
    for kind, data in (("animiert", gif), ("Standbild", png)):
        try:
            await bot.user.edit(avatar=data)
            await set_setting("avatar_hash", h)
            print(f"Profilbild aktualisiert ({kind})")
            return
        except discord.HTTPException as ex:
            print(f"Profilbild ({kind}) nicht geändert:", ex)


async def _design_in_background(guild: discord.Guild):
    try:
        await run_design(guild)
    except Exception as ex:
        print("VOLT-Design fehlgeschlagen:", repr(ex))


@bot.event
async def on_ready():
    global _cleaned_guild_commands
    print(f"VOLT online als {bot.user} ({bot.user.id})")
    global _backup
    if VOLUME_PATH and _backup is None:  # tägliches Backup in den VOLT-Backup-Channel
        from volt_backup import Backup
        _backup = Backup(bot, project="VOLT ADMIN · Website & Tickets", slug="volt-admin", db_path=DB_PATH, data_dir=VOLUME_PATH,
                         restore_hint="Bot stoppen → Archiv entpacken → `volt.db` ins Volume legen → Bot starten")
    if _backup:
        _backup.start()
    try:
        await sync_avatar()
    except Exception as ex:
        print("Profilbild-Abgleich fehlgeschlagen:", repr(ex))
    # Bot-Status: Website als dauerhafte Werbung, bei Wartung/Störung mit Hinweis
    await apply_presence()
    # Nach einem Update mit neuen Panels: einmal automatisch neu posten (wie /panels)
    try:
        g = main_guild()
        refresh_icon_map(g)
        if g and await get_setting("design_version") != DESIGN_VERSION:
            # Neues Design: Icons hochladen, Kanäle/Rollen anpassen, Panels neu posten (im Hintergrund,
            # weil Discord Umbenennungen und Emoji-Uploads bremst)
            asyncio.create_task(_design_in_background(g))
        elif g and await get_setting("panels_version") != PANELS_VERSION:
            async def _icons_then_panels():
                await sync_app_emojis()          # erst die Icons, damit die neuen Panels sie schon zeigen
                await set_setting("panels_version", PANELS_VERSION)
                await post_panels(g)
                print(f"Panels automatisch neu gepostet (Version {PANELS_VERSION}).")
            asyncio.create_task(_icons_then_panels())
        else:
            asyncio.create_task(sync_app_emojis())
    except Exception as ex:
        print("Panels automatisch posten fehlgeschlagen:", repr(ex))
    if not GUILD_ID and not _cleaned_guild_commands:
        # Ohne GUILD_ID laufen die Befehle global: alte Server-Befehle vom alten Bot entfernen
        _cleaned_guild_commands = True
        for g in bot.guilds:
            try:
                bot.tree.clear_commands(guild=g)
                await bot.tree.sync(guild=g)
            except discord.HTTPException:
                pass
        print("Alte Server-Befehle entfernt.")


async def main():
    discord.utils.setup_logging()
    async with bot:
        # Website zuerst starten: Sie ist erreichbar, auch wenn der Discord-Login mal hakt
        await start_website()
        await bot.start(TOKEN)


if __name__ == "__main__":
    asyncio.run(main())