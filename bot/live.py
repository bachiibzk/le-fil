"""Bot du fil en direct.

À chaque passage (toutes les 10 min via GitHub Actions) :
1. collecte gratuite : flux RSS, prix CoinGecko, meme coins CoinGecko + CoinMarketCap, trending CoinGecko ;
2. ne garde que le NOUVEAU (déjà vu → ignoré) et le PERTINENT (mots-clés, seuils de mouvement) ;
3. s'il reste quelque chose, demande à Claude de juger et de rédiger 0 à N posts en français ;
4. n'accepte que des posts dont chaque source vient des données collectées (pas d'invention) ;
5. ajoute les posts à data/feed.json et notifie les plus importants (ntfy, optionnel).

Sans candidat, aucun appel à l'API Anthropic : le coût est nul.
"""
from __future__ import annotations

import calendar
import datetime as dt
import hashlib
import json
import os
import re
import time

import feedparser

from common import (BOT, DATA, app_url, ask_claude, extract_json, fr_pct, fr_usd, get_json, log, now_paris,
                    push_ntfy, read_json, write_json)

CFG = read_json(BOT / "sources.json", {})
LIMITS = CFG.get("limits", {})
FEED_PATH = DATA / "feed.json"
STATE_PATH = DATA / "state.json"
MODEL = os.environ.get("LIVE_MODEL") or "claude-haiku-4-5"
DRY_RUN = os.environ.get("DRY_RUN") == "1"

CMC_MEMES = ("https://api.coinmarketcap.com/data-api/v3/cryptocurrency/listing?start=1&limit=150&sortBy=market_cap"
             "&sortType=desc&convert=USD&cryptoType=all&tagType=all&tagSlugs=memes&audited=false")
CG_MEMES = ("https://api.coingecko.com/api/v3/coins/markets?vs_currency=usd&category=meme-token&order=market_cap_desc"
            "&per_page=150&page=1&price_change_percentage=1h,24h")


def hid(*parts: str) -> str:
    return hashlib.sha1("|".join(parts).encode("utf-8")).hexdigest()[:16]


# ---------------------------------------------------------------- collecte

def collect_news(state: dict) -> list[dict]:
    kw = [k.lower() for k in CFG.get("keywords", {}).get("list", [])]
    always = set(CFG.get("always_pass_labels", []))
    max_age = LIMITS.get("news_max_age_hours", 3) * 3600
    seen = state.setdefault("seen", {})
    out = []
    for src in CFG.get("rss", []):
        try:
            feed = feedparser.parse(src["url"], agent="journal-du-matin-bot/1.0")
        except Exception as exc:  # noqa: BLE001
            log(f"[rss KO] {src['label']} : {exc}")
            continue
        if feed.bozo and not feed.entries:
            log(f"[rss KO] {src['label']} : {getattr(feed, 'bozo_exception', '')}")
            continue
        for e in feed.entries[:40]:
            link = (e.get("link") or "").strip()
            title = (e.get("title") or "").strip()
            if not link.startswith("https://") or not title:
                continue
            key = hid(link)
            if key in seen:
                continue
            ts = e.get("published_parsed") or e.get("updated_parsed")
            published = calendar.timegm(ts) if ts else None
            seen[key] = int(time.time())  # vu, même s'il n'est pas retenu
            if published and time.time() - published > max_age:
                continue
            summary = " ".join(re.sub(r"<[^>]+>", " ", e.get("summary") or "").split())[:500]
            text = f"{title} {summary}".lower()
            if src["kind"] != "trend" and src["label"] not in always and not any(k in text for k in kw):
                continue
            out.append({
                "id": key, "type": "trend" if src["kind"] == "trend" else "news", "category": src["kind"],
                "source": src["label"], "title": title, "summary": summary, "url": link,
                "published_utc": dt.datetime.fromtimestamp(published, dt.timezone.utc).isoformat() if published else None,
            })
    return out


