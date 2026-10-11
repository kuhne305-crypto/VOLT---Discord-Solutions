"""
VOLT - Discord Solutions | All-in-One Bot
Setup, Verify, Tickets (Status-Workflow + Preisangebot), Sicherheit, Warns,
Blacklist, Bewertungen, FAQ, Logs + Website (läuft im selben Railway-Service).
"""
import os
import io
import re
import math
import time
import asyncio
import mimetypes
import datetime as dt
from collections import defaultdict, deque

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
DONATION_URL = os.environ.get("DONATION_URL", "")  # z.B. PayPal.me / Ko-fi Link

# Website (Railway setzt PORT automatisch)
SITE_ENABLED = os.environ.get("SITE_ENABLED", "1") != "0"
SITE_PORT = int(os.environ.get("PORT", "8080"))
MAX_PARALLEL = max(1, int(os.environ.get("MAX_PARALLEL", "2")))            # Projekte gleichzeitig
PROJECTS_PER_DAY = max(0.1, float(os.environ.get("PROJECTS_PER_DAY", "1")))  # normales Tempo
DISCORD_INVITE_URL = os.environ.get("DISCORD_INVITE_URL", "https://discord.gg/RpUtNGT6uj")
SITE_URL = os.environ.get("SITE_URL", "https://volt-discord-solutions.up.railway.app").rstrip("/")

MIN_ACCOUNT_AGE_DAYS = int(os.environ.get("MIN_ACCOUNT_AGE_DAYS", "3"))  # 0 = aus
RAID_JOINS = int(os.environ.get("RAID_JOINS", "6"))      # so viele Joins ...
RAID_WINDOW = int(os.environ.get("RAID_WINDOW", "15"))   # ... in so vielen Sekunden
RAID_LOCKDOWN = 120                                      # Sekunden Kick-Modus nach Raid
NUKE_LIMIT = 3                                           # Loeschungen/Bans ...
NUKE_WINDOW = 30                                         # ... in Sekunden
MAX_OPEN_TICKETS = 2
SUPPORT_SEES_TICKETS = False

BRAND = "VOLT • Discord Solutions"
BRAND_COLOR = 0xF1C40F

intents = discord.Intents.default()
intents.members = True
intents.message_content = True

# max_messages: mehr Nachrichten im Speicher = bei Bearbeiten/Löschen ist der alte Text im Mod-Log bekannt
bot = commands.Bot(command_prefix="!", intents=intents, max_messages=10000)
pool = None  # DB-Objekt, wird im setup_hook gesetzt


# ===============================================================
# ROLLEN
# ===============================================================
ROLES = [
    ("owner", "👑 Owner", 0xF1C40F, discord.Permissions(administrator=True), True),
    ("admin", "🛡️ Admin", 0xE74C3C, discord.Permissions(administrator=True), True),
    ("support", "🔧 Support", 0x3498DB, discord.Permissions(
        manage_messages=True, moderate_members=True, kick_members=True), True),
    ("kunde", "💼 Kunde", 0x2ECC71, discord.Permissions.none(), True),
    ("user", "✅ User", 0x95A5A6, discord.Permissions.none(), False),
    ("bots", "🤖 Bots", 0x9B59B6, discord.Permissions.none(), False),
    ("unverified", "⛔ Unverifiziert", 0x7F8C8D, discord.Permissions.none(), False),
]
ROLE_NAMES = {k: n for k, n, *_ in ROLES}
ROLE_CACHE: dict[int, dict[str, discord.Role]] = {}


def find_role(guild: discord.Guild, key: str):
    cached = ROLE_CACHE.get(guild.id, {}).get(key)
    if cached and guild.get_role(cached.id):
        return cached
    return discord.utils.get(guild.roles, name=ROLE_NAMES[key])


