"""
VOLT-Credit – in JEDEN VOLT-Bot einbauen
========================================
Datei neben die bot.py legen und an drei Stellen einbinden:

    from volt_credit import volt_footer, volt_presence, add_volt_command

    # 1) Unter jedes Embed die VOLT-Fußzeile setzen:
    embed = volt_footer(embed)                      # oder volt_footer(embed, "Familie Volt")

    # 2) Im on_ready den Bot-Status setzen:
    @bot.event
    async def on_ready():
        await volt_presence(bot)

    # 3) Vor dem Sync den /volt-Befehl hinzufügen (z. B. im setup_hook):
    add_volt_command(bot.tree)
    await bot.tree.sync()

Den Text für „Über mich“ im Discord Developer Portal findest du unten in VOLT_ABOUT.
"""
import discord
from discord import app_commands

VOLT_URL = "https://voltstudio.work"
VOLT_LABEL = "VoltStudio.work"
VOLT_INVITE = "https://discord.gg/RpUtNGT6uj"
VOLT_FOOTER = f"⚡ made by VOLT · {VOLT_LABEL}"
VOLT_COLOR = 0xFF1F2A

# Für das Feld „Über mich“ (Description) im Developer Portal, max. 400 Zeichen
VOLT_ABOUT = (
    "⚡ Gebaut von VOLT – kostenlose Familien-Dashboards, Fussball-Manager und Routen-Systeme mit eigenem Discord-Bot.\n"
    f"🌐 {VOLT_LABEL}\n"
    f"💬 {VOLT_INVITE.replace('https://', '')}"
)


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
                         "Discord-Bot. Gebaut und betreut von einer Person, nur auf Spendenbasis.\n\n"
                         f"🌐 **{VOLT_LABEL}**"),
            color=VOLT_COLOR)
        volt_footer(e)
        await interaction.response.send_message(embed=e, view=volt_view(), ephemeral=True)
    return volt_cmd
