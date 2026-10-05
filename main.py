import os
import discord
from discord.ext import commands, tasks

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
    # key, name, farbe, permissions, hoist
    ("owner", "👑 Owner", 0xF1C40F, discord.Permissions(administrator=True), True),
    ("admin", "🛡️ Admin", 0xE74C3C, discord.Permissions(administrator=True), True),
    ("support", "🔧 Support", 0x3498DB, discord.Permissions(
        manage_messages=True, moderate_members=True, kick_members=True), True),
    ("kunde", "💼 Kunde", 0x2ECC71, discord.Permissions.none(), True),
    ("user", "✅ User", 0x95A5A6, discord.Permissions.none(), False),
    ("bots", "🤖 Bots", 0x9B59B6, discord.Permissions.none(), False),
    ("unverified", "⛔ Unverifiziert", 0x7F8C8D, discord.Permissions.none(), False),
]

ROLE_CACHE: dict[int, dict[str, discord.Role]] = {}


def find_role(guild: discord.Guild, key: str):
    cached = ROLE_CACHE.get(guild.id, {}).get(key)
    if cached:
        return cached
    names = {k: n for k, n, *_ in ROLES}
    return discord.utils.get(guild.roles, name=names.get(key))


# ---------------------------------------------------------------
# RECHTE-BAUKASTEN
# ---------------------------------------------------------------
def build_overwrites(guild: discord.Guild, mode: str):
    everyone = guild.default_role
    owner = find_role(guild, "owner")
    admin = find_role(guild, "admin")
    support = find_role(guild, "support")
    user = find_role(guild, "user")
    bot_member = guild.me

    see = discord.PermissionOverwrite(view_channel=True, read_message_history=True)
    see_write = discord.PermissionOverwrite(
        view_channel=True, read_message_history=True, send_messages=True)
    hidden = discord.PermissionOverwrite(view_channel=False)
    bot_full = discord.PermissionOverwrite(
        view_channel=True, send_messages=True, manage_channels=True,
        manage_messages=True, read_message_history=True,
        embed_links=True, attach_files=True, connect=True)

    ow = {bot_member: bot_full}

    if mode == "info":  # Serverinfo: jeder sieht, keiner kann joinen
        ow[everyone] = discord.PermissionOverwrite(view_channel=True, connect=False)

    elif mode == "public":  # Willkommen-Bereich: jeder sieht, keiner schreibt
        ow[everyone] = discord.PermissionOverwrite(
            view_channel=True, read_message_history=True, send_messages=False)

    elif mode == "verified":  # nur verifizierte User, nur lesen
        ow[everyone] = hidden
        if user:
            ow[user] = discord.PermissionOverwrite(
                view_channel=True, read_message_history=True, send_messages=False)

    elif mode == "team":
        ow[everyone] = hidden
        for r in (owner, admin, support):
            if r:
                ow[r] = see_write

    elif mode == "ticket":  # NUR Owner/Admin (+ optional Support)
        ow[everyone] = hidden
        for r in (owner, admin):
            if r:
                ow[r] = see_write
        if SUPPORT_SEES_TICKETS and support:
            ow[support] = see_write

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
    ("━━━━━ 📊 SERVERINFO ━━━━━", "info", [
        ("👥 Mitglieder: 0", "voice"),
        ("🟢 Status: Online", "voice"),
        ("⭐ Bewertungen: bald verfügbar", "voice"),
    ]),
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
# LIVE-MITGLIEDERZAHL (max. 1 Umbenennung pro 10 Minuten)
# ---------------------------------------------------------------
@tasks.loop(minutes=10)
async def update_member_count():
    for guild in bot.guilds:
        for ch in guild.voice_channels:
            if ch.name.startswith("👥 Mitglieder:"):
                new_name = f"👥 Mitglieder: {guild.member_count}"
                if ch.name != new_name:
                    try:
                        await ch.edit(name=new_name, reason="VOLT Statistik")
                    except discord.HTTPException:
                        pass


@update_member_count.before_loop
async def _before():
    await bot.wait_until_ready()


# ---------------------------------------------------------------
# BOT
# ---------------------------------------------------------------
@bot.event
async def setup_hook():
    if GUILD_ID:
        guild = discord.Object(id=GUILD_ID)
        bot.tree.copy_global_to(guild=guild)
        await bot.tree.sync(guild=guild)
    else:
        await bot.tree.sync()
    update_member_count.start()