def has_team_role(member: discord.Member) -> bool:
    if member.id == OWNER_ID or member.id == member.guild.owner_id:
        return True
    names = {ROLE_NAMES["owner"], ROLE_NAMES["admin"], ROLE_NAMES["support"]}
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
STRUCTURE = [
    ("━━━━━ 📊 SERVERINFO ━━━━━", "info", [
        ("👥 Mitglieder: 0", "voice"),
        ("🟢 Status: Online", "voice"),
        ("⭐ Bewertungen: bald verfügbar", "voice"),
    ]),
    ("━━━━━ 👋 WILLKOMMEN ━━━━━", "public", [
        ("📜│regeln", "text"),
        ("👋│willkommen", "text"),
        ("✅│verify", "text"),
        ("🚫│nicht-schreiben", "text", "honeypot"),
    ]),
    ("━━━━━ 📌 INFOS ━━━━━", "verified", [
        ("📢│ankündigungen", "text"),
        ("🟢│server-status", "text"),
        ("⭐│bewertungen", "text"),
        ("💳│kosten-übersicht", "text"),
        ("❓│faq", "text"),
        ("🎨│portfolio", "text"),
    ]),
    ("━━━━━ 🛒 SHOP ━━━━━", "verified", [
        ("💰│preisliste", "text"),
        ("🛒│bestellen", "text"),
    ]),
    ("━━━━━ 🟡 OFFENE TICKETS ━━━━━", "ticket", []),
    ("━━━━━ 🔵 IN BEARBEITUNG ━━━━━", "ticket", []),
    ("━━━━━ 🟢 LAUFENDE PROJEKTE ━━━━━", "ticket", []),
    ("━━━━━ 🟠 WARTUNG ━━━━━", "ticket", []),
    ("━━━━━ 📦 ARCHIV ━━━━━", "ticket", []),
    ("━━━━━ 🛠️ TEAM-INTERN ━━━━━", "team", [
        ("💬│team-chat", "text"),
        ("📝│aufgaben", "text"),
    ]),
    ("━━━━━ 📜 LOGS ━━━━━", "admin", [
        ("🔐│admin-logs", "text"),
        ("🗂️│ticket-logs", "text"),
        ("🛡️│mod-logs", "text"),
        ("🚪│join-leave-logs", "text"),
    ]),
]
TICKET_CATEGORY_KEYS = ("OFFENE TICKETS", "IN BEARBEITUNG", "LAUFENDE PROJEKTE", "WARTUNG", "ARCHIV")


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
  user_id INTEGER PRIMARY KEY, reason TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP);
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
    "progress":    ("🔵", "IN BEARBEITUNG", "Angenommen / in Bearbeitung"),
    "running":     ("🟢", "LAUFENDE PROJEKTE", "Läuft"),
    "maintenance": ("🟠", "WARTUNG", "In Wartungsmodus"),
    "paused":      ("⏳", "IN BEARBEITUNG", "Pausiert / wartet auf dich"),
    "rejected":    ("🔴", "ARCHIV", "Abgelehnt"),
    "archived":    ("📦", "ARCHIV", "Archiviert"),
}
STATUS_TEXT = {
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
    name = f"{emoji}│{ticket['slug']}"
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
    "Was kostet das?": "**Nichts.** Alles bei VOLT ist kostenlos, ich arbeite nur auf Spendenbasis. "
                       "Wenn du zufrieden bist, freue ich mich über eine freiwillige Spende. 💛",
    "Wie läuft eine Bestellung ab?": "1) Ticket in #bestellen öffnen\n2) Ich prüfe deine Anfrage und schicke dir eine Bestätigung\n"
                                     "3) Du bestätigst oder lehnst ab\n4) Dein Projekt wird umgesetzt, du siehst den Status am Channel-Symbol.",
    "Bekomme ich Bescheid, wenn das Team antwortet?": "Ja. Sobald jemand aus dem Team in deinem Ticket schreibt, bekommst du "
                                                       "eine DM mit Link zum Ticket. Mit **/dm-benachrichtigungen** schaltest du das an oder aus.",
    "Was bedeuten die Status-Symbole?": "🟡 Offen · 🔵 In Bearbeitung · 🟢 Läuft · 🟠 Wartungsmodus · "
                                        "⏳ Pausiert · 📦 Archiv · 🔴 Abgelehnt",
    "Wer sieht mein Ticket?": "Nur du und der Owner/Admin. Kein anderer User, auch keine Kunden.",
    "Was darf ich NICHT ins Ticket schreiben?": "Schicke **nie** deinen Bot-Token, Passwörter oder Zahlungsdaten. "
                                                "Für Zugänge sprechen wir einen sicheren Weg ab.",
    "Für wen ist das Angebot?": "Für kleine und große Streamer, Communities, Gruppen und Projekte.",
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


# ===============================================================
# TICKET: OEFFNEN
# ===============================================================
PROJECT_TYPES = ["🤖 Discord-Bot", "📺 Streamer-Bot", "📊 Fraktions-Dashboard + Bot",
                 "🖥️ Discord-Server-Setup", "♻️ Server-Überarbeitung", "📦 Bot + Server (Komplettpaket)",
                 "🎥 OBS-Einrichtung", "💡 Sonstiges"]


class TicketModal(discord.ui.Modal, title="Neues Projekt"):
    pname = discord.ui.TextInput(label="Projektname (wird zum Channel-Namen)", max_length=40)
    desc = discord.ui.TextInput(label="Beschreibung / Wünsche", style=discord.TextStyle.paragraph,
                                max_length=1000)
    platform = discord.ui.TextInput(label="Plattform (Twitch / YouTube / TikTok / …)",
                                    required=False, max_length=50)
    link = discord.ui.TextInput(label="Kanal-Link", required=False, max_length=200)
    budget = discord.ui.TextInput(label="Spende (optional – alles ist kostenlos)",
                                  required=False, max_length=60)

    def __init__(self, ptype: str):
        super().__init__()
        self.ptype = ptype

    async def on_submit(self, interaction: discord.Interaction):
        guild, member = interaction.guild, interaction.user
        await interaction.response.defer(ephemeral=True)

        n = await pool.fetchval(
            "SELECT count(*) FROM tickets WHERE user_id=$1 AND status NOT IN ('archived','rejected','deleted')",
            member.id)
        if n >= MAX_OPEN_TICKETS:
            return await interaction.followup.send(
                f"❌ Du hast schon {n} offene Tickets (Maximum {MAX_OPEN_TICKETS}).", ephemeral=True)

        slug = slugify(self.pname.value)
        cat = find_category(guild, "OFFENE TICKETS")
        channel = await guild.create_text_channel(
            f"🟡│{slug}", category=cat, overwrites=ticket_overwrites(guild, member),
            topic=f"Ticket von {member} | {self.ptype}", reason="VOLT Ticket")
        tid = await pool.fetchval(
            """INSERT INTO tickets (channel_id,user_id,project_type,project_name,slug,description,
               platform,link,budget,status) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,'open') RETURNING id""",
            channel.id, member.id, self.ptype, self.pname.value, slug, self.desc.value,
            self.platform.value or None, self.link.value or None, self.budget.value or None)
        invalidate_site_cache()

        e = emb(f"🎫 Ticket #{tid} – {self.pname.value}", color=0xF1C40F)
        e.add_field(name="Projektart", value=self.ptype, inline=True)
        e.add_field(name="Plattform", value=self.platform.value or "–", inline=True)
        e.add_field(name="Link", value=self.link.value or "–", inline=False)
        e.add_field(name="Budget / Spende", value=self.budget.value or "–", inline=True)
        e.add_field(name="Von", value=member.mention, inline=True)
        e.add_field(name="Beschreibung", value=self.desc.value, inline=False)
        await channel.send(
            content=f"<@{OWNER_ID}> {member.mention}\nDein Ticket ist eingegangen. "
                    f"Du bekommst hier ein Angebot, sobald es geprüft wurde.",
            embed=e, view=AdminPanelView())
        await interaction.followup.send(f"✅ Dein Ticket wurde erstellt: {channel.mention}", ephemeral=True)
        await log(guild, "ticket-logs", emb("🟡 Ticket geöffnet",
                                            f"#{tid} · {self.pname.value} · {member.mention}\n{channel.mention}"))


class ProjectSelect(discord.ui.Select):
    def __init__(self):
        super().__init__(placeholder="Welches Projekt brauchst du?",
                         options=[discord.SelectOption(label=t, value=str(i))
                                  for i, t in enumerate(PROJECT_TYPES)])

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.send_modal(TicketModal(PROJECT_TYPES[int(self.values[0])]))


class ProjectSelectView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=180)
        self.add_item(ProjectSelect())


