"""Journal du matin : une édition complète par jour, générée par Claude avec recherche web.

Lancé chaque matin par .github/workflows/journal.yml (05h UTC ≈ 7h Paris l'été).
Résultat : data/journal.json (14 éditions max, la plus récente en premier) + un post « journal » dans le fil.
"""
from __future__ import annotations

import json
import os
import re

from common import (BOT, DATA, app_url, ask_claude, extract_json, log, now_paris, push_ntfy, read_json,
                    write_json)

MODEL = os.environ.get("JOURNAL_MODEL") or "claude-sonnet-4-5"
JOURNAL_PATH = DATA / "journal.json"
FEED_PATH = DATA / "feed.json"
JOURS = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]
MOIS = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août", "septembre", "octobre",
        "novembre", "décembre"]
TOOLS_FULL = [
    {"type": "web_search_20250305", "name": "web_search", "max_uses": 60},
    {"type": "web_fetch_20250910", "name": "web_fetch", "max_uses": 60},
]
TOOLS_SEARCH = [TOOLS_FULL[0]]


def validate(e: dict, prev: dict | None) -> list[str]:
    err = []
    if prev and set(e) != set(prev):
        err.append(f"clés différentes de l'édition précédente : {sorted(set(e) ^ set(prev))}")
    if len(e.get("essentials", [])) != 5:
        err.append("essentials doit contenir exactement 5 phrases")
    for key, lo, hi in [("tech", 5, 8), ("finance_news", 5, 8), ("trends", 8, 12), ("watch", 3, 5)]:
        n = len(e.get(key, []))
        if not lo <= n <= hi:
            err.append(f"{key} : {n} éléments (attendu {lo}-{hi})")
    if len(e.get("markets", [])) < 11:
        err.append("markets : 11 actifs attendus")
    m = e.get("memes", {})
    for key, lo, hi in [("gainers", 5, 5), ("top_mcap", 5, 5), ("trending", 3, 5), ("radar", 5, 5)]:
        n = len(m.get(key, []))
        if not lo <= n <= hi:
            err.append(f"memes.{key} : {n} éléments (attendu {lo}-{hi})")
    for key in ("gainers", "top_mcap", "trending"):
        for c in m.get(key, []):
            if not 2 <= len(c.get("pump", [])) <= 4 or not c.get("pump_watch"):
                err.append(f"memes.{key} {c.get('ticker')} : pump/pump_watch manquant")
            if not str(c.get("change", "")).startswith(("+", "−", "-")):
                err.append(f"memes.{key} {c.get('ticker')} : variation sans signe")
    profiles = [r.get("profile") for r in m.get("radar", [])]
    if "Solide" not in profiles or profiles.count("Spéculatif") > 2:
        err.append("radar : au moins un Solide et au plus deux Spéculatif")
    for r in m.get("radar", []):
        sc = r.get("scores", {})
        if set(sc) != {"Liquidité", "Narratif", "Élan", "Sécurité"} or not all(isinstance(v, int) and 1 <= v <= 5 for v in sc.values()):
            err.append(f"radar {r.get('ticker')} : 4 notes entières entre 1 et 5 attendues")
    for x in e.get("markets", []):
        if not str(x.get("change", "")).startswith(("+", "−", "-")):
            err.append(f"markets {x.get('asset')} : variation sans signe")
    bad = [u for u in re.findall(r'"url":\s*"([^"]*)"', json.dumps(e, ensure_ascii=False)) if not u.startswith("https://")]
    if bad:
        err.append(f"URL non https : {bad[:5]}")
    return err


def main():
    now = now_paris()
    editions = read_json(JOURNAL_PATH, [])
    prev = editions[0] if editions else None
    date = now.strftime("%Y-%m-%d")
    label = f"{JOURS[now.weekday()]} {now.day}{'er' if now.day == 1 else ''} {MOIS[now.month - 1]} {now.year}"
    system = (BOT / "prompts" / "journal.md").read_text(encoding="utf-8")
    user = (f"Nous sommes le {label} ({date}), il est {now.strftime('%Hh%M')} à Paris.\n"
            f"Édition précédente (structure à reprendre, news à ne pas répéter) :\n"
            f"{json.dumps(prev, ensure_ascii=False) if prev else 'aucune'}")
    try:
        raw = ask_claude(system, user, MODEL, max_tokens=32000, tools=TOOLS_FULL, betas=["web-fetch-2025-09-10"])
    except Exception as exc:  # noqa: BLE001  (web_fetch indisponible sur le compte → recherche seule)
        log(f"[web_fetch KO, repli sur web_search seul] {exc}")
        raw = ask_claude(system, user, MODEL, max_tokens=32000, tools=TOOLS_SEARCH)
    edition = extract_json(raw)
    errors = validate(edition, prev)
    if errors:
        log("Corrections demandées :", errors)
        fix = ask_claude("Tu corriges un objet JSON. Réponds uniquement avec l'objet JSON corrigé. N'invente aucune donnée : "
                         "si une information manque, écris « n.d. » ou retire l'élément en respectant les bornes.",
                         json.dumps({"erreurs": errors, "edition": edition}, ensure_ascii=False), MODEL, max_tokens=32000)
        edition = extract_json(fix)
        errors = validate(edition, prev)
        if errors:
            log("Erreurs restantes (édition publiée quand même) :", errors)
    edition["date"], edition["date_label"] = date, label
    edition.setdefault("generated_at", now.isoformat())
    editions = [edition] + [x for x in editions if x.get("date") != date]
    write_json(JOURNAL_PATH, editions[:14], indent=None)

    # Post « journal » dans le fil + notification
    feed = read_json(FEED_PATH, {"posts": []})
    first = (edition.get("essentials") or ["Nouvelle édition disponible."])[0]
    url = (app_url().rstrip("/") + "/journal.html") if app_url() else ""
    post = {"id": f"journal-{date}", "ts": now.isoformat(), "kind": "journal", "emoji": "🗞️",
            "text": f"Le journal du {label} est prêt. {first}", "tickers": [], "importance": 2,
            "sources": [{"label": "Ouvrir le journal", "url": "journal.html"}]}
    feed["posts"] = [post] + [p for p in feed.get("posts", []) if p.get("id") != post["id"]]
    feed["updated_at"] = now.isoformat()
    write_json(FEED_PATH, feed)
    push_ntfy("🗞️ Journal du matin", first, url or None, priority="default")
    log("Édition publiée :", date)


if __name__ == "__main__":
    main()