@bot.event
async def on_ready():
    print(f"VOLT online als {bot.user} ({bot.user.id})")


def owner_only(interaction: discord.Interaction) -> bool:
    return interaction.user.id == OWNER_ID


async def run_full_setup(interaction: discord.Interaction):
    guild = interaction.guild
    current_channel_id = interaction.channel_id
    stats = {"del_ch": 0, "del_roles": 0, "skipped": [], "rollen": 0,
             "kategorien": 0, "channels": 0}

    # 1) ALLE Channels loeschen (der aktuelle Channel kommt ganz zum Schluss)
    for ch in list(guild.channels):
        if ch.id == current_channel_id:
            continue
        try:
            await ch.delete(reason="VOLT Setup: Neuaufbau")
            stats["del_ch"] += 1
        except discord.HTTPException:
            stats["skipped"].append(f"Channel {ch.name}")

    # 2) ALLE Rollen loeschen (nicht @everyone, keine Bot-/Integrationsrollen,
    #    keine Rollen ueber der Bot-Rolle)
    for role in sorted(guild.roles, key=lambda r: r.position):
        if role.is_default() or role.managed or role >= guild.me.top_role:
            continue
        try:
            await role.delete(reason="VOLT Setup: Neuaufbau")
            stats["del_roles"] += 1
        except discord.HTTPException:
            stats["skipped"].append(f"Rolle {role.name}")

    # 3) Rollen neu erstellen
    ROLE_CACHE[guild.id] = {}
    for key, name, color, perms, hoist in ROLES:
        role = await guild.create_role(
            name=name, colour=discord.Colour(color),
            permissions=perms, hoist=hoist, reason="VOLT Setup")
        ROLE_CACHE[guild.id][key] = role
        stats["rollen"] += 1

    # 4) Dem Owner die Owner-Rolle geben
    owner_member = guild.get_member(OWNER_ID)
    if owner_member is None:
        try:
            owner_member = await guild.fetch_member(OWNER_ID)
        except discord.HTTPException:
            owner_member = None
    if owner_member:
        await owner_member.add_roles(ROLE_CACHE[guild.id]["owner"], reason="VOLT Setup")

    # 5) Kategorien + Channels neu erstellen
    for cat_name, mode, channels in STRUCTURE:
        category = await guild.create_category(
            cat_name, overwrites=build_overwrites(guild, mode), reason="VOLT Setup")
        stats["kategorien"] += 1
        for ch_name, kind in channels:
            if kind == "voice":
                name = ch_name
                if ch_name.startswith("👥 Mitglieder:"):
                    name = f"👥 Mitglieder: {guild.member_count}"
                await guild.create_voice_channel(name, category=category)
            else:
                await guild.create_text_channel(ch_name, category=category)
            stats["channels"] += 1

    # 6) Den Channel, in dem /setup lief, zum Schluss loeschen
    old = guild.get_channel(current_channel_id)
    if old:
        try:
            await old.delete(reason="VOLT Setup: Neuaufbau")
            stats["del_ch"] += 1
        except discord.HTTPException:
            stats["skipped"].append(f"Channel {old.name}")

    msg = (
        "✅ Neuaufbau fertig.\n"
        f"Gelöscht: {stats['del_ch']} Channels, {stats['del_roles']} Rollen\n"
        f"Erstellt: {stats['rollen']} Rollen, {stats['kategorien']} Kategorien, {stats['channels']} Channels\n\n"
        "⚠️ Ziehe jetzt die Bot-Rolle in den Servereinstellungen ganz nach oben."
    )
    if stats["skipped"]:
        msg += "\n\nNicht löschbar (z. B. Community-Pflichtchannels): " + ", ".join(stats["skipped"][:10])
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
        await interaction.response.edit_message(
            content="⏳ Setup läuft, das kann einige Minuten dauern ...", view=None)
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
async def setup_cmd(interaction: discord.Interaction):
    if not owner_only(interaction):
        await interaction.response.send_message("❌ Keine Berechtigung.", ephemeral=True)
        return
    await interaction.response.send_message(
        "⚠️ **Achtung:** Das löscht **alle** Channels und **alle** Rollen auf diesem Server "
        "und baut alles neu auf. Das kann nicht rückgängig gemacht werden.\n\nFortfahren?",
        view=ConfirmWipe(), ephemeral=True)


bot.run(TOKEN)