class TicketPanelView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Ticket öffnen", emoji="🎫",
                       style=discord.ButtonStyle.primary, custom_id="volt:ticket:open")
    async def open_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        if await pool.fetchval("SELECT 1 FROM blacklist WHERE user_id=$1", interaction.user.id):
            return await interaction.response.send_message(
                "🚫 Du kannst keine Tickets öffnen.", ephemeral=True)
        n = await pool.fetchval(
            "SELECT count(*) FROM tickets WHERE user_id=$1 AND status NOT IN ('archived','rejected','deleted')",
            interaction.user.id)
        if n >= MAX_OPEN_TICKETS:
            return await interaction.response.send_message(
                f"❌ Du hast schon {n} offene Tickets (Maximum {MAX_OPEN_TICKETS}).", ephemeral=True)
        await interaction.response.send_message(
            "Was für ein Projekt brauchst du?", view=ProjectSelectView(), ephemeral=True)


# ===============================================================
# TICKET: ADMIN-PANEL (nur OWNER_ID)
# ===============================================================
class PriceModal(discord.ui.Modal, title="Projekt annehmen"):
    price = discord.ui.TextInput(label="Kosten (Standard: kostenlos)",
                                 default="kostenlos", max_length=60)

    def __init__(self, ticket_id: int):
        super().__init__()
        self.ticket_id = ticket_id

    async def on_submit(self, interaction: discord.Interaction):
        ticket = await get_ticket(interaction.channel.id)
        if not ticket or ticket["id"] != self.ticket_id:
            return await interaction.response.send_message("❌ Ticket nicht gefunden.", ephemeral=True)
        e = emb("💼 Bestätigung für dein Projekt",
                f"**Projekt:** {ticket['project_name']}\n**Kosten:** {self.price.value}\n\n"
                f"Bestätige, um zu starten, oder lehne ab.\n"
                f"Alles ist kostenlos – Spenden sind freiwillig. 💛")
        await interaction.response.defer(ephemeral=True)
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


