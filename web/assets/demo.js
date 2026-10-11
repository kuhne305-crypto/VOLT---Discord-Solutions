/* VOLT Familien-Dashboard – klickbare Demo.
   Alles läuft nur im Browser mit erfundenen Demo-Daten. Nichts wird gespeichert oder verschickt. */
(function () {
  "use strict";
  var root = document.getElementById("demo");
  if (!root) return;
  var main = document.getElementById("demoMain");
  var path = document.getElementById("demoPath");
  var toastEl = document.getElementById("demoToast");
  var drawer = document.getElementById("demoDrawer");

  /* ---------- Helfer ---------- */
  function esc(s) { return String(s).replace(/[&<>"']/g, function (c) { return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]; }); }
  function money(n) { return "$" + Number(n).toLocaleString("de-DE"); }
  function initials(n) { return n.split(" ").map(function (p) { return p[0]; }).join("").slice(0, 2).toUpperCase(); }
  var toastT = 0;
  function toast(msg) {
    toastEl.textContent = msg; toastEl.hidden = false;
    clearTimeout(toastT); toastT = setTimeout(function () { toastEl.hidden = true; }, 2600);
  }
  var I = {
    grid: '<path d="M4 4h6v6H4zM14 4h6v6h-6zM4 14h6v6H4zM14 14h6v6h-6z"/>',
    users: '<path d="M16 19v-1.5a3.5 3.5 0 0 0-3.5-3.5h-5A3.5 3.5 0 0 0 4 17.5V19M10 11a3.5 3.5 0 1 0 0-7 3.5 3.5 0 0 0 0 7zM20 19v-1.5a3.5 3.5 0 0 0-2.5-3.35M15.5 4.15a3.5 3.5 0 0 1 0 6.7"/>',
    drop: '<path d="M12 3s6 6.4 6 11a6 6 0 0 1-12 0c0-4.6 6-11 6-11z"/>',
    cal: '<path d="M5 6h14v14H5zM5 10h14M9 3v4M15 3v4"/>',
    clip: '<path d="M8 5h8v3H8zM6 6.5H5v14h14v-14h-1M9 12h6M9 16h4"/>',
    out: '<path d="M5 12h9M10 7l5 5-5 5M19 4v16"/>',
    wallet: '<path d="M4 7h14a2 2 0 0 1 2 2v9H4zM4 7l11-3v3M16 13h1"/>',
    week: '<path d="M4 6h16M4 12h10M4 18h7M17 15l2 2 3-4"/>',
    box: '<path d="M4 8l8-4 8 4v8l-8 4-8-4zM4 8l8 4 8-4M12 12v8"/>',
    shield: '<path d="M12 3l7 3v5c0 4.4-3 8-7 10-4-2-7-5.6-7-10V6z"/><path d="M12 8v4M12 15.5v.5"/>',
    paint: '<path d="M12 3a9 9 0 1 0 0 18c1.1 0 1.6-.8 1.6-1.6 0-1-.9-1.4-.9-2.3 0-.9.7-1.6 1.6-1.6H17a4 4 0 0 0 4-4c0-4.7-4-8.5-9-8.5z"/><circle cx="7.5" cy="11" r="1"/><circle cx="10.5" cy="7.5" r="1"/><circle cx="15" cy="8" r="1"/>',
    search: '<circle cx="11" cy="11" r="6"/><path d="M20 20l-4.5-4.5"/>',
    phone: '<path d="M5 4h4l2 5-2.5 1.5a11 11 0 0 0 5 5L15 13l5 2v4a1 1 0 0 1-1 1A16 16 0 0 1 4 5a1 1 0 0 1 1-1z"/>',
    plus: '<path d="M12 5v14M5 12h14"/>',
    check: '<path d="M5 12l4 4 10-10"/>',
    clock: '<circle cx="12" cy="12" r="8"/><path d="M12 8v4l3 2"/>',
    route: '<circle cx="6" cy="18" r="2"/><circle cx="18" cy="6" r="2"/><path d="M8 18h6a3 3 0 0 0 0-6h-4a3 3 0 0 1 0-6h6"/>',
    pulse: '<path d="M3 12h4l3-7 4 14 3-7h4"/>',
    alert: '<path d="M12 4l9 16H3z"/><path d="M12 10v4M12 17v.5"/>',
    back: '<path d="M9 14L4 9l5-5M4 9h10a6 6 0 0 1 0 12h-3"/>',
    filter: '<path d="M4 5h16l-6 7v6l-4 2v-8z"/>'
  };
  function ic(name, cls) { return '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" class="' + (cls || "") + '" aria-hidden="true">' + I[name] + "</svg>"; }
  function kpi(label, value, sub, icon, tone) {
    return '<div class="dm-kpi"><span>' + label + '</span><strong>' + value + '</strong><small>' + sub + '</small><i class="ic ic-' + tone + '">' + ic(icon) + "</i></div>";
  }
  function head(eyebrow, title, text, actions) {
    return '<div class="dm-head"><div><div class="dm-eyebrow">' + eyebrow + '</div><h3>' + title + '</h3><p>' + text + '</p></div>' +
      (actions ? '<div class="dm-actions">' + actions + "</div>" : "") + "</div>";
  }

  /* ---------- Demo-Daten ---------- */
  var RANKS = { 12: "President", 11: "Vice President", 10: "Sergeant at Arms", 9: "Road Captain", 8: "Enforcer", 7: "Treasurer", 6: "Secretary", 5: "Member", 1: "Prospect" };
  var members = [
    ["Vito Castellano", 12, "@vito.c", "555-0100", "23.06.2026", "aktiv"],
    ["Luca Moretti", 11, "@luca.moretti", "555-0101", "16.06.2026", "aktiv"],
    ["Dario Conti", 10, "@dario_c", "555-0104", "01.01.2026", "aktiv"],
    ["Elena Bianchi", 9, "@elena.b", "555-0107", "12.07.2026", "aktiv"],
    ["Marco Rossi", 8, "@marco.rossi", "555-0109", "20.07.2026", "aktiv"],
    ["Matteo Greco", 7, "@matteo.g", "555-0111", "02.08.2026", "aktiv"],
    ["Sofia Romano", 6, "@sofia.r", "555-0112", "15.08.2026", "aktiv"],
    ["Giulia Ferrari", 5, "@giulia.f", "555-0115", "08.10.2026", "aktiv"],
    ["Enzo Marino", 5, "@enzo.m", "555-0118", "28.08.2026", "aktiv"],
    ["Paolo Ricci", 5, "@paolo.r", "555-0121", "04.09.2026", "aktiv"],
    ["Nico Gallo", 1, "@nico.g", "555-0124", "05.10.2026", "probe"],
    ["Chiara Lombardi", 1, "@chiara.l", "555-0127", "07.10.2026", "probe"]
  ].map(function (m) { return { name: m[0], rank: m[1], tag: m[2], tel: m[3], since: m[4], state: m[5] }; });

  var state = {
    view: "uebersicht", q: "", rankFilter: "all", calMode: "monat", lagerTab: "leihgabe",
    rsvp: { komme: ["Vito Castellano", "Luca Moretti", "Elena Bianchi", "Dario Conti"], spaeter: ["Marco Rossi"], nicht: ["Enzo Marino"], you: null },
    green: 3175000, black: 45350000,
    bookings: [
      [50000, "Grüngeld", "Wochenabgabe", "Wochenabgabe Paolo Ricci · KW 41", "Vito Castellano", "Discord", "gerade eben"],
      [50000, "Grüngeld", "Wochenabgabe", "Wochenabgabe Giulia Ferrari · KW 41", "Luca Moretti", "Dashboard", "vor 12 Min"],
      [-25000, "Schwarzgeld", "Einkauf", "Material für Route", "Dario Conti", "Discord", "heute 14:10"],
      [850000, "Schwarzgeld", "Route", "Verkauf Route MDMA", "Vito Castellano", "Dashboard", "gestern"],
      [50000, "Grüngeld", "Wochenabgabe", "Wochenabgabe Enzo Marino · KW 41", "Vito Castellano", "Discord", "gestern"]
    ],
    weekly: [
      ["Dario Conti", 10, true], ["Elena Bianchi", 9, true], ["Marco Rossi", 8, true], ["Matteo Greco", 7, true],
      ["Paolo Ricci", 5, true], ["Giulia Ferrari", 5, true], ["Sofia Romano", 6, false], ["Nico Gallo", 1, false]
    ],
    absences: [
      ["Elena Bianchi", "Langzeit", "01.10.2026", "31.10.2026", "Prüfungsphase"],
      ["Matteo Greco", "Kurzzeit", "08.10.2026", "10.10.2026", "Urlaub"],
      ["Enzo Marino", "Kurzzeit", "08.10.2026", "08.10.2026", "Arbeit bis 23 Uhr"]
    ],
    loans: [
      ["Elena Bianchi", "4× Schutzwesten", "07.10.2026", "Vito Castellano", "overdue"],
      ["Enzo Marino", "2× Rucksäcke", "08.10.2026", "Luca Moretti", "today"],
      ["Marco Rossi", "2× Funkgeräte", "10.10.2026", "Luca Moretti", "soon"],
      ["Sofia Romano", "2× Schutzweste", "ohne Frist", "Vito Castellano", "none"]
    ],
    returned: [["Paolo Ricci", "1× Reparaturkit", "06.10.2026", "Dario Conti"]],
    sanctions: [
      { who: "Enzo Marino", why: "§15 – Nicht abstimmen bei Meet Ups", amount: 10000, due: "13.10.2026", paid: false },
      { who: "Nico Gallo", why: "§7 – Funk nicht dabei", amount: 5000, due: "10.10.2026", paid: false },
      { who: "Paolo Ricci", why: "§3 – Zu spät zum Meet Up", amount: 2500, due: "05.10.2026", paid: true }
    ],
    bloodSel: 0, mode: "dark", acc: "#e5243b"
  };
  var BLOOD = [
    { type: "in", name: "Giulia Ferrari", date: "Donnerstag, 08.10.2026", rank: "05 – Member", by: "Luca Moretti", text: "Willkommen in der Familie! 🎉" },
    { type: "in", name: "Chiara Lombardi", date: "Mittwoch, 07.10.2026", rank: "01 – Prospect", by: "Vito Castellano", text: "Probezeit gestartet. Viel Erfolg!" },
    { type: "in", name: "Nico Gallo", date: "Montag, 05.10.2026", rank: "01 – Prospect", by: "Dario Conti", text: "Probezeit gestartet. Viel Erfolg!" },
    { type: "out", name: "Tommaso Bruno", date: "Freitag, 02.10.2026", rank: "05 – Member", by: "Vito Castellano", text: "Hat die Familie verlassen. Rollen wurden entfernt." }
  ];

  /* ---------- Ansichten ---------- */
  function vUebersicht() {
    var vals = [2, 2, 2, 2, 9, 5, 13], labels = ["Fr", "Sa", "So", "Mo", "Di", "Mi", "Do"];
    var W = 560, H = 180, pad = 26, max = 20;
    var pts = vals.map(function (v, i) { return [pad + i * (W - pad * 2) / (vals.length - 1), H - 24 - v / max * (H - 44)]; });
    var line = pts.map(function (p, i) { return (i ? "L" : "M") + p[0].toFixed(1) + " " + p[1].toFixed(1); }).join(" ");
    var area = line + " L" + pts[pts.length - 1][0] + " " + (H - 24) + " L" + pts[0][0] + " " + (H - 24) + " Z";
    var grid = [0, 5, 10, 15, 20].map(function (g) { var y = H - 24 - g / max * (H - 44); return '<line x1="' + pad + '" x2="' + (W - pad) + '" y1="' + y + '" y2="' + y + '" stroke="var(--d-line)"/><text x="4" y="' + (y + 4) + '" font-size="10" fill="var(--d-muted)">' + g + "</text>"; }).join("");
    var xl = labels.map(function (l, i) { return '<text x="' + pts[i][0] + '" y="' + (H - 6) + '" font-size="10" text-anchor="middle" fill="var(--d-muted)">' + l + "</text>"; }).join("");
    var dots = pts.map(function (p) { return '<circle cx="' + p[0] + '" cy="' + p[1] + '" r="3.5" fill="var(--acc)"/>'; }).join("");
    var next = [["8", "Meet Up", "📅 MEET UP", "20:30 Uhr · ✅ 10 kommen"], ["9", "Gangwar · Hafen", "⚔️ GANGWAR", "21:30 Uhr · ✅ 6 kommen"], ["10", "Konvoi-Ausfahrt Paleto", "🎉 EVENT", "20:30 Uhr · Treffpunkt Garage"], ["11", "Training Schießstand", "🏋️ TRAINING", "20:00 Uhr · ✅ 5 kommen"], ["14", "Sommerfest am Clubhaus", "🎉 EVENT", "21:00 Uhr · Clubhaus"]];
    return head("Deine Familie", "Alles im <em>Griff.</em>", "Willkommen zurück, Vito. Hier läuft alles zusammen – Discord und Dashboard. (Demo)", '<span class="pill muted">' + ic("cal") + " Donnerstag, 8. Oktober 2026</span>") +
      '<div class="dm-kpis">' + kpi("Mitglieder", "12", "Familienmitglieder auf dem Server", "users", "acc") + kpi("Familienkasse", money(state.green + state.black), "davon " + money(state.black) + " Schwarzgeld", "wallet", "info") + kpi("Aktuelle Route", "MDMA", "Asiatische Botschaft · noch 1 Tag", "route", "warn") + kpi("Aktivitäten", "39", "in den letzten 7 Tagen", "pulse", "info") + "</div>" +
      '<div class="dm-grid"><div class="dm-card"><h4>Serveraktivität</h4><p class="sub">Aktionen aus Discord, Dashboard und API – letzte 7 Tage · <b style="color:var(--d-text)">39</b> erfasste Aktivitäten</p>' +
      '<svg class="chart" viewBox="0 0 ' + W + " " + H + '" preserveAspectRatio="none" role="img" aria-label="Serveraktivität der letzten 7 Tage">' + grid +
      '<path d="' + area + '" fill="var(--acc)" opacity=".14"/><path d="' + line + '" fill="none" stroke="var(--acc)" stroke-width="2.4"/>' + dots + xl + "</svg></div>" +
      '<div class="dm-card"><h4>Als Nächstes</h4><p class="sub">Aufstellungen &amp; Events</p><div class="dm-list">' +
      next.map(function (n) { return '<button class="dm-li" data-go="termine"><span class="date"><small>OKT</small><b>' + n[0] + '</b></span><span class="grow"><small style="color:var(--acc);font-weight:700;font-size:10.5px">' + n[2] + "</small><b>" + n[1] + "</b><small>" + n[3] + "</small></span></button>"; }).join("") + "</div></div></div>";
  }

  function vMitglieder() {
    var q = state.q.trim().toLowerCase();
    var list = members.filter(function (m) {
      var okR = state.rankFilter === "all" || String(m.rank) === state.rankFilter;
      var okQ = !q || (m.name + " " + m.tag + " " + m.tel).toLowerCase().indexOf(q) >= 0;
      return okR && okQ;
    });
    var probe = members.filter(function (m) { return m.state === "probe"; }).length;
    var opts = '<option value="all">Alle Ränge</option>' + Object.keys(RANKS).sort(function (a, b) { return b - a; }).map(function (r) { return '<option value="' + r + '"' + (state.rankFilter === r ? " selected" : "") + ">" + String(r).padStart(2, "0") + " – " + RANKS[r] + "</option>"; }).join("");
    var rows = list.map(function (m, i) {
      return "<tr><td><span class=\"rank\">" + m.rank + " – " + RANKS[m.rank] + '</span></td><td><div class="who"><span class="ava">' + initials(m.name) + "</span><div><b>" + esc(m.name) + '<span class="demo-tag">DEMO</span></b><small>' + m.tag + '</small></div></div></td><td><span class="tel">' + m.tel + '</span></td><td class="num">' + m.since + "</td><td>" + (m.state === "probe" ? '<span class="pill warn">Probezeit</span>' : '<span class="pill ok">Verifiziert</span>') + '</td><td class="right"><button class="dm-btn sm" data-detail="' + members.indexOf(m) + '">Details</button></td></tr>';
    }).join("") || '<tr><td colspan="6" style="color:var(--d-muted);padding:1.2rem .5rem">Kein Demo-Mitglied gefunden.</td></tr>';
    return head("Zentrale · Mitglieder", "Mitglieder", "12 Demo-Mitglieder – im echten Dashboard automatisch aus Discord, mit Rang, IC-Name und Nummer.",
      '<button class="dm-btn" data-act="copy">' + ic("phone") + 'Nummern kopieren</button><button class="dm-btn acc" data-act="add">' + ic("plus") + "Mitglied hinzufügen</button>") +
      '<div class="dm-kpis">' + kpi("Mitglieder", "12", "in der Familie", "users", "acc") + kpi("Verifiziert", String(12 - probe), "Probezeit bestanden", "check", "ok") + kpi("In Probezeit", String(probe), "noch nicht übernommen", "clock", "warn") + kpi("Gefiltert", String(list.length), "angezeigt", "filter", "acc") + "</div>" +
      '<div class="dm-card"><div class="dm-tools"><label class="dm-input">' + ic("search") + '<input id="dmSearch" type="search" placeholder="Name, Nummer oder Discord-Name …" value="' + esc(state.q) + '" aria-label="Demo-Mitglieder durchsuchen"></label><select class="dm-select" id="dmRank" aria-label="Nach Rang filtern">' + opts + "</select></div>" +
      '<div class="dm-table-wrap"><table class="dm-table"><thead><tr><th>Rang</th><th>Name</th><th>Telefon</th><th>Mitglied seit</th><th>Status</th><th class="right">Aktionen</th></tr></thead><tbody>' + rows + "</tbody></table></div></div>";
  }

  function vBlood() {
    var b = BLOOD[state.bloodSel];
    var list = BLOOD.map(function (x, i) {
      return '<button class="dm-li' + (i === state.bloodSel ? " sel" : "") + '" data-blood="' + i + '"><span class="ava">' + initials(x.name) + '</span><span class="grow"><b>' + x.name + '<span class="demo-tag">DEMO</span></b><small>' + x.date + " · " + x.rank + "</small></span>" + (x.type === "in" ? '<span class="pill ok">Blood-In</span>' : '<span class="pill bad">Blood-Out</span>') + "</button>";
    }).join("");
    var em = '<div class="dcx"><span class="ava-df">DF</span><div><div class="meta"><b>Deine Familie</b><span class="bot">BOT</span><time>Heute um 23:59</time></div><span class="mention">@' + b.name + '</span>' +
      '<div class="em ' + (b.type === "in" ? "ok" : "") + '"><span class="t">' + (b.type === "in" ? "🩸 Blood-In" : "🚪 Blood-Out") + "</span><span><b>" + b.date + "</b><br>" + b.text + '</span><div class="f"><span><b>👤 Mitglied</b><span class="mention">@' + b.name + "</span></span><span><b>🎖️ Rang</b>" + b.rank + "</span><span><b>🤝 " + (b.type === "in" ? "Aufgenommen von" : "Eingetragen von") + "</b>" + b.by + '</span></div><span class="ft">Deine Familie</span></div></div></div>';
    return head("Familie · Blood-In & Out", "Blood-In &amp; Blood-Out", "Aufnahme und Ausstieg bekommen ihre eigene Nachricht im Discord. Rang ändern tauscht die Discord-Rolle.",
      '<button class="dm-btn acc" data-act="add">' + ic("plus") + "Blood-In eintragen</button>") +
      '<div class="dm-grid even"><div class="dm-card"><h4>Letzte Einträge</h4><p class="sub">Klick auf einen Eintrag, um die Discord-Nachricht zu sehen</p><div class="dm-list">' + list + "</div></div><div>" + em + "</div></div>";
  }

  function vTermine() {
    var ev = { 1: [["e", "20:30", "📅 Meet Up"]], 3: [["g", "22:00", "⚔️ Gangwar · Innenstadt"]], 4: [["e", "22:00", "🎉 Turnier gegen Ost"], ["s", "23:59", "⚠️ Sanktion fällig"]], 8: [["e", "20:30", "📅 Meet Up"], ["t", "", "🗺️ Route endet: MDMA"]], 9: [["g", "21:30", "⚔️ Gangwar · Hafen"]], 10: [["e", "20:30", "🎉 Konvoi-Ausfahrt"]], 11: [["t", "20:00", "🏋️ Training Schießstand"]], 14: [["e", "21:00", "🎉 Sommerfest"]], 15: [["e", "20:30", "📅 Meet Up"]], 17: [["g", "22:00", "⚔️ Gangwar · Docks"]], 22: [["e", "20:30", "📅 Meet Up"]], 25: [["t", "19:00", "🏋️ Fahrtraining"]], 29: [["e", "20:30", "📅 Meet Up"]], 31: [["e", "22:00", "🎃 Halloween-Party"]] };
    var cal;
    if (state.calMode === "monat") {
      var cells = ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"].map(function (d) { return '<div class="h">' + d + "</div>"; }).join("");
      for (var b = 0; b < 3; b++) cells += '<div class="x"></div>';
      for (var d = 1; d <= 31; d++) {
        cells += '<div class="' + (d === 8 ? "today" : "") + '"><span class="d">' + d + "</span>" + (ev[d] || []).map(function (e) { return '<span class="ev ' + e[0] + '">' + (e[1] ? "<span>" + e[1] + " </span>" : "") + e[2] + "</span>"; }).join("") + "</div>";
      }
      var tail = (3 + 31) % 7; if (tail) for (var t = tail; t < 7; t++) cells += '<div class="x"></div>';
      cal = '<div class="cal">' + cells + "</div>";
    } else {
      cal = '<div class="dm-list">' + Object.keys(ev).filter(function (d) { return d >= 8; }).map(function (d) { return ev[d].map(function (e) { return '<div class="dm-li"><span class="date"><small>OKT</small><b>' + d + '</b></span><span class="grow"><b>' + e[2] + "</b><small>" + (e[1] ? e[1] + " Uhr" : "ganztägig") + "</small></span></div>"; }).join(""); }).join("") + "</div>";
    }
    var r = state.rsvp;
    function names(arr) { return arr.length ? arr.map(function (n) { return '<span class="mention' + (n === "Du (Demo)" ? " you" : "") + '">@' + n + "</span>"; }).join(" ") : "…"; }
    var meet = '<div class="dcx"><span class="ava-df">DF</span><div><div class="meta"><b>Deine Familie</b><span class="bot">BOT</span><time>Gestern um 23:59</time></div><span class="mention">@Member</span>' +
      '<div class="em"><span class="t">📅 Meet Up</span><span><b>Freitag, 09.10.2026</b><br>Uhrzeit: <b>20:30 Uhr</b> · Treffpunkt: <b>Clubhaus</b><br>🕒 Später = Ankunft bis 21:00 Uhr</span>' +
      "<span><b>✅ Komme (" + r.komme.length + ")</b>" + names(r.komme) + "</span><span><b>🕒 Später (" + r.spaeter.length + ") · bis 21:00 Uhr</b>" + names(r.spaeter) + "</span>" +
      '<div class="f"><span><b>❌ Komme nicht (' + r.nicht.length + ")</b>" + names(r.nicht) + "</span><span><b>⏳ Noch offen (" + Math.max(0, 7 - r.komme.length - r.spaeter.length - r.nicht.length) + ')</b>…</span></div><span class="ft">Deine Familie · Demo: klick auf einen Button</span></div>' +
      '<div class="btns"><button class="b-ok" data-rsvp="komme">Komme</button><button class="b-grey" data-rsvp="spaeter">Komme später</button><button class="b-bad" data-rsvp="nicht">Komme nicht</button></div></div></div>';
    return head("Organisation · Termine", "Termine &amp; Aufstellung", "Ein Kalender für alles: Aufstellungen, Meet Ups, Events, Routenwechsel und fällige Sanktionen. Meet Ups werden am Vortag um 23:59 automatisch gepostet.",
      '<button class="dm-btn" data-act="csv">CSV exportieren</button><button class="dm-btn acc" data-act="add">' + ic("plus") + "Termin erstellen</button>") +
      '<div class="dm-kpis three">' + kpi("Anstehende Termine", "10", "im Oktober", "cal", "acc") + kpi("Zusagen", String(r.komme.length + r.spaeter.length), "für Meet Up am 09.10.", "check", "ok") + kpi("Nächster Termin", "08.10. · 20:30", "📅 Meet Up", "clock", "warn") + "</div>" +
      '<div class="dm-card"><div class="dm-tabs" role="tablist"><button role="tab" data-cal="monat" aria-selected="' + (state.calMode === "monat") + '">Monat</button><button role="tab" data-cal="liste" aria-selected="' + (state.calMode === "liste") + '">Liste</button></div>' +
      '<h4 style="margin-bottom:.6rem">Oktober 2026</h4>' + cal + "</div>" +
      '<div class="dm-grid even" style="margin-top:.75rem"><div>' + meet + '</div><div class="dm-card"><h4>So funktioniert die Aufstellung</h4><p class="sub">Direkt im Discord, ohne Befehl</p><div class="dm-list">' +
      [["✅", "Komme", "Du stehst sofort in der Liste, für alle sichtbar."], ["🕒", "Komme später", "Der Bot fragt direkt nach deiner Ankunftszeit."], ["❌", "Komme nicht", "Wer abgemeldet ist, wird automatisch berücksichtigt."], ["🕛", "Automatisch um 23:59", "Meet Ups werden am Vortag gepostet und zum Start eingefroren."]].map(function (x) { return '<div class="dm-li"><span style="font-size:18px">' + x[0] + '</span><span class="grow"><b>' + x[1] + "</b><small>" + x[2] + "</small></span></div>"; }).join("") +
      "</div></div></div>";
  }

  function vAbmeldungen() {
    var a = state.absences;
    var opts = members.map(function (m) { return '<option>' + m.name + "</option>"; }).join("");
    var rows = a.map(function (x) { return '<div class="dm-li"><span class="ava">' + initials(x[0]) + '</span><span class="grow"><b>' + esc(x[0]) + '<span class="demo-tag">DEMO</span></b><small>' + esc(x[2]) + " – " + esc(x[3]) + " · Grund: " + esc(x[4]) + "</small></span>" + (x[1] === "Langzeit" ? '<span class="pill info">Langzeit</span>' : '<span class="pill warn">Kurzzeit</span>') + "</div>"; }).join("");
    return head("Familie · Abmeldungen", "Abmeldungen", "Kurz- und Langzeit mit eigener Übersicht. Wer abgemeldet ist, wird bei Aufstellungen automatisch berücksichtigt.", "") +
      '<div class="dm-kpis">' + kpi("Aktiv abgemeldet", String(a.length), "gerade nicht verfügbar", "out", "acc") + kpi("Kurzzeit", String(a.filter(function (x) { return x[1] === "Kurzzeit"; }).length), "bis 7 Tage", "clock", "warn") + kpi("Langzeit", String(a.filter(function (x) { return x[1] === "Langzeit"; }).length), "länger als 7 Tage", "cal", "info") + kpi("Heute zurück", "1", "Enzo Marino ab 23 Uhr", "back", "ok") + "</div>" +
      '<div class="dm-card"><h4>Abmeldung eintragen</h4><p class="sub">Probier es aus – der Eintrag erscheint nur in deinem Browser.</p>' +
      '<form class="dm-form" id="absForm"><label>Mitglied<select name="who">' + opts + '</select></label><label>Art<select name="kind"><option>Kurzzeit</option><option>Langzeit</option></select></label><label>Bis<input name="until" type="text" value="12.10.2026" maxlength="10"></label><label>Grund<input name="why" type="text" value="Urlaub" maxlength="40"></label><button class="dm-btn acc" type="submit">' + ic("plus") + "Eintragen</button></form>" +
      '<div class="dm-list">' + rows + "</div></div>";
  }

  function vKasse() {
    var rows = state.bookings.map(function (b) {
      return '<tr><td class="num ' + (b[0] >= 0 ? "amount-in" : "amount-out") + '">' + (b[0] >= 0 ? "+ " : "– ") + money(Math.abs(b[0])) + "</td><td>" + (b[1] === "Grüngeld" ? '<span class="pill ok">● Grüngeld</span>' : '<span class="pill warn">● Schwarzgeld</span>') + "</td><td>" + b[2] + "</td><td>" + esc(b[3]) + "</td><td>" + b[4] + '<br><small style="color:var(--acc)">' + b[5] + '</small></td><td style="color:var(--d-muted)">' + b[6] + "</td></tr>";
    }).join("");
    function vault(kind, label, amount, tag) {
      return '<div class="vault ' + kind + '"><div class="top"><span>' + label + "</span><span>" + tag + "</span></div><strong>" + money(amount) + '</strong><div class="row"><button class="dm-btn ok" data-book="' + kind + ':in">Einzahlen</button><button class="dm-btn bad" data-book="' + kind + ':out">Auszahlen</button></div></div>';
    }
    return head("Finanzen · Kasse", "Kasse", "Grüngeld und Schwarzgeld getrennt, jede Buchung mit Grund – im Dashboard oder per /kasse in Discord.", '<button class="dm-btn" data-act="csv">CSV exportieren</button>') +
      '<div class="money">' + vault("green", "● Grüne Kasse · legal", state.green, "safe") + vault("black", "● Schwarze Kasse · off the books", state.black, "risk") + "</div>" +
      '<p style="color:var(--d-muted);margin:0 0 .75rem">Gesamt <b style="color:var(--d-text)">' + money(state.green + state.black) + "</b> · Demo: Ein- und Auszahlen bucht je $50.000</p>" +
      '<div class="dm-card"><h4>Buchungen</h4><p class="sub">Die letzten Ein- und Auszahlungen</p><div class="dm-table-wrap"><table class="dm-table"><thead><tr><th>Betrag</th><th>Kasse</th><th>Kategorie</th><th>Grund</th><th>Von</th><th>Zeit</th></tr></thead><tbody>' + rows + "</tbody></table></div></div>";
  }

  function vWochen() {
    var paid = state.weekly.filter(function (w) { return w[2]; }).length, total = state.weekly.length;
    var rows = state.weekly.map(function (w, i) {
      return "<tr><td>" + (w[2] ? '<span style="color:var(--ok)">' + ic("check") + "</span>" : '<span style="color:var(--bad)">✕</span>') + '</td><td><span class="rank">' + String(w[1]).padStart(2, "0") + " " + RANKS[w[1]] + "</span></td><td>" + w[0] + '<span class="demo-tag">DEMO</span></td><td class="num">' + (w[2] ? "$50.000" : "–") + "</td><td>" + (w[2] ? '<span class="pill ok">Abgeschlossen</span>' : '<span class="pill bad">Ausstehend</span>') + '</td><td class="right">' + (w[2] ? "" : '<button class="dm-btn sm ok" data-pay="' + i + '">Abhaken</button>') + "</td></tr>";
    }).join("");
    return head("Finanzen · Wochenabgaben", "Wochenabgaben", "Die Woche läuft Montag bis Sonntag. Sonntag um 23:59 wird sie automatisch abgeschlossen und die neue Woche gepostet. Jede bezahlte Abgabe wird automatisch in die Kasse gebucht.",
      '<button class="dm-btn" data-act="remind">Erinnern</button><button class="dm-btn acc" data-act="close">' + ic("check") + "Woche abschließen</button>") +
      '<div class="dm-kpis three">' + kpi("Abgaben erhalten", paid + " / " + total, Math.round(paid / total * 100) + " % bezahlt", "check", "ok") + kpi("Noch offen", money((total - paid) * 50000), (total - paid) + " Abgaben ausstehend", "clock", "warn") + kpi("Diese Woche erhalten", money(paid * 50000), "gebucht als Grüngeld", "wallet", "acc") + "</div>" +
      '<div class="dm-card"><h4>KW 41 · 05.10. – 11.10.2026</h4><p class="sub">Abgabe pro Person: $50.000 · fällig bis Sonntag 23:59</p><div class="dm-table-wrap"><table class="dm-table"><thead><tr><th></th><th>Rang</th><th>Mitglied</th><th>Betrag</th><th>Status</th><th class="right">Aktion</th></tr></thead><tbody>' + rows + "</tbody></table></div></div>";
  }

  function vLager() {
    var tab = state.lagerTab, body;
    if (tab === "leihgabe") {
      body = '<div class="dm-table-wrap"><table class="dm-table"><thead><tr><th>Mitglied</th><th>Gegenstand</th><th>Rückgabe bis</th><th>Ausgegeben von</th><th class="right">Aktion</th></tr></thead><tbody>' +
        (state.loans.map(function (l, i) {
          var due = l[4] === "overdue" ? '<span class="pill bad">⛔ ' + l[2] + "</span>" : l[4] === "today" ? '<span class="pill warn">' + l[2] + " · heute</span>" : l[4] === "soon" ? '<span class="pill warn">' + l[2] + "</span>" : '<span style="color:var(--d-muted)">ohne Frist</span>';
          return '<tr><td><div class="who"><span class="ava">' + initials(l[0]) + "</span><b>" + l[0] + '</b></div></td><td>📦 ' + l[1] + "</td><td>" + due + "</td><td>" + l[3] + '</td><td class="right"><button class="dm-btn sm ok" data-return="' + i + '">Zurückgegeben</button></td></tr>';
        }).join("") || '<tr><td colspan="5" style="color:var(--d-muted)">Keine offenen Leihgaben. Alles zurück! 🎉</td></tr>') + "</tbody></table></div>";
    } else if (tab === "in") {
      body = '<div class="dm-list">' + state.returned.map(function (l) { return '<div class="dm-li"><span class="ava">' + initials(l[0]) + '</span><span class="grow"><b>' + l[1] + "</b><small>zurück von " + l[0] + " · " + l[2] + '</small></span><span class="pill ok">IN</span></div>'; }).join("") + "</div>";
    } else if (tab === "out") {
      body = '<div class="dm-list">' + [["2× Schutzweste", "Sofia Romano", "02.10.2026"], ["Material Route", "Dario Conti", "08.10.2026"], ["1× Funkgerät (defekt)", "Marco Rossi", "05.10.2026"]].map(function (l) { return '<div class="dm-li"><span class="ava">' + initials(l[1]) + '</span><span class="grow"><b>' + l[0] + "</b><small>raus durch " + l[1] + " · " + l[2] + '</small></span><span class="pill bad">OUT</span></div>'; }).join("") + "</div>";
    } else {
      body = '<div class="dm-table-wrap"><table class="dm-table"><thead><tr><th>Gegenstand</th><th class="right">Bestand</th><th class="right">Verliehen</th><th class="right">Heute</th></tr></thead><tbody>' +
        [["Schutzweste", 46, 6, "+6"], ["Funkgerät", 18, 2, "+2"], ["Rucksack", 12, 2, "0"], ["Verbandskasten", 120, 0, "−14"], ["Reparaturkit", 33, 0, "−3"], ["Dietrich", 9, 0, "−1"]].map(function (r) { return "<tr><td>📦 " + r[0] + '</td><td class="right num">' + r[1] + '</td><td class="right num">' + r[2] + '</td><td class="right num ' + (r[3].indexOf("+") === 0 ? "amount-in" : r[3] === "0" ? "" : "amount-out") + '">' + r[3] + "</td></tr>"; }).join("") + "</tbody></table></div>";
    }
    var overdue = state.loans.filter(function (l) { return l[4] === "overdue"; }).length;
    var today = state.loans.filter(function (l) { return l[4] === "today"; }).length;
    var tabs = [["bestand", "🗃️ Bestand"], ["out", "📤 OUT"], ["leihgabe", "📦 Leihgabe (" + state.loans.length + ")"], ["in", "📥 IN"]].map(function (t) { return '<button role="tab" data-lager="' + t[0] + '" aria-selected="' + (tab === t[0]) + '">' + t[1] + "</button>"; }).join("");
    return head("Lagerverwaltung · Leihgabe", "Leihgabe – wer hat was?", "OUT, LEIHGABE und IN: jede Bewegung bekommt eine eigene Nachricht im Discord, mit Buttons darunter – und im Dashboard genauso.", '<button class="dm-btn acc" data-act="add">' + ic("plus") + "Leihgabe eintragen</button>") +
      '<div class="dm-kpis">' + kpi("Verliehen", String(state.loans.length), "offene Leihgaben", "box", "acc") + kpi("Überfällig", String(overdue), "Rückgabedatum vorbei", "alert", "acc") + kpi("Heute fällig", String(today), "heute zurückgeben", "clock", "warn") + kpi("Zurück diese Woche", String(state.returned.length), "zurückgenommen", "back", "ok") + "</div>" +
      '<div class="dm-card"><div class="dm-tabs" role="tablist">' + tabs + "</div>" + body + "</div>";
  }

  function vSanktionen() {
    var open = state.sanctions.filter(function (s) { return !s.paid; });
    var first = open[0];
    var rows = state.sanctions.map(function (s, i) {
      return '<div class="dm-li"><span class="ava">' + initials(s.who) + '</span><span class="grow"><b>' + s.who + '<span class="demo-tag">DEMO</span></b><small>' + s.why + " · fällig " + s.due + '</small></span><span class="num" style="font-weight:700">' + money(s.amount) + "</span>" + (s.paid ? '<span class="pill ok">Bezahlt</span>' : '<button class="dm-btn sm ok" data-sanc="' + i + '">Bezahlt</button>') + "</div>";
    }).join("");
    var em = first ? '<div class="dcx"><span class="ava-df">DF</span><div><div class="meta"><b>Deine Familie</b><span class="bot">BOT</span><time>Heute um 17:02</time></div><span class="mention">@' + first.who + '</span><div class="em warn"><span class="t">⚠️ Neue Sanktion verhängt</span><span>Bitte innerhalb der Frist bei der Leitung bezahlen.</span><div class="f"><span><b>📋 Grund</b>' + first.why + "</span><span><b>💰 Betrag</b>" + money(first.amount) + "</span><span><b>📅 Fällig bis</b>" + first.due + '</span><span><b>✍️ Erstellt von</b>Vito Castellano</span></div><span class="ft">Deine Familie · Erinnerung kommt 24 h vorher per DM</span></div></div></div>'
      : '<div class="dm-card"><h4>Alles bezahlt 🎉</h4><p class="sub" style="margin:0">Keine offenen Sanktionen in der Demo.</p></div>';
    return head("Ordnung · Sanktionen", "Sanktionen", "Sanktionen mit Grund, Betrag und Frist. Der Bot postet sie im Discord und erinnert 24 Stunden vorher per DM.", '<button class="dm-btn acc" data-act="add">' + ic("plus") + "Sanktion verhängen</button>") +
      '<div class="dm-kpis three">' + kpi("Offen", String(open.length), "noch nicht bezahlt", "alert", "acc") + kpi("Offener Betrag", money(open.reduce(function (a, s) { return a + s.amount; }, 0)), "bei der Leitung bezahlen", "wallet", "warn") + kpi("Bezahlt", String(state.sanctions.length - open.length), "diesen Monat", "check", "ok") + "</div>" +
      '<div class="dm-grid even"><div class="dm-card"><h4>Alle Sanktionen</h4><p class="sub">Demo: „Bezahlt“ bucht in die Kasse</p><div class="dm-list">' + rows + "</div></div><div>" + em + "</div></div>";
  }

  function vDesign() {
    var colors = ["#e5243b", "#b3123f", "#f97316", "#eab308", "#f4f4f5", "#3b82f6", "#8b5cf6", "#22c55e"];
    return head("Persönlich einstellbar", "Hell oder dunkel. <em>Deine Farbe.</em>", "Familienfarbe und Logo legt die Leitung fest. Jedes Mitglied stellt sich den Rest selbst ein. Probier es aus.", "") +
      '<div class="dm-card" style="display:grid;gap:1.2rem"><div><h4>Erscheinungsbild</h4><p class="sub">Gilt nur für dich</p><div class="modes">' +
      [["dark", "Dunkel", "linear-gradient(135deg,#141215,#0b0a0c)"], ["light", "Hell", "linear-gradient(135deg,#ffffff,#e9e9ef)"], ["system", "System", "linear-gradient(90deg,#141215 50%,#ffffff 50%)"]].map(function (m) {
        return '<button data-mode="' + m[0] + '" aria-pressed="' + (state.modeChoice === m[0] || (!state.modeChoice && m[0] === "dark")) + '"><i style="background:' + m[2] + ';border:1px solid var(--d-line2)"></i>' + m[1] + "</button>";
      }).join("") + "</div></div>" +
      '<div><h4>Deine Akzentfarbe</h4><p class="sub">Der erste Kreis ist die Familienfarbe von Deine Familie.</p><div class="swatches">' +
      colors.map(function (c) { return '<button data-acc="' + c + '" style="background:' + c + '" aria-label="Akzentfarbe ' + c + '" aria-pressed="' + (state.acc === c) + '"></button>'; }).join("") + "</div></div></div>";
  }

  var VIEWS = {
    uebersicht: ["Übersicht", vUebersicht], mitglieder: ["Mitglieder", vMitglieder], blood: ["Blood-In & Out", vBlood],
    termine: ["Termine & Aufstellung", vTermine], abmeldungen: ["Abmeldungen", vAbmeldungen], kasse: ["Kasse", vKasse],
    wochen: ["Wochenabgaben", vWochen], lager: ["Lagerverwaltung", vLager], sanktionen: ["Sanktionen", vSanktionen], design: ["Erscheinungsbild", vDesign]
  };

  function render(keepScroll) {
    var v = VIEWS[state.view];
    var st = main.scrollTop;
    main.innerHTML = v[1]();
    path.textContent = "Deine Familie / " + v[0];
    if (keepScroll) main.scrollTop = st; else main.scrollTop = 0;
    root.querySelectorAll("[data-view]").forEach(function (b) {
      if (b.getAttribute("data-view") === state.view) b.setAttribute("aria-current", "page"); else b.removeAttribute("aria-current");
    });
  }
  function go(view) { state.view = view; drawer.hidden = true; render(false); }

  /* ---------- Klicks ---------- */
  root.addEventListener("click", function (e) {
    var t = e.target.closest("button, [data-go]");
    if (!t || !root.contains(t)) return;
    var a;
    if ((a = t.getAttribute("data-view"))) {
      go(a);
      var side = root.querySelector(".demo-side");
      if (side && side.scrollWidth > side.clientWidth) side.scrollLeft = t.offsetLeft - side.clientWidth / 2 + t.offsetWidth / 2;
      return;
    }
    if ((a = t.getAttribute("data-go"))) return go(a);
    if ((a = t.getAttribute("data-detail")) !== null) return openMember(members[+a]);
    if (t.hasAttribute("data-close")) { drawer.hidden = true; return; }
    if ((a = t.getAttribute("data-blood")) !== null) { state.bloodSel = +a; return render(true); }
    if ((a = t.getAttribute("data-cal"))) { state.calMode = a; return render(true); }
    if ((a = t.getAttribute("data-lager"))) { state.lagerTab = a; return render(true); }
    if ((a = t.getAttribute("data-rsvp"))) {
      var r = state.rsvp;
      ["komme", "spaeter", "nicht"].forEach(function (k) { r[k] = r[k].filter(function (n) { return n !== "Du (Demo)"; }); });
      r[a].push("Du (Demo)");
      render(true); return toast(a === "spaeter" ? "Im echten Bot fragt „Später“ direkt nach deiner Ankunftszeit." : "Eingetragen! Im echten Discord sieht das jeder sofort.");
    }
    if ((a = t.getAttribute("data-book"))) {
      var p = a.split(":"), amt = 50000, sign = p[1] === "in" ? 1 : -1;
      if (p[0] === "green") state.green += sign * amt; else state.black += sign * amt;
      state.bookings.unshift([sign * amt, p[0] === "green" ? "Grüngeld" : "Schwarzgeld", "Demo", sign > 0 ? "Demo-Einzahlung" : "Demo-Auszahlung", "Du (Demo)", "Dashboard", "gerade eben"]);
      state.bookings = state.bookings.slice(0, 7);
      render(true); return toast("Demo-Buchung angelegt. Im echten Dashboard landet sie auch im Discord-Log.");
    }
    if ((a = t.getAttribute("data-pay")) !== null) { state.weekly[+a][2] = true; render(true); return toast("Abgabe abgehakt und als Grüngeld gebucht (Demo)."); }
    if ((a = t.getAttribute("data-return")) !== null) {
      var l = state.loans.splice(+a, 1)[0]; state.returned.unshift([l[0], l[1], "heute", "Du (Demo)"]);
      render(true); return toast("Zurückgegeben – landet im echten Lager automatisch in IN.");
    }
    if ((a = t.getAttribute("data-sanc")) !== null) { state.sanctions[+a].paid = true; render(true); return toast("Als bezahlt markiert (Demo)."); }
    if ((a = t.getAttribute("data-acc"))) { state.acc = a; root.style.setProperty("--acc", a); return render(true); }
    if ((a = t.getAttribute("data-mode"))) {
      state.modeChoice = a;
      var light = a === "light" || (a === "system" && window.matchMedia && window.matchMedia("(prefers-color-scheme: light)").matches);
      root.setAttribute("data-mode", light ? "light" : "dark");
      return render(true);
    }
    if ((a = t.getAttribute("data-act"))) {
      var msg = { copy: "12 Demo-Nummern kopiert (nur im echten Dashboard landen sie in der Zwischenablage).", csv: "Export gibt es im echten Dashboard.", remind: "Im echten Dashboard bekommen alle Offenen jetzt eine DM.", close: "Im echten Dashboard wird die Woche jetzt abgeschlossen und KW 42 gepostet.", add: "In der Demo ist das gesperrt – im echten Dashboard öffnet sich hier das Formular." }[a];
      return toast(msg || "Nur in der echten Version.");
    }
  });
  root.addEventListener("input", function (e) {
    if (e.target.id === "dmSearch") {
      state.q = e.target.value;
      var pos = e.target.selectionStart;
      render(true);
      var s = document.getElementById("dmSearch"); if (s) { s.focus(); try { s.setSelectionRange(pos, pos); } catch (x) {} }
    }
  });
  root.addEventListener("change", function (e) {
    if (e.target.id === "dmRank") { state.rankFilter = e.target.value; render(true); }
  });
  root.addEventListener("submit", function (e) {
    if (e.target.id !== "absForm") return;
    e.preventDefault();
    var f = e.target, until = f.until.value.trim() || "–", why = f.why.value.trim().slice(0, 40) || "–";
    state.absences.unshift([f.who.value, f.kind.value, "11.10.2026", until.slice(0, 10), why]);
    render(true);
    toast("Abmeldung eingetragen (nur in deinem Browser). Im echten Bot kommt sie auch in #abmeldungen.");
  });
  root.addEventListener("keydown", function (e) { if (e.key === "Escape") drawer.hidden = true; });

  function openMember(m) {
    var p = document.getElementById("demoDrawerBody");
    p.innerHTML = '<div class="who"><span class="ava">' + initials(m.name) + "</span><div><b>" + esc(m.name) + '<span class="demo-tag">DEMO</span></b><small>' + m.tag + "</small></div></div>" +
      '<dl class="kv"><dt>Rang</dt><dd>' + String(m.rank).padStart(2, "0") + " – " + RANKS[m.rank] + "</dd><dt>Discord-Rolle</dt><dd>@" + RANKS[m.rank] + "</dd><dt>Telefon</dt><dd>" + m.tel + "</dd><dt>Mitglied seit</dt><dd>" + m.since + "</dd><dt>Status</dt><dd>" + (m.state === "probe" ? "In Probezeit" : "Verifiziert") + "</dd><dt>Wochenabgabe</dt><dd>KW 41 bezahlt</dd><dt>Sanktionen</dt><dd>keine offenen</dd></dl>" +
      '<p style="color:var(--d-muted);margin:0">Im echten Dashboard änderst du hier den Rang. Der Bot tauscht dann automatisch die Discord-Rolle.</p>' +
      '<div class="dm-actions"><button class="dm-btn" data-close>Schließen</button><button class="dm-btn acc" data-act="add">Rang ändern</button></div>';
    drawer.hidden = false;
    var c = drawer.querySelector("[data-close]"); if (c) c.focus();
  }
  drawer.addEventListener("click", function (e) { if (e.target === drawer) drawer.hidden = true; });

  /* ---------- Sneak Peek ---------- */
  var track = document.getElementById("peekTrack");
  if (track) {
    var slides = track.children, count = document.getElementById("peekCount"), dots = document.getElementById("peekDots");
    var idx = 0;
    for (var i = 0; i < slides.length; i++) {
      var d = document.createElement("button"); d.type = "button"; d.setAttribute("aria-label", "Bild " + (i + 1)); d.dataset.i = i; dots.appendChild(d);
    }
    function setIdx(n) {
      idx = Math.max(0, Math.min(slides.length - 1, n));
      count.textContent = String(idx + 1).padStart(2, "0") + " / " + String(slides.length).padStart(2, "0");
      Array.prototype.forEach.call(dots.children, function (b, j) { b.setAttribute("aria-current", j === idx ? "true" : "false"); });
    }
    function scrollTo(n) { track.scrollTo({ left: slides[Math.max(0, Math.min(slides.length - 1, n))].offsetLeft - track.offsetLeft, behavior: "smooth" }); }
    document.getElementById("peekPrev").addEventListener("click", function () { scrollTo(idx - 1); });
    document.getElementById("peekNext").addEventListener("click", function () { scrollTo(idx + 1); });
    dots.addEventListener("click", function (e) { var b = e.target.closest("button"); if (b) scrollTo(+b.dataset.i); });
    var raf = 0;
    track.addEventListener("scroll", function () { cancelAnimationFrame(raf); raf = requestAnimationFrame(function () { setIdx(Math.round(track.scrollLeft / track.clientWidth)); }); });
    track.addEventListener("keydown", function (e) { if (e.key === "ArrowRight") { e.preventDefault(); scrollTo(idx + 1); } if (e.key === "ArrowLeft") { e.preventDefault(); scrollTo(idx - 1); } });
    ["contextmenu", "dragstart"].forEach(function (ev) { track.addEventListener(ev, function (e) { e.preventDefault(); }); });
    setIdx(0);
  }

  ["contextmenu", "copy", "dragstart"].forEach(function (ev) { root.addEventListener(ev, function (e) { if (!e.target.closest("input")) e.preventDefault(); }); });
  render(false);
})();
