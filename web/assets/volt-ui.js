/* VOLT UI – Overlay, Bestätigungs-Dialog und Bildansicht für alle VOLT-Oberflächen.
   In jedem Projekt GLEICH (gehört zu volt-ui.css).

   VOLT.confirm({title, text, ok, cancel, danger, icon}) -> Promise<boolean>
   VOLT.dialog({title, html, icon, wide, buttons:[{label, primary, danger, value}]}) -> Promise<value|null>
   VOLT.image(src, alt)                       -> Bild groß im Overlay
   Automatisch: Knöpfe/Links mit data-vu-confirm="Text" fragen vorher nach,
                Bilder in [data-vu-zoom] öffnen sich beim Klick groß.
   Icon-Sprite: <html data-vu-icons="/pfad/volt-icons.svg"> (sonst /assets/icons/volt-icons.svg) */
(function () {
  "use strict";
  var V = window.VOLT = window.VOLT || {};
  var SPRITE = document.documentElement.getAttribute("data-vu-icons") || "/assets/icons/volt-icons.svg";
  var lang = (document.documentElement.lang || "de").slice(0, 2);
  var TXT = lang === "en" ? { ok: "OK", cancel: "Cancel", close: "Close", sure: "Are you sure?" }
                          : { ok: "OK", cancel: "Abbrechen", close: "Schließen", sure: "Bist du sicher?" };

  function icon(name, cls) {
    return '<svg class="vi' + (cls ? " " + cls : "") + '" aria-hidden="true"><use href="' + SPRITE + "#vi-" + name + '"/></svg>';
  }
  V.icon = icon;
  function esc(s) { return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) { return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]; }); }

  var X = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M6 6L18 18M18 6L6 18" fill="none" stroke="currentColor" stroke-width="2.2"/></svg>';
  var open = null;
  function close(value) {
    if (!open) return;
    var o = open; open = null;
    o.el.remove();
    document.documentElement.classList.remove("vu-lock");
    document.removeEventListener("keydown", o.key, true);
    if (o.back && o.back.focus) { try { o.back.focus({ preventScroll: true }); } catch (e) { o.back.focus(); } }
    o.resolve(value);
  }

  V.dialog = function (opt) {
    opt = opt || {};
    if (open) close(null);
    return new Promise(function (resolve) {
      var ov = document.createElement("div");
      ov.className = "overlay";
      var id = "vu-t-" + Date.now();
      var btns = (opt.buttons || []).map(function (b, i) {
        var cls = b.primary ? "vu-btn primary" : b.danger ? "vu-btn danger" : "vu-btn";
        return '<button type="button" class="' + cls + '" data-i="' + i + '">' + esc(b.label) + "</button>";
      }).join("");
      ov.innerHTML =
        '<div class="modal' + (opt.wide ? " wide" : "") + (opt.media ? " media" : "") + '" role="dialog" aria-modal="true" aria-labelledby="' + id + '">' +
          '<div class="modal-head">' + (opt.icon ? icon(opt.icon) : "") + '<h3 id="' + id + '">' + esc(opt.title || "") + "</h3>" +
            '<button type="button" class="modal-x" aria-label="' + TXT.close + '">' + X + "</button></div>" +
          (opt.html != null ? '<div class="' + (opt.media ? "modal-media" : "modal-body") + '">' + opt.html + "</div>" : "") +
          (btns ? '<div class="modal-foot">' + btns + "</div>" : "") +
        "</div>";
      var back = document.activeElement;
      function key(e) {
        if (e.key === "Escape") { e.preventDefault(); close(null); return; }
        if (e.key === "Tab") {  // Fokus im Dialog halten
          var f = ov.querySelectorAll("button,[href],input,select,textarea");
          if (!f.length) return;
          var first = f[0], last = f[f.length - 1];
          if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
          else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
        }
      }
      open = { el: ov, resolve: resolve, key: key, back: back };
      ov.addEventListener("mousedown", function (e) { if (e.target === ov) close(null); });
      ov.querySelector(".modal-x").addEventListener("click", function () { close(null); });
      Array.prototype.forEach.call(ov.querySelectorAll("[data-i]"), function (b) {
        b.addEventListener("click", function () { var d = opt.buttons[+b.getAttribute("data-i")]; close(d.value === undefined ? true : d.value); });
      });
      document.addEventListener("keydown", key, true);
      document.documentElement.classList.add("vu-lock");
      document.body.appendChild(ov);
      var focus = ov.querySelector(".modal-foot .primary,.modal-foot .danger") || ov.querySelector(".modal-x");
      focus.focus();
    });
  };

  V.confirm = function (opt) {
    if (typeof opt === "string") opt = { text: opt };
    opt = opt || {};
    return V.dialog({
      title: opt.title || TXT.sure,
      icon: opt.icon || (opt.danger ? "warnung" : "volt"),
      html: "<p>" + esc(opt.text || "") + "</p>",
      buttons: [{ label: opt.cancel || TXT.cancel, value: false },
                { label: opt.ok || TXT.ok, value: true, primary: !opt.danger, danger: !!opt.danger }]
    }).then(function (v) { return v === true; });
  };

  V.image = function (src, alt) {
    return V.dialog({ title: alt || "", icon: "portfolio", media: true,
      html: '<img src="' + esc(src) + '" alt="' + esc(alt || "") + '" draggable="false">' });
  };

  // data-vu-confirm: vor dem Klick nachfragen (Links und Knöpfe)
  document.addEventListener("click", function (e) {
    var t = e.target.closest && e.target.closest("[data-vu-confirm]");
    if (!t || t.__vuOk) return;
    e.preventDefault(); e.stopImmediatePropagation();
    V.confirm({ text: t.getAttribute("data-vu-confirm"), danger: t.hasAttribute("data-vu-danger") }).then(function (ok) {
      if (!ok) return;
      t.__vuOk = true; t.click(); t.__vuOk = false;
    });
  }, true);

  // data-vu-zoom: Bilder groß ansehen
  document.addEventListener("click", function (e) {
    var box = e.target.closest && e.target.closest("[data-vu-zoom]");
    if (!box) return;
    var img = box.tagName === "IMG" ? box : box.querySelector("img");
    if (!img) return;
    e.preventDefault();
    V.image(box.getAttribute("data-vu-zoom") || img.currentSrc || img.src, img.alt);
  });
})();