async def change_status(interaction: discord.Interaction, status: str):
    ticket = await get_ticket(interaction.channel.id)
    if not ticket:
        return await interaction.response.send_message("❌ Kein Ticket in der Datenbank.", ephemeral=True)
    prev = ticket["status"]
    if status in ("running", "maintenance", "paused") and prev in ("open", "offered", "rejected"):
        return await interaction.response.send_message(
            "❌ Erst muss der Kunde das Angebot bestätigen.", ephemeral=True)

    await interaction.response.defer(ephemeral=True)
    _, delayed = await apply_status(interaction.guild, interaction.channel, ticket, status)

    emoji, _, label = STATUS[status]
    member = interaction.guild.get_member(ticket["user_id"])
    worked = await work_seconds(ticket["id"])
    status_e = emb(f"{emoji} Status: {label}", STATUS_TEXT.get(status, ""))
    if status in ("running", "archived") and worked > 0:
        status_e.add_field(name="⏱️ Arbeitszeit", value=fmt_dur(worked))
    await interaction.channel.send(content=member.mention if member else None, embed=status_e)
    await log(interaction.guild, "ticket-logs",
              emb(f"{emoji} Status geändert", f"#{ticket['id']} · {ticket['project_name']} → **{label}**"
                  + (f"\nArbeitszeit bisher: {fmt_dur(worked)}" if worked > 0 else "")))
    review_open = status == "running" and not await has_review(ticket["id"])
    await notify_ticket_owner(interaction.guild, ticket, f"{emoji} Neuer Status: {label}",
                              STATUS_TEXT.get(status, "Der Status deines Projekts hat sich geändert.")
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
        if not ticket or ticket["status"] not in ("open", "offered"):
            return await interaction.response.send_message(
                "❌ Dieses Ticket ist schon angenommen oder geschlossen.", ephemeral=True)
        await interaction.response.send_modal(PriceModal(ticket["id"]))

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
        await change_status(interaction, "rejected")

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
PRICE_TEXT = (
    "**Professionelle Discord-Anpassung – übersichtlich, sicher und individuell.**\n\n"
    "📁 **Channel & Kategorien** – übersichtliche Struktur, Text- und Sprachkanäle, Info-, Regel-, Team- "
    "und Supportbereiche, private Bereiche\n"
    "🎭 **Rollen** – Team-, Rang-, Mitglieds- und Sonderrollen, Namen & Farben, Rollen für Bots\n"
    "🔐 **Permissions** – individuelle Berechtigungen, getrennte Bereiche, Schutz der Verwaltungsbereiche\n"
    "🤖 **Bots** – Ticket-, Verify-, Sicherheits- und Streamer-Systeme nach Wunsch\n"
    "♻️ **Überarbeitung** bestehender Server\n\n"
    "📺 **Streamer** – Streamer-Bot mit Live-Alerts, Self-Roles und Zeitplan, Hilfe beim Einrichten von OBS\n"
    "📊 **Dashboards** – Fraktions- und Familien-Dashboards mit eigenem Discord-Bot\n\n"
    "💛 **Alles ist kostenlos.** Ich arbeite nur auf Spendenbasis, Spenden sind freiwillig.\n"
    "Öffne einfach ein Ticket in #bestellen."
)


async def honeypot_embed() -> discord.Embed:
    n = await pool.fetchval("SELECT value FROM stats WHERE key='honeypot_bans'") or 0
    e = discord.Embed(
        title="🚨⚠️ WICHTIGER HINWEIS ⚠️🚨",
        description=(
            "**Dieser Kanal dient lediglich dazu, gehackte Spam-Accounts automatisch zu bannen!**\n\n"
            "Das bedeutet:\n"
            "**Wer hier reinschreibt, wird ohne Möglichkeit auf Entbannung permanent von diesem Discord gebannt!**\n\n"
            "🚫 **ALSO NICHT HIER REINSCHREIBEN!!!** 🚫\n\n"
            "Wer hier dennoch reinschreibt, ist selbst schuld."),
        color=0xE74C3C)
    e.add_field(name="📊 Statistik",
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


async def send_panel(guild: discord.Guild, key: str, embed: discord.Embed, view=None):
    ch = find_channel(guild, key)
    if not ch:
        return
    try:
        await ch.purge(limit=50, check=lambda m: m.author.id == guild.me.id)
    except discord.HTTPException:
        pass
    await ch.send(embed=embed, view=view)


async def post_panels(guild: discord.Guild):
    await send_panel(guild, "regeln", emb("📜 Serverregeln", RULES))
    await send_panel(guild, "verify", emb("✅ Verifizierung",
                                          "Lies die Regeln in #regeln und klicke unten, um sie zu akzeptieren."),
                     VerifyView())
    await send_panel(guild, "willkommen", emb(
        "👋 Willkommen bei VOLT – Discord Solutions",
        "Wir bauen **Discord-Bots und Discord-Server** für kleine und große Streamer, Communities und Projekte.\n\n"
        "1️⃣ Regeln akzeptieren\n2️⃣ Preisliste ansehen\n3️⃣ In #bestellen ein Ticket öffnen"))
    hp = find_channel(guild, "nicht-schreiben")
    if hp:
        try:  # Schreibrecht fuer alle setzen, damit die Falle funktioniert
            await hp.edit(overwrites=build_overwrites(guild, "honeypot"))
        except discord.HTTPException:
            pass
    await send_panel(guild, "nicht-schreiben", await honeypot_embed())
    await send_panel(guild, "server-status", emb("🟢 Status: Online", "Alle Systeme laufen."))
    await send_panel(guild, "preisliste", emb("💰 Preisliste & Leistungen", PRICE_TEXT))
    await send_panel(guild, "kosten", emb(
        "💳 Kosten-Übersicht",
        "• **Alles:** kostenlos – Bots, Server-Setups, Dashboards und OBS-Hilfe\n"
        "• **Spenden:** immer freiwillig und willkommen 💛\n"
        "• Vor dem Start bekommst du eine Bestätigung im Ticket und entscheidest selbst."),
        donate_view() if DONATION_URL else None)
    await send_panel(guild, "faq", emb("❓ Häufige Fragen", "Wähle unten eine Frage aus."), FaqView())
    await send_panel(guild, "bestellen", emb(
        "🛒 Bestellen",
        "Klicke auf **Ticket öffnen**, wähle dein Projekt und beschreibe deine Wünsche.\n"
        "Dein Ticket sieht nur du und der Owner."), TicketPanelView())
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


@blacklist.command(name="add", description="User von Tickets sperren")
@owner_check()
async def bl_add(interaction: discord.Interaction, user: discord.User, grund: str = "–"):
    await pool.execute("INSERT INTO blacklist (user_id,reason) VALUES ($1,$2) "
                       "ON CONFLICT (user_id) DO UPDATE SET reason=$2", user.id, grund)
    await interaction.response.send_message(f"🚫 {user} gesperrt.", ephemeral=True)
    await log(interaction.guild, "mod-logs", emb("🚫 Blacklist", f"{user} · {grund}"))


@blacklist.command(name="remove", description="Sperre aufheben")
@owner_check()
async def bl_remove(interaction: discord.Interaction, user: discord.User):
    await pool.execute("DELETE FROM blacklist WHERE user_id=$1", user.id)
    await interaction.response.send_message(f"✅ {user} entsperrt.", ephemeral=True)


@blacklist.command(name="list", description="Gesperrte User anzeigen")
@owner_check()
async def bl_list(interaction: discord.Interaction):
    rows = await pool.fetch("SELECT * FROM blacklist")
    text = "\n".join(f"<@{r['user_id']}> · {r['reason']}" for r in rows) or "Leer."
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
    if ticket["status"] in ("open", "offered"):
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
    if not DONATION_URL:
        return await interaction.response.send_message("Aktuell ist kein Spendenlink hinterlegt.", ephemeral=True)
    await interaction.response.send_message(
        embed=emb("💛 Danke!", "Spenden sind komplett freiwillig und helfen, den Service kostenlos zu halten."),
        view=donate_view(), ephemeral=True)


@bot.tree.command(name="panels", description="Info-/Verify-/Ticket-Panels neu posten (nur Owner)")
@app_commands.guild_only()
@app_commands.default_permissions(administrator=True)
@owner_check()
async def panels_cmd(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    await post_panels(interaction.guild)
    await interaction.followup.send("✅ Panels aktualisiert.", ephemeral=True)


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
    bl = await pool.fetchval("SELECT count(*) FROM blacklist") or 0
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
        "`/hilfe` – diese Übersicht"))
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
            "`/blacklist add|remove|list` – Ticket-Sperre\n`/panels` – Panels neu posten\n"
            "`/setup` – Server komplett neu aufbauen (löscht alles!)"))
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
    protected = {ROLE_NAMES["owner"], ROLE_NAMES["admin"]}
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
WEB_PAGES = {"index", "streamer", "fraktion", "impressum", "datenschutz"}
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
        "donate": DONATION_URL if DONATION_URL.startswith("https://") else None,
        "discord": {"members": _site["members"], "online": _site["online"]},
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


