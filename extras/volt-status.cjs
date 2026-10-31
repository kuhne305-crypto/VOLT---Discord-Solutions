/*
 * VOLT – Datei für Bots mit discord.js
 * ====================================
 * Datei neben die Haupt-Datei des Bots legen und nach `const client = new Client(...)`:
 *
 *      CommonJS:  require('./volt-status.cjs').voltStart(client);
 *      ESM:       import { voltStart } from './volt-status.cjs';   voltStart(client);
 *
 * Was dann passiert:
 *  1) VOLT-Werbung im Bot-Status: Der Bot zeigt abwechselnd seinen eigenen Status
 *     (z. B. Twitch) und "⚡ VoltStudio.work". Ohne eigenen Status steht dauerhaft die Werbung da.
 *     Ausschalten: voltStart(client, { werbung: false })
 *  2) Optional (nur mit Railway-Variable VOLT_STATUS_KEY): private Statusmeldung an VOLT ADMIN.
 *     Gesendet werden nur Bot-ID, Bot-Name, Anzahl Server, Ping und Laufzeit.
 */
'use strict';

const VOLT_LABEL = 'VoltStudio.work';
const VOLT_AD_TEXT = `⚡ ${VOLT_LABEL}`;
const VOLT_STATUS_URL = process.env.VOLT_STATUS_URL || 'https://voltstudio.work/api/heartbeat';
const VERSION = '1.2-js';
const AD_MS = 20000;   // so lange steht die VOLT-Werbung im Status ...
const OWN_MS = 40000;  // ... und so lange der eigene Status des Bots

function plainActivity(a) {
  const out = { name: a.name, type: a.type };
  if (a.url) out.url = a.url;
  if (a.state) out.state = a.state;
  return out;
}

function startPresence(client) {
  if (client.__voltPresence) return;
  const cu = client.user;
  if (!cu || typeof cu.setPresence !== 'function') return;
  const original = cu.setPresence.bind(cu);
  let own = { activities: (cu.presence && cu.presence.activities ? cu.presence.activities : []).map(plainActivity),
              status: (cu.presence && cu.presence.status) || 'online' };
  // Merkt sich jeden Status, den der Bot selbst setzt (setActivity ruft intern setPresence auf)
  cu.setPresence = (data = {}) => {
    own = { activities: Array.isArray(data.activities) ? data.activities : own.activities, status: data.status || own.status };
    return original(data);
  };
  const ad = () => original({ activities: [{ type: 4, name: 'Custom Status', state: VOLT_AD_TEXT }], status: own.status });
  let showingAd = false;
  const step = () => {
    let wait = OWN_MS;
    try {
      if (!own.activities || own.activities.length === 0) {
        if (!showingAd) { ad(); showingAd = true; }
      } else if (showingAd) {
        original({ activities: own.activities, status: own.status }); showingAd = false; wait = OWN_MS;
      } else {
        ad(); showingAd = true; wait = AD_MS;
      }
    } catch (e) { /* Status ist Nebensache, der Bot läuft weiter */ }
    const t = setTimeout(step, wait); if (t.unref) t.unref();
  };
  const first = setTimeout(step, 8000); if (first.unref) first.unref();
  client.__voltPresence = true;
}

function startHeartbeat(client, key) {
  let interval = 60000;
  const started = Date.now();
  let lastMsg = null;
  const say = (code, text) => { if (lastMsg !== code) { console.log(text); lastMsg = code; } };
  async function beat() {
    if (typeof client.isReady === 'function' && !client.isReady()) return;
    const ping = client.ws && typeof client.ws.ping === 'number' && client.ws.ping >= 0 ? Math.round(client.ws.ping) : null;
    try {
      const r = await fetch(VOLT_STATUS_URL, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${key}`, 'User-Agent': `VOLT-Status/${VERSION}` },
        body: JSON.stringify({
          v: VERSION, bot_id: client.user ? client.user.id : null, bot_name: client.user ? client.user.tag : null,
          guilds: client.guilds && client.guilds.cache ? client.guilds.cache.size : null, ping_ms: ping,
          uptime_s: Math.round((Date.now() - started) / 1000), discord_ok: ping !== null, node: process.version,
        }),
        signal: AbortSignal.timeout(15000),
      });
      if (r.status === 200) {
        const d = await r.json().catch(() => ({}));
        say('ok', `[VOLT] Status aktiv: ${d.name || 'Bot'} meldet sich jede Minute bei VOLT ADMIN`);
        if (d.interval) interval = Math.max(30, Number(d.interval)) * 1000;
      } else if (r.status === 401) {
        say('401', '[VOLT] Status abgelehnt: VOLT_STATUS_KEY ist falsch oder wurde gelöscht.');
      } else {
        say(`http${r.status}`, `[VOLT] Website antwortet mit HTTP ${r.status}, versuche es weiter …`);
      }
    } catch (e) {
      say('down', `[VOLT] ${VOLT_LABEL} gerade nicht erreichbar (${e.name || 'Fehler'}), versuche es weiter …`);
    }
  }
  const loop = async () => { await beat(); const t = setTimeout(loop, interval); if (t.unref) t.unref(); };
  const t = setTimeout(loop, 5000); if (t.unref) t.unref();
}

function voltStart(client, opts = {}) {
  if (typeof opts === 'string') opts = { key: opts };
  if (client.__voltStarted) return;
  client.__voltStarted = true;
  const werbung = opts.werbung !== false;
  const key = String(opts.key || process.env.VOLT_STATUS_KEY || '').trim();
  let done = false;
  const onReady = () => {
    if (done) return; done = true;
    if (werbung) startPresence(client);
    if (key) startHeartbeat(client, key);
  };
  if (typeof client.isReady === 'function' && client.isReady()) onReady();
  else {
    let ev = 'ready';
    try { const { Events } = require('discord.js'); if (Events && Events.ClientReady) ev = Events.ClientReady; } catch (e) { /* ohne discord.js-Import */ }
    client.once(ev, onReady);
  }
}

exports.voltStart = voltStart;