def collect_markets(state: dict) -> list[dict]:
    coins = CFG.get("markets", {}).get("coins", {})
    if not coins:
        return []
    ids = ",".join(coins)
    data = get_json(f"https://api.coingecko.com/api/v3/simple/price?ids={ids}&vs_currencies=usd&include_24hr_change=true")
    if not data:
        return []
    last = state.setdefault("last_market_alert", {})
    out = []
    for cid, threshold in coins.items():
        d = data.get(cid) or {}
        price = d.get("usd")
        if not price:
            continue
        ref = last.get(cid)
        if ref is None:
            last[cid] = price  # première mesure : référence, pas d'alerte
            continue
        move = (price / ref - 1) * 100
        if abs(move) >= threshold:
            out.append({
                "id": hid("mkt", cid, str(round(price, 6))), "type": "market", "coin": cid,
                "price_usd": price, "price_fr": fr_usd(price), "move_since_last_alert": fr_pct(move),
                "change_24h": fr_pct(d.get("usd_24h_change")),
                "url": f"https://www.coingecko.com/en/coins/{cid}", "source": "CoinGecko",
            })
            last[cid] = price
    return out


def collect_memes(state: dict) -> list[dict]:
    mcfg = CFG.get("memes", {})
    min_mcap = mcfg.get("min_mcap_usd", 1e7)
    alert = mcfg.get("move_alert_pct", 20)
    cooldown = mcfg.get("cooldown_hours", 6) * 3600
    cg = get_json(CG_MEMES) or []
    cmc_raw = get_json(CMC_MEMES + f"&t={int(time.time())}") or {}
    cmc = {}
    for c in (cmc_raw.get("data", {}) or {}).get("cryptoCurrencyList", []) or []:
        q = next((x for x in c.get("quotes", []) if x.get("name") == "USD"), None)
        if q:
            cmc[c.get("symbol", "").upper()] = {"change_24h": q.get("percentChange24h"), "mcap": q.get("marketCap"),
                                                "slug": c.get("slug")}
    cooldowns = state.setdefault("meme_cooldown", {})
    top_prev = set(state.get("meme_top20", []))
    out = []
    top_now = []
    for i, c in enumerate(cg):
        sym = (c.get("symbol") or "").upper()
        mcap = c.get("market_cap") or 0
        ch = c.get("price_change_percentage_24h")
        if i < 20:
            top_now.append(c["id"])
        if mcap < min_mcap or ch is None:
            continue
        other = cmc.get(sym)
        # Fiabilité : on écarte si CMC donne un signe opposé (données contradictoires).
        if other and other.get("change_24h") is not None and (other["change_24h"] >= 0) != (ch >= 0):
            continue
        reason = None
        if abs(ch) >= alert:
            reason = f"variation 24 h de {fr_pct(ch)}"
        elif i < 20 and top_prev and c["id"] not in top_prev:
            reason = "entre dans le top 20 des meme coins par capitalisation"
        if not reason:
            continue
        if time.time() - cooldowns.get(c["id"], 0) < cooldown:
            continue
        cooldowns[c["id"]] = int(time.time())
        out.append({
            "id": hid("meme", c["id"], now_paris().strftime("%Y%m%d%H")), "type": "meme", "trigger": reason,
            "name": c.get("name"), "ticker": sym, "price": fr_usd(c.get("current_price")), "mcap": fr_usd(mcap),
            "change_24h": fr_pct(ch), "change_1h": fr_pct(c.get("price_change_percentage_1h_in_currency")),
            "volume_24h": fr_usd(c.get("total_volume")), "rank_in_memes": i + 1,
            "cmc_change_24h": fr_pct(other["change_24h"]) if other else "n.d. (absent de CMC)",
            "cmc_mcap": fr_usd(other["mcap"]) if other else "n.d.",
            "url": f"https://www.coingecko.com/en/coins/{c['id']}", "source": "CoinGecko",
        })
    if top_now:
        state["meme_top20"] = top_now
    # Trending CoinGecko : nouveaux entrants seulement
    tr = get_json("https://api.coingecko.com/api/v3/search/trending") or {}
    prev_tr = set(state.get("trending", []))
    now_tr = []
    for it in (tr.get("coins") or [])[:15]:
        item = it.get("item", {})
        cid = item.get("id")
        if not cid:
            continue
        now_tr.append(cid)
        if prev_tr and cid not in prev_tr:
            d = item.get("data", {}) or {}
            ch = (d.get("price_change_percentage_24h") or {}).get("usd")
            out.append({
                "id": hid("trend", cid, now_paris().strftime("%Y%m%d")), "type": "trending",
                "name": item.get("name"), "ticker": (item.get("symbol") or "").upper(),
                "mcap": d.get("market_cap") or "n.d.", "change_24h": fr_pct(ch),
                "trending_rank": item.get("score", 0) + 1,
                "url": f"https://www.coingecko.com/en/coins/{cid}", "source": "CoinGecko (trending)",
            })
    if now_tr:
        state["trending"] = now_tr
    return out


