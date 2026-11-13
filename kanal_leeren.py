"""/kanal-leeren – alle Nachrichten eines Kanals löschen (nur Owner, mit Rückfrage).

Eigenes Modul, getrennt vom Hauptcode (main.py). main.py lädt es geschützt:
ein Fehler hier schaltet nur diesen Befehl ab, VOLT ADMIN läuft normal weiter.
Es braucht vom Hauptcode nur: den Bot, die Owner-ID und die Helfer log, emb und ic.
"""
import datetime as dt

import discord
from discord import app_commands


def setup(bot, *, owner_id: int, log, emb, ic):
    clearing: set[int] = set()   # Kanäle, die gerade geleert werden (nicht doppelt starten)

    class ClearChannelView(discord.ui.View):
        """Rückfrage vor dem Leeren – nur der Owner darf bestätigen, nach 2 Minuten verfällt sie."""

        def __init__(self, channel, total: int):
            super().__init__(timeout=120)
            self.channel, self.total = channel, total

        async def interaction_check(self, interaction: discord.Interaction) -> bool:
            return interaction.user.id == owner_id

        @discord.ui.button(label="Endgültig löschen", emoji="🗑️", style=discord.ButtonStyle.danger)
        async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
            self.stop()
            ch = self.channel
            if ch.id in clearing:
                return await interaction.response.edit_message(content="⏳ Dieser Kanal wird schon geleert.", embed=None, view=None)
            clearing.add(ch.id)
            await interaction.response.edit_message(
                content=f"⏳ Lösche Nachrichten in {ch.mention} … (ältere als 14 Tage gehen nur einzeln, das dauert etwas)",
                embed=None, view=None)
            deleted = 0
            try:
                while True:
                    gone = await ch.purge(limit=200, bulk=True, reason=f"Kanal geleert von {interaction.user}")
                    if not gone:
                        break
                    deleted += len(gone)
                    try:
                        await interaction.edit_original_response(content=f"⏳ {deleted} Nachrichten in {ch.mention} gelöscht …")
                    except discord.HTTPException:
                        pass   # Rückmeldung nach 15 Minuten nicht mehr änderbar – Löschen läuft weiter
            except discord.HTTPException as ex:
                await log(ch.guild, "admin-logs", emb("🗑️ Kanal leeren abgebrochen",
                                                      f"{ch.mention}: {deleted} gelöscht, dann Fehler: {ex}", 0xFF4D5E))
                try:
                    await interaction.edit_original_response(content=f"❌ Abgebrochen nach {deleted} Nachrichten: {ex}")
                except discord.HTTPException:
                    pass
                return
            finally:
                clearing.discard(ch.id)
            await log(ch.guild, "admin-logs", emb(f"{ic('loeschen', '🗑️')} Kanal geleert",
                                                  f"{ch.mention}: **{deleted}** Nachrichten gelöscht von {interaction.user.mention}."))
            try:
                await interaction.edit_original_response(
                    content=f"✅ {ch.mention} ist leer – **{deleted}** Nachrichten gelöscht.\n"
                            "War hier ein VOLT-Panel drin? Mit `/panels` wird es neu gepostet.")
            except discord.HTTPException:
                pass

        @discord.ui.button(label="Abbrechen", style=discord.ButtonStyle.secondary)
        async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
            self.stop()
            await interaction.response.edit_message(content="Abgebrochen – nichts gelöscht.", embed=None, view=None)

    async def only_owner(interaction: discord.Interaction) -> bool:
        return interaction.user.id == owner_id

    @bot.tree.command(name="kanal-leeren", description="Alle Nachrichten in einem Kanal löschen (mit Rückfrage)")
    @app_commands.describe(kanal="Welcher Kanal? Leer lassen = dieser Kanal")
    @app_commands.guild_only()
    @app_commands.default_permissions(administrator=True)
    @app_commands.check(only_owner)
    async def clear_channel_cmd(interaction: discord.Interaction, kanal: discord.TextChannel | None = None):
        ch = kanal or interaction.channel
        if not isinstance(ch, (discord.TextChannel, discord.Thread, discord.VoiceChannel)):
            return await interaction.response.send_message("❌ In diesem Kanal geht das nicht.", ephemeral=True)
        perms = ch.permissions_for(interaction.guild.me)
        if not (perms.manage_messages and perms.read_message_history):
            return await interaction.response.send_message(
                f"❌ Mir fehlen in {ch.mention} die Rechte „Nachrichten verwalten“ und „Nachrichtenverlauf lesen“.", ephemeral=True)
        await interaction.response.defer(ephemeral=True, thinking=True)
        total = old = 0
        limit_old = discord.utils.utcnow() - dt.timedelta(days=14)
        async for m in ch.history(limit=20000):
            total += 1
            if m.created_at < limit_old:
                old += 1
        if total == 0:
            return await interaction.followup.send(f"{ch.mention} ist schon leer.", ephemeral=True)
        more = "+" if total >= 20000 else ""
        e = emb(f"{ic('warnung', '⚠️')} Kanal wirklich leeren?",
                f"In {ch.mention} werden **alle {total}{more} Nachrichten** gelöscht – auch angepinnte und die von Bots.\n"
                f"**Das kann nicht rückgängig gemacht werden.**"
                + (f"\n\n{old} davon sind älter als 14 Tage. Die löscht Discord nur einzeln – das dauert ein paar Minuten."
                   if old else ""), 0xFF4D5E)
        await interaction.followup.send(embed=e, view=ClearChannelView(ch, total), ephemeral=True)

    return clear_channel_cmd
