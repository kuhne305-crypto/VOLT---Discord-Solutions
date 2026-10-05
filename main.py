"""
VOLT - Discord Solutions | All-in-One Bot
Setup, Verify, Tickets (Status-Workflow + Preisangebot), Sicherheit, Warns,
Blacklist, Bewertungen, FAQ, Logs.
"""
import os
import io
import re
import time
import asyncio
import datetime as dt
from collections import defaultdict, deque

import aiosqlite
import discord
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

bot = commands.Bot(command_prefix="!", intents=intents)
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


def slugify(text: str) -> str:
    text = re.sub(r"[^a-z0-9äöüß]+", "-", text.lower().strip()).strip("-")
    return text[:40] or "projekt"


async def apply_status(guild: discord.Guild, channel: discord.TextChannel, ticket, status: str):
    emoji, cat_key, _ = STATUS[status]
    name = f"{emoji}│{ticket['slug']}"
    cat = find_category(guild, cat_key)
    kwargs = {}
    if channel.name != name:
        wait = rename_wait(channel.id)
        if wait:
            return False, wait
        kwargs["name"] = name
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
    return True, 0


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
    "Was kostet das?": "Der Basis-Service ist für Streamer vorerst **kostenlos**. Spenden sind freiwillig "
                       "willkommen. Für Extra-Wünsche nenne ich nach deiner Anfrage einen Preis, den du "
                       "bestätigen oder ablehnen kannst.",
    "Wie läuft eine Bestellung ab?": "1) Ticket in #bestellen öffnen\n2) Ich prüfe deine Anfrage und schicke ein Angebot\n"
                                     "3) Du bestätigst oder lehnst ab\n4) Dein Projekt wird umgesetzt, du siehst den Status am Channel-Symbol.",
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
PROJECT_TYPES = ["🤖 Discord-Bot", "🖥️ Discord-Server-Setup", "♻️ Server-Überarbeitung",
                 "📦 Bot + Server (Komplettpaket)", "💡 Sonstiges"]


class TicketModal(discord.ui.Modal, title="Neues Projekt"):
    pname = discord.ui.TextInput(label="Projektname (wird zum Channel-Namen)", max_length=40)
    desc = discord.ui.TextInput(label="Beschreibung / Wünsche", style=discord.TextStyle.paragraph,
                                max_length=1000)
    platform = discord.ui.TextInput(label="Plattform (Twitch / YouTube / TikTok / …)",
                                    required=False, max_length=50)
    link = discord.ui.TextInput(label="Kanal-Link", required=False, max_length=200)
    budget = discord.ui.TextInput(label="Budget (oder: kostenlos / Spende)",
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
class PriceModal(discord.ui.Modal, title="Preis festlegen"):
    price = discord.ui.TextInput(label="Preis (z. B. 25 € oder kostenlos)",
                                 default="kostenlos", max_length=60)

    def __init__(self, ticket_id: int):
        super().__init__()
        self.ticket_id = ticket_id

    async def on_submit(self, interaction: discord.Interaction):
        ticket = await get_ticket(interaction.channel.id)
        if not ticket or ticket["id"] != self.ticket_id:
            return await interaction.response.send_message("❌ Ticket nicht gefunden.", ephemeral=True)
        e = emb("💼 Angebot für dein Projekt",
                f"**Projekt:** {ticket['project_name']}\n**Preis:** {self.price.value}\n\n"
                f"Bestätige das Angebot, um zu starten, oder lehne es ab.\n"
                f"Spenden sind immer freiwillig. 💛")
        await interaction.response.defer(ephemeral=True)
        msg = await interaction.channel.send(
            content=f"<@{ticket['user_id']}>", embed=e, view=OfferView())
        await pool.execute("UPDATE tickets SET price=$1, status='offered', offer_message_id=$2 WHERE id=$3",
                           self.price.value, msg.id, ticket["id"])
        await interaction.followup.send("✅ Angebot gesendet.", ephemeral=True)


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
    ok, wait = await apply_status(interaction.guild, interaction.channel, ticket, status)
    if not ok:
        return await interaction.followup.send(
            f"⏳ Discord erlaubt nur 2 Umbenennungen pro 10 Minuten. Versuch es in ca. {wait}s erneut.",
            ephemeral=True)

    emoji, _, label = STATUS[status]
    member = interaction.guild.get_member(ticket["user_id"])
    await interaction.channel.send(
        content=member.mention if member else None,
        embed=emb(f"{emoji} Status: {label}", STATUS_TEXT.get(status, "")))
    await log(interaction.guild, "ticket-logs",
              emb(f"{emoji} Status geändert", f"#{ticket['id']} · {ticket['project_name']} → **{label}**"))

    if status == "archived":
        try:
            f = await make_transcript(interaction.channel, ticket)
            await log(interaction.guild, "ticket-logs",
                      emb("📦 Ticket archiviert", f"#{ticket['id']} · {ticket['project_name']}"), file=f)
        except discord.HTTPException:
            pass
        if prev in ACTIVE_STATES:
            await interaction.channel.send(
                content=member.mention if member else None,
                embed=emb("⭐ Wie zufrieden warst du?",
                          "Gib uns kurz eine Bewertung. Sie erscheint in #bewertungen.\n"
                          "Wenn dir die Arbeit gefallen hat, freuen wir uns über eine freiwillige Spende. 💛"),
                view=ReviewView())
            if DONATION_URL:
                await interaction.channel.send(view=donate_view())
    await interaction.followup.send("✅ Status aktualisiert.", ephemeral=True)


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
        ok, wait = await apply_status(interaction.guild, interaction.channel, ticket, "progress")
        if not ok:
            return await interaction.followup.send(
                f"⏳ Bitte in ca. {wait}s noch einmal bestätigen (Discord-Limit).", ephemeral=True)
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
        ok, wait = await apply_status(interaction.guild, interaction.channel, ticket, "rejected")
        if not ok:
            return await interaction.followup.send(
                f"⏳ Bitte in ca. {wait}s noch einmal versuchen (Discord-Limit).", ephemeral=True)
        await interaction.message.edit(view=None)
        await interaction.channel.send(embed=emb(
            "🔴 Angebot abgelehnt", "Das Ticket wurde geschlossen. Du kannst jederzeit ein neues öffnen.",
            0xE74C3C))
        await log(interaction.guild, "ticket-logs",
                  emb("🔴 Angebot abgelehnt", f"#{ticket['id']} · {ticket['project_name']}", 0xE74C3C))


# ===============================================================
# BEWERTUNGEN
# ===============================================================
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
        await log(interaction.guild, "bewertungen", e)
        await interaction.response.send_message("💛 Danke für deine Bewertung!", ephemeral=True)


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
    "💛 **Basis-Service für Streamer vorerst kostenlos.** Spenden sind freiwillig.\n"
    "Extra-Wünsche werden nach Aufwand berechnet. **Preis auf Anfrage** – öffne einfach ein Ticket in #bestellen."
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
        "• **Basis-Service:** kostenlos (für Streamer vorerst)\n"
        "• **Extra-Wünsche:** nach Aufwand, du bekommst vorher ein Angebot und entscheidest selbst\n"
        "• **Spenden:** immer freiwillig und willkommen 💛"), donate_view() if DONATION_URL else None)
    await send_panel(guild, "faq", emb("❓ Häufige Fragen", "Wähle unten eine Frage aus."), FaqView())
    await send_panel(guild, "bestellen", emb(
        "🛒 Bestellen",
        "Klicke auf **Ticket öffnen**, wähle dein Projekt und beschreibe deine Wünsche.\n"
        "Dein Ticket sieht nur du und der Owner."), TicketPanelView())
    await send_panel(guild, "bewertungen", emb(
        "⭐ Bewertungen", "Hier erscheinen die Bewertungen unserer Kunden nach Projektabschluss."))


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
    else:
        msg = f"❌ Fehler: {error}"
        print("Command-Fehler:", repr(error))
    if interaction.response.is_done():
        await interaction.followup.send(msg, ephemeral=True)
    else:
        await interaction.response.send_message(msg, ephemeral=True)