# ---------------------------------------------------------------- rédaction

def write_posts(candidates: list[dict], recent: list[dict]) -> list[dict]:
    system = (BOT / "prompts" / "live.md").read_text(encoding="utf-8")
    payload = {
        "maintenant_paris": now_paris().isoformat(),
        "candidats": candidates,
        "derniers_posts": [{"ts": p["ts"], "text": p["text"]} for p in recent[:15]],
    }
    raw = ask_claude(system, json.dumps(payload, ensure_ascii=False), MODEL, max_tokens=3000)
    data = extract_json(raw)
    allowed = {c["url"]: c for c in candidates}
    by_id = {c["id"]: c for c in candidates}
    posts = []
    for p in data.get("posts", []):
        text = str(p.get("text", "")).strip()
        ids = [i for i in p.get("candidate_ids", []) if i in by_id]
        if not text or not ids or len(text) > 600:
            continue
        sources = [{"label": by_id[i]["source"], "url": by_id[i]["url"]} for i in ids if by_id[i]["url"] in allowed]
        if not sources:
            continue
        kind = p.get("kind") if p.get("kind") in {"news", "meme", "market", "trend", "tech", "finance"} else "news"
        posts.append({
            "id": hid("post", text),
            "ts": now_paris().isoformat(),
            "kind": kind,
            "emoji": str(p.get("emoji", "📰"))[:4],
            "text": text,
            "tickers": [str(t).upper()[:12] for t in p.get("tickers", [])][:5],
            "importance": max(1, min(3, int(p.get("importance", 1) or 1))),
            "sources": sources,
        })
    return posts


def main():
    state = read_json(STATE_PATH, {})
    feed = read_json(FEED_PATH, {"posts": []})
    first_run = not state.get("initialized")

    candidates = collect_news(state) + collect_markets(state) + collect_memes(state)
    # purge des identifiants vus de plus de 7 jours
    week = time.time() - 7 * 86400
    state["seen"] = {k: v for k, v in state.get("seen", {}).items() if v > week}
    state["last_run"] = now_paris().isoformat()

    if first_run and (state.get("seen") or state.get("last_market_alert")):
        state["initialized"] = True  # au moins une source a répondu : les prochains passages publient
    if first_run:
        state["meme_cooldown"] = {}  # rien n'a été publié : pas de délai de carence
        log(f"Premier passage : {len(candidates)} éléments mémorisés comme références, rien n'est publié.")
        candidates = []
    candidates = candidates[: LIMITS.get("max_candidates_per_run", 25)]
    log(f"{len(candidates)} candidat(s) nouveau(x) et pertinent(s).")

    posts = []
    if candidates and not DRY_RUN:
        try:
            posts = write_posts(candidates, feed.get("posts", []))
        except Exception as exc:  # noqa: BLE001
            log(f"[claude KO] {exc}")
    elif candidates:
        log("DRY_RUN=1 : candidats non envoyés à Claude :")
        for c in candidates:
            log(" -", c["type"], c.get("title") or c.get("name"), c["url"])

    if posts:
        known = {p["id"] for p in feed.get("posts", [])}
        posts = [p for p in posts if p["id"] not in known]
        feed["posts"] = (posts + feed.get("posts", []))[: LIMITS.get("feed_max_posts", 400)]
        for p in posts:
            if p["importance"] >= 3:
                push_ntfy(f"{p['emoji']} Le Fil", p["text"], app_url() or p["sources"][0]["url"], priority="high")
        feed["updated_at"] = now_paris().isoformat()  # ne change que s'il y a du nouveau
        write_json(FEED_PATH, feed)
    write_json(STATE_PATH, state, indent=None)
    log(f"{len(posts)} post(s) publié(s).")


if __name__ == "__main__":
    main()