async def site_page(request: web.Request) -> web.StreamResponse:
    name = request.match_info.get("name", "index")
    if name.endswith(".html"):
        name = name[:-5]
    path = os.path.join(WEB_DIR, f"{name}.html")
    if name not in WEB_PAGES or not os.path.isfile(path):
        raise web.HTTPNotFound()
    return web.FileResponse(path, headers={"Cache-Control": "no-cache"})


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
    urls = "".join(f"<url><loc>{SITE_URL}/{p}</loc></url>"
                   for p in ("", "streamer.html", "fraktion.html", "datenschutz.html", "impressum.html"))
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
    app.router.add_get("/health", site_health)
    app.router.add_get("/robots.txt", site_robots)
    app.router.add_get("/sitemap.xml", site_sitemap)
    app.router.add_static("/assets/", os.path.join(WEB_DIR, "assets"), show_index=False, follow_symlinks=False)
    app.router.add_get("/", site_page)
    app.router.add_get("/{name}", site_page)
    _site_runner = web.AppRunner(app, access_log=None)
    await _site_runner.setup()
    await web.TCPSite(_site_runner, "0.0.0.0", SITE_PORT).start()
    src = "aus Railway-Variable PORT" if os.environ.get("PORT") else "Standard, PORT nicht gesetzt"
    print(f"Website läuft auf Port {SITE_PORT} ({src}) → {SITE_URL}")


async def migrate_db():
    cols = {r[1] for r in await pool.fetch("PRAGMA table_info(tickets)")}
    for col in ("accepted_at", "live_at"):
        if col not in cols:
            await pool.execute(f"ALTER TABLE tickets ADD COLUMN {col} TEXT")
    if "slot" not in cols:
        await pool.execute("ALTER TABLE tickets ADD COLUMN slot INTEGER")
    rcols = {r[1] for r in await pool.fetch("PRAGMA table_info(reviews)")}
    if "message_id" not in rcols:
        await pool.execute("ALTER TABLE reviews ADD COLUMN message_id INTEGER")


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
    for v in (VerifyView(), TicketPanelView(), AdminPanelView(), OfferView(), ReviewView(), FaqView()):
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


_cleaned_guild_commands = False


@bot.event
async def on_ready():
    global _cleaned_guild_commands
    print(f"VOLT online als {bot.user} ({bot.user.id})")
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