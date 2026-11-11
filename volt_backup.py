"""VOLT Backups: tägliche Sicherung der Datenbank in den VOLT-Backup-Channel auf Discord.

- Jeden Tag um 04:00 Uhr (Europe/Berlin) und einmal kurz nach dem Start, wenn das letzte Backup älter als 23 Stunden ist.
- Die SQLite-Datenbank wird konsistent kopiert (sqlite3-Backup, klappt auch während der Bot läuft) und als .tar.gz gepackt,
  auf Wunsch zusammen mit Ordnern (z. B. hochgeladene Bilder).
- Gepostet wird mit klarer Überschrift „🗄️ Backup · <Projekt>“ über den eigenen Bot in den Channel BACKUP_CHANNEL_ID
  (Standard: der VOLT-Backup-Channel). Ist BACKUP_WEBHOOK_URL gesetzt, geht es stattdessen über diesen Webhook.
- Über 9,5 MB wird die Datei in Teile zerlegt (Discord-Grenze 10 MB). Ordner, die zu groß sind, kommen sonntags separat.
- Ist der Bot nicht auf dem Backup-Server, steht im Log ein Einladungslink.
"""
import asyncio
import io
import logging
import os
import sqlite3
import tarfile
import tempfile
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable

import aiohttp
import discord

try:
    from zoneinfo import ZoneInfo
    TZ = ZoneInfo("Europe/Berlin")
except Exception:  # noqa: BLE001 – ohne Zeitzonendaten: Winterzeit reicht für „nachts“
    TZ = timezone(timedelta(hours=1))

log = logging.getLogger("volt.backup")
DEFAULT_CHANNEL = 1570225109732565064
LIMIT = 9_500_000
HOUR = 4
COLOR = 0xE5212F
BOT_PERMS = 52224  # Kanäle sehen, Nachrichten senden, Links einbetten, Dateien anhängen


