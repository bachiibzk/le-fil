"""Outils partagés par le bot du fil (live.py) et le journal du matin (journal.py)."""
from __future__ import annotations

import datetime as dt
import json
import os
import re
import sys
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
BOT = ROOT / "bot"
PARIS = ZoneInfo("Europe/Paris")
UA = {"User-Agent": "journal-du-matin-bot/1.0 (+https://github.com)", "Accept": "application/json, */*"}


def log(*args):
    print(*args, file=sys.stderr, flush=True)


def now_paris() -> dt.datetime:
    return dt.datetime.now(PARIS).replace(microsecond=0)


def read_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def write_json(path: Path, data, indent: int | None = 1):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=indent) + "\n", encoding="utf-8")
    tmp.replace(path)


def get_json(url: str, timeout: int = 20, **kw):
    """GET JSON, renvoie None en cas d'échec (une source en panne ne doit pas bloquer le bot)."""
    try:
        r = requests.get(url, headers=UA, timeout=timeout, **kw)
        r.raise_for_status()
        return r.json()
    except Exception as exc:  # noqa: BLE001
        log(f"[source KO] {url[:90]} : {exc}")
        return None


def fr_pct(x: float | None) -> str:
    """+1,23 % / −4,56 % (signe moins typographique)."""
    if x is None:
        return "n.d."
    s = f"{abs(x):.2f}".replace(".", ",")
    return ("+" if x >= 0 else "−") + s + " %"


def fr_usd(x: float | None) -> str:
    if x is None:
        return "n.d."
    if x >= 1e9:
        return f"{x / 1e9:.2f}".replace(".", ",") + " Md$"
    if x >= 1e6:
        return f"{x / 1e6:.2f}".replace(".", ",") + " M$"
    if x >= 1:
        return f"{x:,.2f}".replace(",", " ").replace(".", ",") + " $"
    return f"{x:.8g}".replace(".", ",") + " $"


def extract_json(text: str):
    """Récupère le premier objet JSON d'une réponse (tolère les ```json)."""
    text = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.M)
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("Pas d'objet JSON dans la réponse")
    return json.loads(text[start : end + 1])


# ---------- Claude ----------

def claude_client():
    import anthropic  # import tardif : live.py n'en a besoin que s'il y a du nouveau

    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        raise SystemExit("ANTHROPIC_API_KEY manquant (Settings > Secrets and variables > Actions).")
    return anthropic.Anthropic(api_key=key, max_retries=3)


def response_text(msg) -> str:
    return "".join(getattr(b, "text", "") for b in msg.content if getattr(b, "type", "") == "text")


def ask_claude(system: str, user: str, model: str, max_tokens: int = 4000, tools=None, betas=None, max_continuations: int = 8) -> str:
    """Appel Claude en streaming, avec gestion des 'pause_turn' des outils serveur (web search / web fetch)."""
    client = claude_client()
    messages = [{"role": "user", "content": user}]
    kwargs = dict(model=model, max_tokens=max_tokens, system=system)
    if tools:
        kwargs["tools"] = tools
    api = client.beta.messages if betas else client.messages
    if betas:
        kwargs["betas"] = betas
    text_parts = []
    for _ in range(max_continuations):
        with api.stream(messages=messages, **kwargs) as stream:
            msg = stream.get_final_message()
        text_parts.append(response_text(msg))
        usage = getattr(msg, "usage", None)
        log(f"[claude] stop={msg.stop_reason} usage={usage}")
        if msg.stop_reason == "pause_turn":
            messages = messages + [{"role": "assistant", "content": msg.content}]
            continue
        break
    return "".join(text_parts)


# ---------- Notifications (optionnel) ----------

def push_ntfy(title: str, body: str, url: str | None = None, priority: str = "default"):
    """Envoie une notification via ntfy.sh si le secret NTFY_TOPIC est défini."""
    topic = os.environ.get("NTFY_TOPIC", "").strip()
    if not topic:
        return
    server = os.environ.get("NTFY_SERVER", "https://ntfy.sh").rstrip("/")
    headers = {"Title": title.encode("utf-8"), "Priority": priority, "Tags": "newspaper"}
    if url:
        headers["Click"] = url
    try:
        requests.post(f"{server}/{topic}", data=body.encode("utf-8"), headers=headers, timeout=15)
    except Exception as exc:  # noqa: BLE001
        log(f"[ntfy KO] {exc}")


def app_url() -> str:
    return os.environ.get("APP_URL", "").strip()
