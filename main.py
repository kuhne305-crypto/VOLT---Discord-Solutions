import os
import discord
from discord.ext import commands

TOKEN = os.environ["DISCORD_TOKEN"]
OWNER_ID = int(os.environ["OWNER_ID"])
GUILD_ID = int(os.environ["GUILD_ID"]) if os.environ.get("GUILD_ID") else None

# Soll Support (Team) Tickets sehen? Du wolltest: nur Ersteller + Admin/Owner
SUPPORT_SEES_TICKETS = False

intents = discord.Intents.default()
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)


# ---------------------------------------------------------------
# ROLLEN (von oben nach unten = hoch nach niedrig)
# ---------------------------------------------------------------
ROLES = [
    # name, farbe, permissions, hoist
    ("👑 Owner", 0xF1C40F, discord.Permissions(administrator=True), True),
    ("🛡️ Admin", 0xE74C3C, discord.Permissions(administrator=True), True),
    ("🔧 Support", 0x3498DB, discord.Permissions(
        manage_messages=True, moderate_members=True, kick_members=True), True),
    ("💼 Kunde", 0x2ECC71, discord.Permissions.none(), True),
    ("✅ User", 0x95A5A6, discord.Permissions.none(), False),
    ("🤖 Bots", 0x9B59B6, discord.Permissions.none(), False),
    ("⛔ Unverifiziert", 0x7F8C8D, discord.Permissions.none(), False),
]


def find_role(guild: discord.Guild, key: str):
    """Rolle anhand eines Teilnamens finden, z.B. 'Owner'."""
    for r in guild.roles:
        if key.lower() in r.name.lower():
            return r
    return None


# ---------------------------------------------------------------
# RECHTE-BAUKASTEN
# ---------------------------------------------------------------
def build_overwrites(guild: discord.Guild, mode: str):
    everyone = guild.default_role
    owner = find_role(guild, "Owner")
    admin = find_role(guild, "Admin")
    support = find_role(guild, "Support")
    user = find_role(guild, "User")
    bot_member = guild.me

    see = discord.PermissionOverwrite(view_channel=True, read_message_history=True)
    see_write = discord.PermissionOverwrite(
        view_channel=True, read_message_history=True, send_messages=True)
    hidden = discord.PermissionOverwrite(view_channel=False)
    bot_full = discord.PermissionOverwrite(
        view_channel=True, send_messages=True, manage_channels=True,
        manage_messages=True, read_message_history=True,
        embed_links=True, attach_files=True)

    ow = {bot_member: bot_full}

    if mode == "public":  # Willkommen-Bereich: jeder sieht, keiner schreibt
        ow[everyone] = discord.PermissionOverwrite(
            view_channel=True, read_message_history=True, send_messages=False)

    elif mode == "verified":  # nur verifizierte User, nur lesen
        ow[everyone] = hidden
        if user:
            ow[user] = discord.PermissionOverwrite(
                view_channel=True, read_message_history=True, send_messages=False)

    elif mode == "team":  # Team-intern
        ow[everyone] = hidden
        for r in (owner, admin, support):
            if r:
                ow[r] = see_write

    elif mode == "ticket":  # Tickets: NUR Owner/Admin (+ optional Support)
        ow[everyone] = hidden
        for r in (owner, admin):
            if r:
                ow[r] = see_write
        if SUPPORT_SEES_TICKETS and support:
            ow[support] = see_write
        # Rollen "User" und "Kunde" bekommen hier bewusst NICHTS.
        # Zugriff fuer den Ersteller kommt pro Channel (ticket_overwrites).

    elif mode == "admin":  # Logs
        ow[everyone] = hidden
        for r in (owner, admin):
            if r:
                ow[r] = see

    return ow


def ticket_overwrites(guild: discord.Guild, creator: discord.Member):
    """Rechte fuer EINEN Ticket-Channel: Ersteller + Owner/Admin + Bot. Sonst niemand."""
    ow = build_overwrites(guild, "ticket")
    ow[creator] = discord.PermissionOverwrite(
        view_channel=True,
        read_message_history=True,
        send_messages=True,
        attach_files=True,
        embed_links=True,
        manage_channels=False,
        manage_messages=False,
    )
    return ow


# ---------------------------------------------------------------
# SERVER-STRUKTUR
# (kategorie, modus, [ (channel, art) ])
# ---------------------------------------------------------------
STRUCTURE = [
    ("━━━━━ 👋 WILLKOMMEN ━━━━━", "public", [
        ("📜│regeln", "text"),
        ("👋│willkommen", "text"),
        ("✅│verify", "text"),
        ("🚫│nicht-schreiben", "text"),
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


# ---------------------------------------------------------------
# BOT
# ---------------------------------------------------------------
@bot.event
async def setup_hook():
    if GUILD_ID:
        guild = discord.Object(id=GUILD_ID)
        bot.tree.copy_global_to(guild=guild)
        await bot.tree.sync(guild=guild)  # sofort verfuegbar
    else:
        await bot.tree.sync()


@bot.event
async def on_ready():
    print(f"VOLT online als {bot.user} ({bot.user.id})")


def owner_only(interaction: discord.Interaction) -> bool:
    return interaction.user.id == OWNER_ID


@bot.tree.command(name="setup", description="Baut Rollen, Kategorien, Channels und Rechte auf (nur Owner)")
async def setup_cmd(interaction: discord.Interaction):
    if not owner_only(interaction):
        await interaction.response.send_message("❌ Keine Berechtigung.", ephemeral=True)
        return

    await interaction.response.defer(ephemeral=True, thinking=True)
    guild = interaction.guild
    created = {"rollen": 0, "kategorien": 0, "channels": 0}

    # 1) Rollen anlegen (nur fehlende)
    for name, color, perms, hoist in ROLES:
        if discord.utils.get(guild.roles, name=name):
            continue
        await guild.create_role(
            name=name, colour=discord.Colour(color),
            permissions=perms, hoist=hoist, reason="VOLT Setup")
        created["rollen"] += 1

    # 2) Kategorien + Channels (nur fehlende)
    for cat_name, mode, channels in STRUCTURE:
        overwrites = build_overwrites(guild, mode)
        category = discord.utils.get(guild.categories, name=cat_name)
        if category is None:
            category = await guild.create_category(
                cat_name, overwrites=overwrites, reason="VOLT Setup")
            created["kategorien"] += 1

        for ch_name, kind in channels:
            if discord.utils.get(category.channels, name=ch_name):
                continue
            if kind == "voice":
                await guild.create_voice_channel(ch_name, category=category)
            else:
                await guild.create_text_channel(ch_name, category=category)
            created["channels"] += 1

    await interaction.followup.send(
        f"✅ Setup fertig.\n"
        f"Rollen: {created['rollen']} · Kategorien: {created['kategorien']} · Channels: {created['channels']}\n\n"
        f"⚠️ Ziehe jetzt die Bot-Rolle in den Servereinstellungen ganz nach oben "
        f"(über Kunde/User), sonst kann der Bot keine Rollen vergeben.",
        ephemeral=True)


bot.run(TOKEN)