def human(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return (f"{n:.1f} {unit}" if unit != "B" else f"{n} B").replace(".", ",")
        n /= 1024
    return str(n)


def _snapshot(db_path: Path, dest: Path) -> tuple[int, int]:
    """Konsistente Kopie der Datenbank + Anzahl Tabellen und Einträge."""
    src = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    dst = sqlite3.connect(dest)
    try:
        src.backup(dst)
    finally:
        src.close()
    try:
        tables = [r[0] for r in dst.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
        rows = 0
        for t in tables:
            try:
                rows += dst.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0]
            except sqlite3.Error:
                pass
        return len(tables), rows
    finally:
        dst.close()


def _folder_files(folders) -> list[tuple[Path, Path]]:
    out = []
    for folder in folders:
        folder = Path(folder)
        if folder.is_dir():
            for f in sorted(folder.rglob("*")):
                if f.is_file():
                    out.append((f, Path(folder.name) / f.relative_to(folder)))
    return out


def _pack(entries: list[tuple[Path, str]]) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz", compresslevel=9) as tar:
        for path, arcname in entries:
            tar.add(str(path), arcname=str(arcname))
    return buf.getvalue()


def build(db_path: Path, folders, stamp: str, slug: str, with_folders: bool) -> dict:
    """Erstellt das Archiv. with_folders=None → Ordner nur, wenn alles zusammen unter das Limit passt."""
    with tempfile.TemporaryDirectory() as tmp:
        snap = Path(tmp) / db_path.name
        tables, rows = _snapshot(db_path, snap)
        raw = snap.stat().st_size
        files = _folder_files(folders)
        folder_size = sum(f.stat().st_size for f, _ in files)
        base = [(snap, db_path.name)]
        data = _pack(base)
        included = False
        if files and with_folders is not False:
            combined = _pack(base + files)
            if with_folders or len(combined) <= LIMIT:
                data, included = combined, True
        return {"data": data, "name": f"{slug}_{stamp}.tar.gz", "raw": raw, "tables": tables, "rows": rows,
                "files": len(files), "folder_size": folder_size, "folders_included": included}


class Backup:
    def __init__(self, client: discord.Client, *, project: str | Callable[[], str], slug: str, db_path, data_dir,
                 folders=(), restore_hint: str = ""):
        self.client = client
        self.project = project
        self.slug = slug
        self.db_path = Path(db_path)
        self.data_dir = Path(data_dir)
        self.folders = [Path(f) for f in folders]
        self.restore_hint = restore_hint
        self.channel_id = int(os.getenv("BACKUP_CHANNEL_ID") or DEFAULT_CHANNEL)
        self.webhook_url = os.getenv("BACKUP_WEBHOOK_URL", "").strip()
        self._task: asyncio.Task | None = None
        self._lock = asyncio.Lock()

    # ------------------------------------------------------------------ Zeitplan
    @property
    def marker(self) -> Path:
        return self.data_dir / ".last_backup"

    def last(self) -> float:
        try:
            return float(self.marker.read_text().strip())
        except (OSError, ValueError):
            return 0.0

    def start(self) -> None:
        if os.getenv("BACKUP_DISABLED") or (self._task and not self._task.done()):
            return
        self._task = asyncio.create_task(self._loop())

    async def _loop(self) -> None:
        await self.client.wait_until_ready()
        await asyncio.sleep(90)
        if time.time() - self.last() > 23 * 3600:
            await self.run("nach dem Start")
        while not self.client.is_closed():
            now = datetime.now(TZ)
            nxt = now.replace(hour=HOUR, minute=0, second=0, microsecond=0)
            if nxt <= now:
                nxt += timedelta(days=1)
            await asyncio.sleep(max(60, (nxt - now).total_seconds()))
            await self.run("täglich")

    # ------------------------------------------------------------------ Sichern + senden
    def _name(self) -> str:
        try:
            return self.project() if callable(self.project) else self.project
        except Exception:  # noqa: BLE001
            return self.slug

    async def run(self, reason: str = "manuell") -> tuple[bool, str]:
        async with self._lock:
            try:
                if not self.db_path.exists():
                    return False, f"Datenbank {self.db_path} nicht gefunden"
                now = datetime.now(TZ)
                stamp = now.strftime("%Y-%m-%d_%H%M")
                sunday = now.weekday() == 6
                info = await asyncio.to_thread(build, self.db_path, self.folders, stamp, self.slug, None)
                extra = None
                if self.folders and info["files"] and not info["folders_included"] and (sunday or self.last() == 0):
                    extra = await asyncio.to_thread(_pack_folders, self.folders, f"{self.slug}_{stamp}_bilder.tar.gz")
                ok, msg = await self._send(info, extra, reason, now)
                if ok:
                    self.marker.write_text(str(time.time()))
                    print(f"[Backup] gesendet: {info['name']} ({human(len(info['data']))})", flush=True)
                else:
                    print(f"[Backup] NICHT gesendet: {msg}", flush=True)
                return ok, msg
            except Exception as e:  # noqa: BLE001
                log.exception("Backup fehlgeschlagen")
                print(f"[Backup] fehlgeschlagen: {e}", flush=True)
                return False, f"Backup fehlgeschlagen: {e}"

    def _embed(self, info: dict, reason: str, now: datetime, parts: int, extra: dict | None) -> discord.Embed:
        name = self._name()
        e = discord.Embed(title=f"🗄️ Backup · {name}", color=COLOR, timestamp=now,
                          description=f"Automatische Sicherung ({reason}). Datei herunterladen und gut aufheben.")
        e.add_field(name="Projekt", value=name, inline=True)
        bot = f"{self.client.user}" if self.client.user else "–"
        e.add_field(name="Bot", value=bot, inline=True)
        e.add_field(name="Zeit", value=f"<t:{int(now.timestamp())}:f>", inline=True)
        size = f"{human(len(info['data']))} (Datenbank entpackt {human(info['raw'])})"
        e.add_field(name="Datei", value=f"`{info['name']}`" + (f" · {parts} Teile" if parts > 1 else ""), inline=False)
        e.add_field(name="Größe", value=size, inline=True)
        e.add_field(name="Inhalt", value=f"{info['tables']} Tabellen · {info['rows']:,} Einträge".replace(",", "."), inline=True)
        if info["files"]:
            if info["folders_included"]:
                pics = f"{info['files']} Dateien enthalten ({human(info['folder_size'])})"
            elif extra:
                pics = f"{info['files']} Dateien als eigene Datei darunter ({human(info['folder_size'])})"
            else:
                pics = f"{info['files']} Dateien ({human(info['folder_size'])}) – zu groß, kommen sonntags separat"
            e.add_field(name="Bilder & Uploads", value=pics, inline=False)
        if self.restore_hint:
            e.add_field(name="Wiederherstellen", value=self.restore_hint[:1024], inline=False)
        e.set_footer(text="VOLT Backups · täglich 04:00 Uhr")
        return e

    @staticmethod
    def _split(name: str, data: bytes) -> list[discord.File]:
        if len(data) <= LIMIT:
            return [discord.File(io.BytesIO(data), filename=name)]
        chunks = [data[i:i + LIMIT] for i in range(0, len(data), LIMIT)]
        return [discord.File(io.BytesIO(c), filename=f"{name}.part{i + 1}of{len(chunks)}") for i, c in enumerate(chunks)]

    async def _send(self, info: dict, extra: dict | None, reason: str, now: datetime) -> tuple[bool, str]:
        files = self._split(info["name"], info["data"])
        embed = self._embed(info, reason, now, len(files), extra)
        later = files[1:] + (self._split(extra["name"], extra["data"]) if extra else [])
        name = self._name()
        if self.webhook_url:
            async with aiohttp.ClientSession() as session:
                hook = discord.Webhook.from_url(self.webhook_url, session=session)
                await hook.send(embed=embed, file=files[0], username="VOLT Backups", wait=True)
                for f in later:
                    await hook.send(content=f"📎 {name} · `{f.filename}`", file=f, username="VOLT Backups", wait=True)
            return True, "über Webhook gesendet"
        channel = self.client.get_channel(self.channel_id)
        if channel is None:
            try:
                channel = await self.client.fetch_channel(self.channel_id)
            except (discord.NotFound, discord.Forbidden):
                channel = None
        if channel is None:
            app_id = self.client.user.id if self.client.user else "?"
            return False, (f"Backup-Channel {self.channel_id} nicht erreichbar – den Bot auf den VOLT-Server einladen und ihm den "
                           f"Backup-Channel freigeben: https://discord.com/oauth2/authorize?client_id={app_id}&scope=bot"
                           f"&permissions={BOT_PERMS}")
        try:
            await channel.send(embed=embed, file=files[0])
            for f in later:
                await channel.send(content=f"📎 {name} · `{f.filename}`", file=f)
        except discord.Forbidden:
            return False, f"Keine Rechte im Backup-Channel {self.channel_id} (Nachrichten senden + Dateien anhängen nötig)"
        return True, "gesendet"


def _pack_folders(folders, name: str) -> dict:
    files = _folder_files(folders)
    return {"name": name, "data": _pack([(f, a) for f, a in files])}
