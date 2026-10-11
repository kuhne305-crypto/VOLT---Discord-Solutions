/* VOLT – Website-Skript: Navigation, Live-Status, Blitze, Vorschau-Schutz */
(function () {
  "use strict";

  var $ = function (s, r) { return (r || document).querySelector(s); };
  var $$ = function (s, r) { return Array.prototype.slice.call((r || document).querySelectorAll(s)); };
  var reduceMotion = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  /* ---------- Navigation ---------- */
  var menuBtn = $("#menuBtn"), nav = $("#nav");
  if (menuBtn && nav) {
    menuBtn.addEventListener("click", function () {
      var open = nav.classList.toggle("open");
      menuBtn.setAttribute("aria-expanded", open ? "true" : "false");
    });
  }
  $$(".nav-drop").forEach(function (drop) {
    var btn = $("button", drop);
    var desktop = window.matchMedia("(min-width: 961px)");
    function set(open) {
      drop.classList.toggle("open", open);
      btn.setAttribute("aria-expanded", open ? "true" : "false");
    }
    btn.addEventListener("click", function (e) { e.stopPropagation(); set(!drop.classList.contains("open")); });
    drop.addEventListener("mouseenter", function () { if (desktop.matches) set(true); });
    drop.addEventListener("mouseleave", function () { if (desktop.matches) set(false); });
    document.addEventListener("click", function (e) { if (!drop.contains(e.target)) set(false); });
    document.addEventListener("keydown", function (e) { if (e.key === "Escape") { set(false); btn.focus(); } });
  });
  if (nav) {
    nav.addEventListener("click", function (e) {
      var a = e.target.closest && e.target.closest("a");
      if (a && nav.classList.contains("open")) { nav.classList.remove("open"); menuBtn.setAttribute("aria-expanded", "false"); }
    });
  }

  /* ---------- Vorschauen: nicht bedienbar, nicht kopierbar ---------- */
  $$(".preview").forEach(function (p) {
    ["contextmenu", "dragstart", "copy", "selectstart"].forEach(function (ev) {
      p.addEventListener(ev, function (e) { e.preventDefault(); });
    });
  });

  /* ---------- Jahr ---------- */
  $$("[data-year]").forEach(function (el) { el.textContent = new Date().getFullYear(); });

  /* ---------- Live-Status ---------- */
  var nf = function (n, d) {
    if (n === null || n === undefined || isNaN(n)) return "–";
    try { return Number(n).toLocaleString("de-DE", { maximumFractionDigits: d || 0, minimumFractionDigits: d || 0 }); }
    catch (e) { return String(n); }
  };
  function setAll(key, text) { $$('[data-s="' + key + '"]').forEach(function (el) { el.textContent = text; }); }
  function plural(n, one, many) { return n === 1 ? one : many; }
  function pad(n) { return (n < 10 ? "0" : "") + n; }
  function dur(sec) {
    sec = Math.max(0, Math.round(sec || 0));
    var h = Math.floor(sec / 3600), m = Math.floor(sec % 3600 / 60);
    return h ? h + " Std " + pad(m) + " Min" : (m ? m + " Min" : "unter 1 Min");
  }
  function clock(sec) {
    sec = Math.max(0, Math.floor(sec));
    return Math.floor(sec / 3600) + ":" + pad(Math.floor(sec % 3600 / 60)) + ":" + pad(sec % 60);
  }
  var timers = [];
  function tick() {
    timers.forEach(function (t) {
      var sec = t.base + (t.running ? (Date.now() - t.t0) / 1000 : 0);
      t.el.textContent = (t.running ? "⏱ " : "⏸ ") + clock(sec) + (t.running ? " · Uhr läuft" : " · pausiert");
    });
  }
  setInterval(tick, 1000);

  var BOLT = '<svg viewBox="0 0 24 24" aria-hidden="true"><path fill="currentColor" d="M13.6 1.8 3.9 13.6h6.6l-1.3 8.6 10-12.4h-6.8z"/></svg>';
  var DEMO = {
    ok: true, demo: true, updated: null, invite: null,
    discord: { members: 12, online: 4 },
    projects: { running: 3, active: 1, paused: 0, requests: 1, done: 7 },
    workload: { active: 1, capacity: 2, percent: 50, label: "Gut ausgelastet", queue: 1, wait_days: 2, per_day: 1,
      slots: [{ n: 1, busy: true, type: "📺 Streamer-Bot", running: true, seconds: 5040 }, { n: 2, busy: false }] },
    build: { avg_days: null, samples: 0, avg_work_seconds: 11520, work_samples: 4 },
    team: { people: 1 },
    reviews: {
      count: 5, avg: 4.8, label: "Sehr zufrieden", dist: { "5": 4, "4": 1, "3": 0, "2": 0, "1": 0 },
      latest: [
        { stars: 5, text: "Live-Alerts laufen seit Tag eins ohne Probleme. Schnelle Antworten im Ticket.", type: "🤖 Discord-Bot", month: "2026-10" },
        { stars: 5, text: "Server komplett neu aufgebaut, sieht richtig sauber aus.", type: "🖥️ Discord-Server-Setup", month: "2026-09" },
        { stars: 4, text: "Hat einen Tag länger gedauert als gedacht, Ergebnis passt aber.", type: "📦 Bot + Server (Komplettpaket)", month: "2026-09" }
      ]
    }
  };

  function render(d, mode) {
    var conn = $('[data-s="conn"]');
    if (conn) {
      conn.classList.toggle("is-live", mode === "live");
      conn.classList.toggle("is-demo", mode === "demo");
      conn.textContent = mode === "live" ? "Live" : mode === "demo" ? "Beispielwerte" : "Nicht erreichbar";
    }
    $$("[data-demo-note]").forEach(function (el) { el.hidden = mode !== "demo"; });
    if (!d) return;

    var dc = d.discord || {}, pr = d.projects || {}, wl = d.workload || {}, rv = d.reviews || {}, b = d.build || {};
    setAll("online", nf(dc.online));
    setAll("members", nf(dc.members));
    setAll("running", nf(pr.running));
    setAll("active", nf(pr.active));
    setAll("done", nf(pr.done));
    setAll("queue", nf(wl.queue));
    setAll("percent", nf(wl.percent));
    setAll("wl-label", wl.label || "–");
    setAll("capacity", nf(wl.capacity));

    var w = wl.wait_days;
    setAll("wait", w === 0 ? "Sofort" : w ? "~" + nf(w) + " " + plural(w, "Tag", "Tage") : "–");
    setAll("wait-sub", w === 0 ? "Die Werkbank ist frei" : "Start für neue Anfragen");
    if (b.avg_work_seconds) {
      setAll("build", "Ø " + (b.avg_work_seconds >= 3600 ? nf(b.avg_work_seconds / 3600, 1).replace(/,0$/, "") + " Std" : dur(b.avg_work_seconds)));
      setAll("build-sub", "gestoppte Arbeitszeit aus " + nf(b.work_samples) + " " + plural(b.work_samples, "Projekt", "Projekten"));
    } else if (b.avg_days) {
      setAll("build", "Ø " + nf(b.avg_days, 1).replace(/,0$/, "") + " " + plural(b.avg_days, "Tag", "Tage"));
      setAll("build-sub", "aus " + nf(b.samples) + " Projekten");
    } else {
      setAll("build", "~1 Tag");
      setAll("build-sub", "Richtwert pro Projekt");
    }

    var meter = $("[data-meter]");
    if (meter) meter.style.width = Math.max(0, Math.min(100, wl.percent || 0)) + "%";

    var slots = $("#slots");
    if (slots && wl.capacity) {
      slots.textContent = "";
      timers = [];
      var list = wl.slots || [];
      for (var i = 0; i < wl.capacity; i++) {
        var sl = list[i] || { n: i + 1, busy: i < (wl.active || 0) };
        var s = document.createElement("div");
        s.className = "slot" + (sl.busy ? " busy" : "") + (sl.busy && sl.running === false ? " paused" : "");
        s.innerHTML = BOLT;
        var box = document.createElement("span"); box.className = "slot-txt";
        var t = document.createElement("b");
        t.textContent = "Platz " + sl.n + (sl.busy ? " · " + (sl.type || "Projekt in Arbeit") : ": frei");
        box.appendChild(t);
        if (sl.busy && typeof sl.seconds === "number") {
          var c = document.createElement("small");
          box.appendChild(c);
          timers.push({ el: c, base: sl.seconds, running: !!sl.running, t0: Date.now() });
        }
        s.appendChild(box);
        slots.appendChild(s);
      }
      tick();
    }
    var q = $("#queue");
    if (q) {
      q.textContent = "";
      var n = wl.queue || 0;
      if (n > 0) {
        var dots = document.createElement("span"); dots.className = "dots";
        for (var j = 0; j < Math.min(n, 8); j++) dots.appendChild(document.createElement("i"));
        q.appendChild(dots);
      }
      var qt = document.createElement("span");
      qt.textContent = n > 0 ? n + " " + plural(n, "Anfrage wartet", "Anfragen warten") + " in der Warteschlange" : "Keine Warteschlange";
      q.appendChild(qt);
    }

    var avg = rv.avg;
    setAll("rating-avg", avg ? nf(avg, 1) : "–");
    setAll("rating-label", rv.label || "Noch keine Bewertungen");
    setAll("rating-count", rv.count ? "aus " + nf(rv.count) + " " + plural(rv.count, "Bewertung", "Bewertungen") : "noch keine Bewertungen");
    $$('[data-s="rating-stars"]').forEach(function (el) { el.style.setProperty("--fill", (avg ? avg / 5 * 100 : 0) + "%"); });
    var dist = rv.dist || {};
    $$("[data-dist]").forEach(function (row) {
      var k = row.getAttribute("data-dist"), c = dist[k] || 0;
      $(".bar i", row).style.width = (rv.count ? c / rv.count * 100 : 0) + "%";
      $("span:last-child", row).textContent = c;
    });
    var list = $("#revList");
    if (list) {
      list.textContent = "";
      var latest = rv.latest || [];
      if (!latest.length) {
        var empty = document.createElement("p");
        empty.className = "rev-empty";
        empty.textContent = "Noch keine Bewertungen. Die ersten kommen nach abgeschlossenen Projekten direkt aus dem VOLT-Discord.";
        list.appendChild(empty);
      }
      latest.forEach(function (r) {
        var item = document.createElement("article"); item.className = "rev";
        var st = document.createElement("span"); st.className = "stars sm"; st.style.setProperty("--fill", (r.stars / 5 * 100) + "%");
        st.setAttribute("role", "img"); st.setAttribute("aria-label", r.stars + " von 5 Sternen");
        item.appendChild(st);
        if (r.text) { var qq = document.createElement("q"); qq.textContent = r.text; item.appendChild(qq); }
        var meta = document.createElement("div"); meta.className = "rev-meta";
        var m1 = document.createElement("span"); m1.textContent = r.type || "Projekt"; meta.appendChild(m1);
        if (r.month && /^\d{4}-\d{2}$/.test(r.month)) {
          var m2 = document.createElement("span"); var p = r.month.split("-"); m2.textContent = p[1] + "/" + p[0]; meta.appendChild(m2);
        }
        var m3 = document.createElement("span"); m3.textContent = "Verifizierter Kunde"; meta.appendChild(m3);
        item.appendChild(meta);
        list.appendChild(item);
      });
    }

    if (d.updated) {
      var dt = new Date(d.updated);
      if (!isNaN(dt)) setAll("updated", "Stand " + dt.toLocaleTimeString("de-DE", { hour: "2-digit", minute: "2-digit" }) + " Uhr");
    } else if (mode === "demo") {
      setAll("updated", "Beispielwerte, live auf der echten Seite");
    }

    if (typeof d.donate === "string" && /^https:\/\/[^\s"'<>]+$/.test(d.donate)) {
      $$("a[data-donate]").forEach(function (a) { a.href = d.donate; a.hidden = false; });
    }
    if (typeof d.invite === "string" && /^https:\/\/(discord\.gg|discord\.com\/invite)\/[A-Za-z0-9-]+$/.test(d.invite)) {
      $$("a[data-invite]").forEach(function (a) { a.href = d.invite; });
    }
  }

  var needsStats = $$("[data-s]").length > 0;
  function load() {
    fetch("/api/stats", { headers: { "Accept": "application/json" }, cache: "no-store" })
      .then(function (r) { if (!r.ok) throw new Error(r.status); return r.json(); })
      .then(function (d) { if (!d || !d.ok) throw new Error("bad"); render(d, "live"); })
      .catch(function () { if (window.VOLT_DEMO) render(DEMO, "demo"); else render(null, "off"); });
  }
  if (needsStats) {
    if (window.VOLT_DEMO) render(DEMO, "demo");
    load();
    setInterval(function () { if (!document.hidden) load(); }, 60000);
  }

  /* ---------- Gewitter im Hero ---------- */
  function storm(canvas) {
    if (reduceMotion || !canvas.getContext) return;
    var ctx = canvas.getContext("2d"), dpr = Math.min(window.devicePixelRatio || 1, 2);
    var W = 0, H = 0, visible = true, bolts = [], raf = 0, timer = 0;
    function size() {
      var r = canvas.getBoundingClientRect();
      W = r.width; H = r.height;
      canvas.width = Math.round(W * dpr); canvas.height = Math.round(H * dpr);
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    }
    size();
    if (window.ResizeObserver) new ResizeObserver(size).observe(canvas); else window.addEventListener("resize", size);
    if (window.IntersectionObserver) new IntersectionObserver(function (e) { visible = e[0].isIntersecting; }).observe(canvas);

    function path(x0, y0, x1, y1, rough) {
      var pts = [[x0, y0], [x1, y1]], disp = rough;
      for (var k = 0; k < 6; k++) {
        var next = [pts[0]];
        for (var i = 0; i < pts.length - 1; i++) {
          var a = pts[i], b = pts[i + 1];
          next.push([(a[0] + b[0]) / 2 + (Math.random() - .5) * disp, (a[1] + b[1]) / 2 + (Math.random() - .5) * disp * .35]);
          next.push(b);
        }
        pts = next; disp *= .55;
      }
      return pts;
    }
    function strike() {
      if (!visible || document.hidden || W < 10) return schedule();
      var x0 = W * (.08 + Math.random() * .84), y1 = H * (.45 + Math.random() * .45);
      var x1 = x0 + (Math.random() - .5) * W * .3;
      var main = path(x0, -10, x1, y1, Math.min(220, W * .25));
      var parts = [{ pts: main, w: 1 }];
      var nb = 2 + Math.floor(Math.random() * 3);
      for (var i = 0; i < nb; i++) {
        var start = main[Math.floor(main.length * (.2 + Math.random() * .5))];
        var len = H * (.12 + Math.random() * .25), ang = (Math.random() < .5 ? -1 : 1) * (.35 + Math.random() * .6);
        parts.push({ pts: path(start[0], start[1], start[0] + Math.sin(ang) * len, start[1] + Math.cos(ang) * len, 70), w: .5 });
      }
      bolts.push({ parts: parts, t0: performance.now() });
      if (!raf) raf = requestAnimationFrame(frame);
      schedule();
    }
    function schedule() { clearTimeout(timer); timer = setTimeout(strike, 2600 + Math.random() * 4200); }
    function intensity(t) {
      if (t < 70) return 1; if (t < 130) return .25; if (t < 210) return .9; if (t < 260) return .35;
      if (t < 560) return .8 * (1 - (t - 260) / 300); return 0;
    }
    function frame(now) {
      ctx.clearRect(0, 0, W, H);
      ctx.globalCompositeOperation = "lighter";
      bolts = bolts.filter(function (b) { return now - b.t0 < 600; });
      bolts.forEach(function (b) {
        var a = intensity(now - b.t0);
        if (a <= 0) return;
        ctx.fillStyle = "rgba(255,31,42," + (a * .05) + ")";
        ctx.fillRect(0, 0, W, H);
        b.parts.forEach(function (p) {
          ctx.beginPath();
          p.pts.forEach(function (pt, i) { i ? ctx.lineTo(pt[0], pt[1]) : ctx.moveTo(pt[0], pt[1]); });
          ctx.lineJoin = "round"; ctx.lineCap = "round";
          ctx.shadowColor = "rgba(255,31,42,1)"; ctx.shadowBlur = 26 * p.w;
          ctx.strokeStyle = "rgba(255,31,42," + (a * .7 * p.w) + ")"; ctx.lineWidth = 6 * p.w; ctx.stroke();
          ctx.shadowBlur = 8;
          ctx.strokeStyle = "rgba(255,236,236," + (a * (p.w > .6 ? 1 : .7)) + ")"; ctx.lineWidth = 1.7 * p.w + .4; ctx.stroke();
        });
      });
      ctx.globalCompositeOperation = "source-over";
      raf = bolts.length ? requestAnimationFrame(frame) : 0;
      if (!raf) ctx.clearRect(0, 0, W, H);
    }
    setTimeout(strike, 900);
  }
  $$("canvas.storm").forEach(storm);
})();
