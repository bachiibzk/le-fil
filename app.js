(function () {
  "use strict";

  // ---------------------------------------------------------------- réglages (par téléphone)
  var DEFAULTS = { watch: "bitcoin,ethereum,solana,dogecoin,pepe,pudgy-penguins", filter: "tout", theme: "auto", notify: false, minImp: 1 };
  var S = Object.assign({}, DEFAULTS);
  try { Object.assign(S, JSON.parse(localStorage.getItem("fil-settings") || "{}")); } catch (e) {}
  function save() { try { localStorage.setItem("fil-settings", JSON.stringify(S)); } catch (e) {} }
  function applyTheme() { if (S.theme === "auto") document.documentElement.removeAttribute("data-theme"); else document.documentElement.setAttribute("data-theme", S.theme); }
  applyTheme();

  var CG = "https://api.coingecko.com/api/v3";
  var FEED_URL = "data/feed.json";
  var POLL_MS = 60000;

  var posts = [];
  var knownIds = null;
  var pending = [];
  var memeRows = [];
  var memeSort = { key: "market_cap", dir: -1 };
  var lastFeedOk = null;

  // ---------------------------------------------------------------- helpers
  function h(tag, attrs) {
    var el = document.createElement(tag);
    if (attrs) for (var k in attrs) {
      if (k === "text") el.textContent = attrs[k];
      else if (k === "cls") el.className = attrs[k];
      else el.setAttribute(k, attrs[k]);
    }
    for (var i = 2; i < arguments.length; i++) { var c = arguments[i]; if (c == null || c === false) continue; el.appendChild(typeof c === "string" ? document.createTextNode(c) : c); }
    return el;
  }
  function safeUrl(u) { u = String(u || ""); return /^https:\/\//.test(u) || /^[\w.-]+\.html$/.test(u) ? u : null; }
  function num(x, d) { return x == null || isNaN(x) ? "n.d." : Number(x).toLocaleString("fr-FR", { minimumFractionDigits: d, maximumFractionDigits: d }); }
  function price(x) {
    if (x == null) return "n.d.";
    if (x >= 1000) return num(x, 0) + " $";
    if (x >= 1) return num(x, 2) + " $";
    return Number(x).toLocaleString("fr-FR", { maximumSignificantDigits: 4 }) + " $";
  }
  function big(x) { if (!x) return "n.d."; if (x >= 1e9) return num(x / 1e9, 2) + " Md$"; if (x >= 1e6) return num(x / 1e6, 1) + " M$"; return num(x / 1e3, 0) + " k$"; }
  function pct(x) { if (x == null || isNaN(x)) return { t: "n.d.", c: "flat" }; return { t: (x >= 0 ? "+" : "−") + num(Math.abs(x), 2) + " %", c: x > 0 ? "up" : x < 0 ? "down" : "flat" }; }
  function ago(iso) {
    var t = Date.parse(iso); if (isNaN(t)) return "";
    var s = Math.max(0, (Date.now() - t) / 1000);
    if (s < 60) return "à l'instant";
    if (s < 3600) return Math.floor(s / 60) + " min";
    if (s < 86400) return Math.floor(s / 3600) + " h";
    return new Date(t).toLocaleDateString("fr-FR", { day: "numeric", month: "short", timeZone: "Europe/Paris" });
  }
  function hhmm(d) { return d.toLocaleTimeString("fr-FR", { hour: "2-digit", minute: "2-digit", timeZone: "Europe/Paris" }).replace(":", "h"); }
  function getJSON(url) { return fetch(url, { cache: "no-store" }).then(function (r) { if (!r.ok) throw new Error(r.status); return r.json(); }); }
  function tab() { var t = (location.hash || "#fil").slice(1); return ["fil", "marches", "reglages"].indexOf(t) >= 0 ? t : "fil"; }
  function setStatus(text, live) { document.getElementById("status").textContent = text; document.getElementById("dot").className = "dot" + (live ? " live" : ""); }

  // ---------------------------------------------------------------- bandeau de prix
  function loadTicker() {
    var ids = S.watch.split(",").map(function (s) { return s.trim(); }).filter(Boolean).slice(0, 15);
    if (!ids.length) { document.getElementById("ticker").replaceChildren(); return Promise.resolve(); }
    return getJSON(CG + "/coins/markets?vs_currency=usd&ids=" + encodeURIComponent(ids.join(",")) + "&price_change_percentage=24h")
      .then(function (rows) {
        rows.sort(function (a, b) { return ids.indexOf(a.id) - ids.indexOf(b.id); });
        document.getElementById("ticker").replaceChildren.apply(document.getElementById("ticker"), rows.map(function (r) {
          var p = pct(r.price_change_percentage_24h);
          return h("a", { cls: "tick", href: "https://www.coingecko.com/en/coins/" + encodeURIComponent(r.id), target: "_blank", rel: "noopener", style: "text-decoration:none;color:inherit" },
            h("span", { cls: "sym", text: String(r.symbol || "").toUpperCase() }), h("span", { text: price(r.current_price) }), h("span", { cls: p.c, text: p.t }));
        }));
      }).catch(function () {});
  }

  // ---------------------------------------------------------------- fil
  var FILTERS = [["tout", "Tout"], ["important", "🔴 Important"], ["meme", "🐸 Memes"], ["market", "📈 Marchés"], ["news", "📰 News"], ["trend", "🔥 Tendances"], ["journal", "🗞️ Journal"]];
  function matches(p) {
    if ((p.importance || 1) < S.minImp) return false;
    switch (S.filter) {
      case "important": return p.importance >= 3;
      case "news": return ["news", "tech", "finance"].indexOf(p.kind) >= 0;
      case "tout": return true;
      default: return p.kind === S.filter;
    }
  }
  function postEl(p, fresh) {
    var foot = h("div", { cls: "post-foot" });
    if (p.importance >= 3) foot.appendChild(h("span", { cls: "chip hot", text: "Important" }));
    (p.tickers || []).forEach(function (t) { foot.appendChild(h("span", { cls: "chip tk", text: "$" + t })); });
    (p.sources || []).forEach(function (s) { var u = safeUrl(s.url); if (u) foot.appendChild(h("a", { cls: "chip", href: u, target: /^https/.test(u) ? "_blank" : "_self", rel: "noopener", text: s.label || "Source" })); });
    return h("article", { cls: "post" + (fresh ? " fresh" : "") },
      h("div", { cls: "avatar", "aria-hidden": "true", text: p.emoji || "📰" }),
      h("div", null,
        h("div", { cls: "post-head" }, h("b", { text: "Claude" }), h("span", { cls: "meta", text: "@lefil · " + ago(p.ts) })),
        h("p", { cls: "post-text", text: p.text || "" }),
        foot));
  }
  function renderFeed(freshIds) {
    var app = document.getElementById("app");
    var bar = h("div", { cls: "filters", role: "toolbar", "aria-label": "Filtrer le fil" });
    FILTERS.forEach(function (f) {
      var b = h("button", { type: "button", "aria-pressed": String(S.filter === f[0]), text: f[1] });
      b.addEventListener("click", function () { S.filter = f[0]; save(); renderFeed(); });
      bar.appendChild(b);
    });
    var list = posts.filter(matches);
    var body;
    if (!posts.length) body = h("div", { cls: "empty" }, h("h2", { text: "Pas encore de post" }), h("p", { text: "Le bot publie dès qu'une info nouvelle et pertinente tombe. Revenez dans quelques minutes." }));
    else if (!list.length) body = h("div", { cls: "empty" }, h("h2", { text: "Rien dans ce filtre" }), h("p", { text: "Essayez « Tout »." }));
    else {
      body = h("div", { cls: "feed" });
      list.slice(0, 150).forEach(function (p) { body.appendChild(postEl(p, freshIds && freshIds[p.id])); });
    }
    app.replaceChildren(bar, body);
  }

  function notify(p) {
    if (!S.notify || !("Notification" in window) || Notification.permission !== "granted") return;
    if (!document.hidden) return;
    try {
      if (navigator.serviceWorker && navigator.serviceWorker.controller) navigator.serviceWorker.ready.then(function (reg) { reg.showNotification((p.emoji || "") + " Le Fil", { body: p.text, icon: "icons/icon-192.png", tag: p.id }); });
      else new Notification((p.emoji || "") + " Le Fil", { body: p.text, icon: "icons/icon-192.png" });
    } catch (e) {}
  }

  function loadFeed(manual) {
    return getJSON(FEED_URL + "?t=" + Date.now()).then(function (data) {
      var incoming = Array.isArray(data.posts) ? data.posts : [];
      incoming.sort(function (a, b) { return Date.parse(b.ts) - Date.parse(a.ts); });
      lastFeedOk = new Date();
      var last = incoming[0] ? ago(incoming[0].ts) : "";
      setStatus("En direct · " + hhmm(lastFeedOk) + (last ? " · dernier post " + last : ""), true);
      if (knownIds === null) { knownIds = {}; incoming.forEach(function (p) { knownIds[p.id] = 1; }); posts = incoming; if (tab() === "fil") renderFeed(); return; }
      var news = incoming.filter(function (p) { return !knownIds[p.id]; });
      news.forEach(function (p) { knownIds[p.id] = 1; if (p.importance >= 3) notify(p); });
      if (!news.length) { posts = incoming; if (tab() === "fil" && manual) renderFeed(); return; }
      if (tab() === "fil" && window.scrollY > 200 && !manual) {
        pending = incoming;
        var pill = document.getElementById("new-pill");
        pill.textContent = "↑ " + news.length + " nouveau" + (news.length > 1 ? "x posts" : " post");
        pill.hidden = false;
      } else {
        posts = incoming;
        var fresh = {}; news.forEach(function (p) { fresh[p.id] = 1; });
        if (tab() === "fil") renderFeed(fresh);
      }
    }).catch(function () { setStatus(lastFeedOk ? "Hors ligne · dernière mise à jour " + hhmm(lastFeedOk) : "Hors ligne", false); if (knownIds === null && tab() === "fil") renderFeed(); });
  }
  document.getElementById("new-pill").addEventListener("click", function () {
    this.hidden = true; posts = pending.length ? pending : posts; pending = []; window.scrollTo({ top: 0, behavior: "smooth" }); renderFeed();
  });

  // ---------------------------------------------------------------- marchés
  function loadMemes() {
    return getJSON(CG + "/coins/markets?vs_currency=usd&category=meme-token&order=market_cap_desc&per_page=60&page=1&price_change_percentage=1h,24h,7d")
      .then(function (rows) { memeRows = rows || []; if (tab() === "marches") renderMarkets(); })
      .catch(function () { if (tab() === "marches") renderMarkets(true); });
  }
  function renderMarkets(err) {
    var app = document.getElementById("app");
    var cols = [["#", "market_cap_rank", false], ["Meme coin", "name", false], ["Prix", "current_price", true], ["1 h", "price_change_percentage_1h_in_currency", true], ["24 h", "price_change_percentage_24h", true], ["7 j", "price_change_percentage_7d_in_currency", true], ["MC", "market_cap", true], ["Vol. 24 h", "total_volume", true]];
    var rows = memeRows.slice().sort(function (a, b) {
      var x = a[memeSort.key], y = b[memeSort.key];
      if (typeof x === "string") return memeSort.dir * x.localeCompare(y);
      return memeSort.dir * ((x == null ? -Infinity : x) - (y == null ? -Infinity : y));
    });
    var thead = h("tr");
    cols.forEach(function (c) {
      var th = h("th", { cls: c[2] ? "num" : "", scope: "col", text: c[0] + (memeSort.key === c[1] ? (memeSort.dir < 0 ? " ↓" : " ↑") : "") });
      th.addEventListener("click", function () { memeSort = { key: c[1], dir: memeSort.key === c[1] ? -memeSort.dir : -1 }; renderMarkets(); });
      thead.appendChild(th);
    });
    var tbody = h("tbody");
    rows.forEach(function (r, i) {
      var tr = h("tr");
      tr.appendChild(h("td", { cls: "num", text: String(i + 1) }));
      tr.appendChild(h("td", null, h("a", { href: "https://www.coingecko.com/en/coins/" + encodeURIComponent(r.id), target: "_blank", rel: "noopener" }, r.name, h("span", { cls: "tkr", text: String(r.symbol || "").toUpperCase() }))));
      tr.appendChild(h("td", { cls: "num", text: price(r.current_price) }));
      ["price_change_percentage_1h_in_currency", "price_change_percentage_24h", "price_change_percentage_7d_in_currency"].forEach(function (k) { var p = pct(r[k]); tr.appendChild(h("td", { cls: "num " + p.c, text: p.t })); });
      tr.appendChild(h("td", { cls: "num", text: big(r.market_cap) }));
      tr.appendChild(h("td", { cls: "num", text: big(r.total_volume) }));
      tbody.appendChild(tr);
    });
    app.replaceChildren(
      h("div", { cls: "section-title" }, "Meme coins en direct", h("small", { text: memeRows.length ? "CoinGecko · " + hhmm(new Date()) : "" })),
      err && !memeRows.length ? h("div", { cls: "empty" }, h("p", { text: "CoinGecko ne répond pas (limite de requêtes ?). Nouvel essai dans une minute." })) :
        h("div", { cls: "table-wrap" }, h("table", null, h("thead", null, thead), tbody)),
      h("p", { cls: "note", text: "Touchez un en-tête pour trier. Rafraîchi chaque minute pendant que l'onglet est ouvert. Données publiques CoinGecko, pas un conseil d'investissement." }));
  }

  // ---------------------------------------------------------------- réglages
  function renderSettings() {
    var app = document.getElementById("app");
    var watch = h("input", { type: "text", value: S.watch, "aria-label": "Identifiants CoinGecko", autocapitalize: "off", autocomplete: "off", spellcheck: "false" });
    var saveW = h("button", { cls: "btn primary", type: "button", text: "Enregistrer" });
    saveW.addEventListener("click", function () { S.watch = watch.value.toLowerCase().replace(/\s+/g, ""); save(); loadTicker(); saveW.textContent = "Enregistré ✓"; setTimeout(function () { saveW.textContent = "Enregistrer"; }, 1500); });

    var theme = h("select", { "aria-label": "Thème" });
    [["auto", "Automatique"], ["light", "Clair"], ["dark", "Sombre"]].forEach(function (o) { var op = h("option", { value: o[0], text: o[1] }); if (S.theme === o[0]) op.selected = true; theme.appendChild(op); });
    theme.addEventListener("change", function () { S.theme = theme.value; save(); applyTheme(); });

    var imp = h("select", { "aria-label": "Importance minimale" });
    [[1, "Tous les posts"], [2, "Notables et importants"], [3, "Importants seulement"]].forEach(function (o) { var op = h("option", { value: String(o[0]), text: o[1] }); if (S.minImp === o[0]) op.selected = true; imp.appendChild(op); });
    imp.addEventListener("change", function () { S.minImp = Number(imp.value); save(); });

    var notif = h("button", { cls: "btn", type: "button", text: S.notify ? "Notifications activées ✓" : "Activer les notifications" });
    notif.addEventListener("click", function () {
      if (!("Notification" in window)) { notif.textContent = "Non disponible sur ce navigateur"; return; }
      Notification.requestPermission().then(function (p) { S.notify = p === "granted"; save(); notif.textContent = S.notify ? "Notifications activées ✓" : "Refusées dans le navigateur"; });
    });

    app.replaceChildren(
      h("div", { cls: "card" }, h("h2", { text: "Bandeau de prix" }),
        h("p", { cls: "small", text: "Identifiants CoinGecko séparés par des virgules (le nom dans l'URL de la fiche, ex. coingecko.com/en/coins/pudgy-penguins → pudgy-penguins)." }),
        watch, saveW),
      h("div", { cls: "card" }, h("h2", { text: "Fil" }), h("label", { cls: "row" }, "Afficher", imp)),
      h("div", { cls: "card" }, h("h2", { text: "Notifications" }),
        h("p", { cls: "small", text: "Alertes pour les posts importants quand l'app est ouverte en arrière-plan. Pour des alertes même app fermée (iPhone compris), installez l'app gratuite ntfy et abonnez-vous au sujet configuré dans le dépôt (voir README)." }),
        notif),
      h("div", { cls: "card" }, h("h2", { text: "Apparence" }), h("label", { cls: "row" }, "Thème", theme)),
      h("div", { cls: "card" }, h("h2", { text: "Installer sur ce téléphone" }),
        h("p", { cls: "small", text: "iPhone : Safari → bouton Partager → « Sur l'écran d'accueil ». Android : Chrome → menu ⋮ → « Installer l'application »." })));
  }

  // ---------------------------------------------------------------- navigation
  var marketsTimer = null;
  function route() {
    var t = tab();
    document.querySelectorAll("nav.tabs a[data-tab]").forEach(function (a) { if (a.dataset.tab === t) a.setAttribute("aria-current", "page"); else a.removeAttribute("aria-current"); });
    document.getElementById("view-title").textContent = t === "marches" ? "Marchés" : t === "reglages" ? "Réglages" : "Le Fil";
    document.getElementById("new-pill").hidden = true;
    clearInterval(marketsTimer);
    if (t === "fil") renderFeed();
    else if (t === "marches") { renderMarkets(); loadMemes(); marketsTimer = setInterval(loadMemes, POLL_MS); }
    else renderSettings();
    window.scrollTo(0, 0);
  }
  window.addEventListener("hashchange", route);
  document.getElementById("refresh").addEventListener("click", function () { loadFeed(true); loadTicker(); if (tab() === "marches") loadMemes(); });
  document.addEventListener("visibilitychange", function () { if (!document.hidden) { loadFeed(); loadTicker(); } });

  route();
  loadFeed();
  loadTicker();
  setInterval(loadFeed, POLL_MS);
  setInterval(loadTicker, POLL_MS);

  if ("serviceWorker" in navigator) navigator.serviceWorker.register("sw.js").catch(function () {});
})();