@bot.tree.command(name="warn", description="User verwarnen (3 Warns = Timeout, 5 = Bann)")
@app_commands.guild_only()
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
@team_check()
async def warns_cmd(interaction: discord.Interaction, user: discord.Member):
    rows = await pool.fetch("SELECT * FROM warns WHERE user_id=$1 ORDER BY id", user.id)
    if not rows:
        return await interaction.response.send_message("Keine Warns. ✅", ephemeral=True)
    text = "\n".join(f"#{i+1} · {str(r['created_at'])[:10]} · {r['reason']}" for i, r in enumerate(rows))
    await interaction.response.send_message(embed=emb(f"Warns von {user.display_name}", text), ephemeral=True)


@bot.tree.command(name="clearwarns", description="Alle Warns eines Users löschen")
@app_commands.guild_only()
@team_check()
async def clearwarns_cmd(interaction: discord.Interaction, user: discord.Member):
    await pool.execute("DELETE FROM warns WHERE user_id=$1", user.id)
    await interaction.response.send_message(f"✅ Warns von {user.mention} gelöscht.", ephemeral=True)
    await log(interaction.guild, "mod-logs", emb("🧹 Warns gelöscht", f"{user.mention} durch {interaction.user.mention}"))


@bot.tree.command(name="timeout", description="User in den Timeout schicken")
@app_commands.guild_only()
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
                               guild_only=True)


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


@bot.tree.command(name="spenden", description="Freiwillig unterstützen")
async def spenden_cmd(interaction: discord.Interaction):
    if not DONATION_URL:
        return await interaction.response.send_message("Aktuell ist kein Spendenlink hinterlegt.", ephemeral=True)
    await interaction.response.send_message(
        embed=emb("💛 Danke!", "Spenden sind komplett freiwillig und helfen, den Service kostenlos zu halten."),
        view=donate_view(), ephemeral=True)


@bot.tree.command(name="panels", description="Info-/Verify-/Ticket-Panels neu posten (nur Owner)")
@app_commands.guild_only()
@owner_check()
async def panels_cmd(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    await post_panels(interaction.guild)
    await interaction.followup.send("✅ Panels aktualisiert.", ephemeral=True)


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
    if has_team_role(member):
        return

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


@bot.event
async def on_message_delete(message: discord.Message):
    if message.guild and not message.author.bot and message.content:
        cat = message.channel.category
        if cat and any(k in cat.name for k in TICKET_CATEGORY_KEYS):
            return
        await log(message.guild, "mod-logs", emb(
            "🗑️ Nachricht gelöscht",
            f"{message.author.mention} in {message.channel.mention}\n{message.content[:900]}", 0x95A5A6))


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
# START
# ===============================================================
@bot.event
async def setup_hook():
    global pool
    pool = DB(DB_PATH)
    await pool.connect()
    print(f"Datenbank: {DB_PATH}")
    for v in (VerifyView(), TicketPanelView(), AdminPanelView(), OfferView(), ReviewView(), FaqView()):
        bot.add_view(v)
    if GUILD_ID:
        g = discord.Object(id=GUILD_ID)
        bot.tree.copy_global_to(guild=g)
        await bot.tree.sync(guild=g)
    else:
        await bot.tree.sync()
    update_stats.start()


@bot.event
async def on_ready():
    print(f"VOLT online als {bot.user} ({bot.user.id})")


if __name__ == "__main__":
    bot.run(TOKEN)
