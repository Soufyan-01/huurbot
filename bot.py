"""Huurbot: scant huursites op nieuwe woningen en meldt ze via Telegram.

Gebruik:
  python bot.py          normale scan
  python bot.py --test   rapporteert per bron wat er gevonden wordt (meldt geen woningen)
"""
import html
import json
import os
import random
import re
import sys
import time
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
import yaml

try:
    from curl_cffi import requests as browser_requests   # doet zich voor als Chrome
except ImportError:
    browser_requests = None
from bs4 import BeautifulSoup

ROOT = Path(__file__).parent
STATE_FILE = ROOT / "seen.json"
CONFIG = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))
TEST = "--test" in sys.argv
OVERVIEW = "--overzicht" in sys.argv

TG_TOKEN = os.environ.get("TELEGRAM_TOKEN")
TG_CHAT = os.environ.get("TELEGRAM_CHAT_ID")
WA_PHONE = os.environ.get("WHATSAPP_PHONE")      # bijv. +31612345678
WA_KEY = os.environ.get("WHATSAPP_APIKEY")       # van CallMeBot

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "nl-NL,nl;q=0.9,en;q=0.8",
}

PRICE_RE = re.compile(r"€\s*([\d.]{3,7})")
AREA_RE = re.compile(r"(\d{2,4})\s*m²")
GONE_RE = re.compile(r"\b(verhuurd|verkocht|niet meer beschikbaar)\b", re.I)
NAV_RE = re.compile(
    r"/(contact|over-ons|over|about|login|inloggen|mijn|account|registreren|"
    r"nieuws|blog|vacatures?|faq|veelgestelde-vragen|privacy|cookies?|disclaimer|"
    r"zoeken|search|verkoop|verkopen|kopen|koopwoningen|beleggers?|investors?|"
    r"huurders?|onderhoud|reparatie|klachten?)(/|$)", re.I)

KEEP_DAYS = 90
FAIL_ALERT_AT = 6

MIN_P, MAX_P = CONFIG["min_price"], CONFIG["max_price"]
_ex = [re.escape(w) for w in CONFIG.get("exclude_words", []) or []]
EXCLUDE_RE = re.compile("|".join(_ex), re.I) if _ex else None
PLACES = CONFIG["places"]


# ── bronnen ──────────────────────────────────────────────────────
def portal_jobs():
    """Ingebouwde portals: per plaats een zoek-URL + regex voor advertentielinks."""
    defs = {
        "pararius": (
            lambda p: f"https://www.pararius.nl/huurwoningen/{p}/{MIN_P}-{MAX_P}",
            r"^/(?:appartement|huis|studio|woning)-te-huur/[^/]+/[0-9a-f]{6,}/",
        ),
        "huurwoningen": (
            lambda p: f"https://www.huurwoningen.nl/in/{p}/",
            r"^/huren/[^/]+/[0-9a-f]{6,}/",
        ),
        "funda": (
            lambda p: (f'https://www.funda.nl/zoeken/huur?selected_area=["{p}"]'
                       f'&price="{MIN_P}-{MAX_P}"&sort="date_down"'),
            r"^(?:https://www\.funda\.nl)?/(?:detail/)?huur/[^/]+/(?:appartement|huis)-[^/]+/(?:\d+/)?$",
        ),
    }
    jobs = []
    for name, on in CONFIG.get("portals", {}).items():
        if on and name in defs:
            url_fn, rx = defs[name]
            jobs.append({"name": name, "kind": "portal", "link": re.compile(rx), "browser": True,
                         "pages": [(url_fn(p), p, None) for p in PLACES]})
    return jobs


def site_jobs():
    jobs = []
    for s in CONFIG.get("sites", []) or []:
        pages = []
        for u in s.get("urls", []) or []:
            places = PLACES if "{place}" in u else [None]
            for p in places:
                base = u.replace("{place}", p or "")
                if "{page}" in base:
                    seq = f"{s['name']}|{base}"
                    limit = s.get("overview_max_pages") if OVERVIEW else None
                    for n in range(1, int(limit or s.get("max_pages", 20)) + 1):
                        pages.append((base.replace("{page}", str(n)), p, seq))
                else:
                    pages.append((base, p, None))
        jobs.append({"name": s["name"], "kind": "site", "api": s.get("api"),
                     "radius": s.get("radius", 10),
                     "radius_filtered": bool(s.get("radius_filtered")),
                     "pattern": re.compile(s["pattern"]) if s.get("pattern") else None,
                     "pages": pages,
                     "expanded": any("{place}" in u for u in s.get("urls", []) or [])})
    return jobs


VESTEDA_SKIPPED = []


def fetch_vesteda(session, radius=10):
    """Vesteda laadt woningen via een achterliggende zoekdienst (JSON)."""
    body = {
        "filters": [], "latitude": 52.01152, "longitude": 4.7104635,
        "place": "Gouda", "placeType": 1, "radius": radius,
        "priceFrom": MIN_P, "priceTo": MAX_P, "sorting": 0,
        "paging": {"pageNo": 1, "pageSize": 60},
    }
    r = session.post("https://www.vesteda.com/api/units/search/facet", json=body,
                     headers={"Accept": "application/json",
                              "Referer": "https://www.vesteda.com/nl/woning-zoeken"},
                     timeout=20)
    r.raise_for_status()
    items = []

    def walk(o):
        if isinstance(o, dict):
            url = o.get("url") or o.get("detailUrl") or o.get("link")
            if isinstance(url, str) and re.search(r"/nl/[^/]+/[^/]+-\d+", url):
                full = urljoin("https://www.vesteda.com", url)
                city = str(o.get("city") or o.get("place") or "")
                title = " ".join(str(o.get(k) or "") for k in ("street", "houseNumber",
                                                               "houseNumberAddition")).strip()
                price = next((o.get(k) for k in ("priceUnformatted", "price", "rent")
                              if isinstance(o.get(k), (int, float))), None)
                area = next((o.get(k) for k in ("size", "surface", "livingArea")
                             if isinstance(o.get(k), (int, float))), None)
                hay = norm(full + " " + city)
                place = next((p for p in PLACES if norm(p) in hay), None) or city or "regio Gouda"
                status = str(o.get("status") or o.get("statusText") or "")
                if not GONE_RE.search(status):
                    items.append({"url": full, "title": (title or city) + (f", {city}" if city and city.lower() not in (title or "").lower() else ""),
                                  "place": place,
                                  "price": int(price) if price else None,
                                  "area": int(area) if area else None})
                else:
                    VESTEDA_SKIPPED.append(f"{title} {city} ({status})")
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)

    walk(r.json())
    return list({i["url"]: i for i in items}.values())


# ── helpers ──────────────────────────────────────────────────────
def load_state():
    if STATE_FILE.exists():
        st = json.loads(STATE_FILE.read_text(encoding="utf-8"))
    else:
        st = {}
    st.setdefault("seen", {})
    st.setdefault("fails", {})
    st.setdefault("seeded", [])
    if st.pop("initialized", False):           # migratie van v1
        st["seeded"] = sorted(set(st["seeded"]) | {"pararius", "huurwoningen", "funda"})
    return st


def save_state(state):
    cutoff = time.time() - KEEP_DAYS * 86400
    state["seen"] = {u: t for u, t in state["seen"].items() if t > cutoff}
    STATE_FILE.write_text(json.dumps(state, indent=1, sort_keys=True), encoding="utf-8")


def to_whatsapp(text):
    t = text.replace("<b>", "*").replace("</b>", "*").replace("<i>", "_").replace("</i>", "_")
    return html.unescape(re.sub(r"<[^>]+>", "", t))


def notify(text):
    """Stuurt naar Telegram en/of WhatsApp, afhankelijk van wat is ingesteld."""
    sent = False
    if TG_TOKEN and TG_CHAT:
        sent = True
        try:
            requests.post(f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage",
                          json={"chat_id": TG_CHAT, "text": text[:4000], "parse_mode": "HTML"},
                          timeout=15).raise_for_status()
        except requests.RequestException as e:
            print(f"Telegram-fout: {e}")
    if WA_PHONE and WA_KEY:
        sent = True
        try:
            r = requests.get("https://api.callmebot.com/whatsapp.php",
                             params={"phone": WA_PHONE, "apikey": WA_KEY,
                                     "text": to_whatsapp(text)[:1500]},
                             timeout=30)
            if r.status_code != 200:
                print(f"WhatsApp-fout {r.status_code}: {r.text[:200]}")
            time.sleep(3)   # CallMeBot wil niet te snel achter elkaar
        except requests.RequestException as e:
            print(f"WhatsApp-fout: {e}")
    if not sent:
        print("[melding]\n" + text + "\n")


telegram = notify   # oude naam blijft werken


def parse_int(s):
    d = re.sub(r"[^\d]", "", s)
    return int(d) if d else None


def norm(s):
    return re.sub(r"[-_+%20]+", " ", s.lower())


def climb(a, max_len=1500):
    """Tekst van het advertentieblok rond een link.

    Stopt zodra het blok een prijs bevat, te groot wordt, of een link naar een
    ándere advertentie bevat (dan zitten we in de lijst i.p.v. in één kaart).
    """
    own = a.get("href", "").split("#")[0]
    block, node = a.get_text(" ", strip=True), a
    if "€" in block:
        return block
    for _ in range(7):
        node = node.parent
        if node is None:
            break
        hrefs = {x.get("href", "").split("#")[0] for x in node.find_all("a", href=True)}
        hrefs.discard(own)
        if any(len(h) > 15 and not h.startswith(("#", "javascript", "mailto", "tel")) for h in hrefs):
            break
        text = node.get_text(" ", strip=True)
        if len(text) > max_len:
            break
        block = text
        if "€" in text:
            break
    return block


GENERIC_TITLES = {"details", "bekijk", "bekijken", "woning bekijken", "meer info",
                  "meer informatie", "reageer", "lees meer", "bekijk woning"}


# Alleen échte blokkadepagina's herkennen (géén gewone captcha in een formulier)
CHALLENGE_RE = re.compile(r"ben je een robot|are you a robot|just a moment\.\.\.|"
                          r"cf-browser-verification|challenge-platform|verify you are human", re.I)


def get_page(session, url, prefer_browser=False):
    """Haalt een pagina op. Bij blokkade (403/429/captcha) nog eens als 'echte' Chrome."""
    def plain():
        return session.get(url, timeout=20)

    def browser():
        return browser_requests.get(url, impersonate="chrome", timeout=25,
                                    headers={"Accept-Language": HEADERS["Accept-Language"]})

    attempts = [browser, plain] if (prefer_browser and browser_requests) else [plain]
    if browser_requests and not prefer_browser:
        attempts.append(browser)

    last = None
    for i, fn in enumerate(attempts):
        for retry in range(2):
            try:
                r = fn()
            except Exception as e:                       # verbinding verbroken e.d.
                last = e
                time.sleep(4)
                continue
            blocked = r.status_code in (403, 429) or (
                r.status_code == 200 and len(r.text) < 25000 and CHALLENGE_RE.search(r.text))
            if not blocked:
                return r
            last = requests.HTTPError(f"{r.status_code} geblokkeerd: {url}")
            break                                        # zelfde methode opnieuw heeft geen zin
    raise last if isinstance(last, requests.RequestException) else requests.RequestException(str(last))


def extract(page_html, page_url, job, page_place):
    soup = BeautifulSoup(page_html, "html.parser")
    host = urlparse(page_url).netloc.removeprefix("www.")
    page_base = page_url.split("?")[0].rstrip("/")
    found = {}
    raw_links = set()

    for a in soup.find_all("a", href=True):
        raw = a["href"].strip()
        if raw.startswith(("mailto:", "tel:", "javascript:", "#")):
            continue
        url = urljoin(page_url, raw).split("#")[0]
        u = urlparse(url)

        if job["kind"] == "portal":
            if not (job["link"].search(u.path) or job["link"].search(raw.split("?")[0])):
                continue
            url = url.split("?")[0]
            raw_links.add(url)
            place = page_place
            block = climb(a)
        else:
            # Generieke watcher: eigen domein, diep genoeg pad, geen menu-link
            if u.netloc.removeprefix("www.") != host:
                continue
            if u.path.rstrip("/").count("/") < 2 or NAV_RE.search(u.path):
                continue
            if url.split("?")[0].rstrip("/") == page_base:
                continue
            if job["pattern"] and not job["pattern"].search(url):
                continue
            raw_links.add(url)
            block = climb(a, max_len=800)
            hay = norm(url + " " + block)
            place = next((p for p in PLACES if norm(p) in hay), None)
            if not place:
                if not job.get("radius_filtered"):
                    continue
                place = "regio Gouda"

        if GONE_RE.search(block):
            continue
        if EXCLUDE_RE and EXCLUDE_RE.search(url + " " + block):
            continue

        title = a.get_text(" ", strip=True)
        item = found.setdefault(url, {"url": url, "title": "", "place": place,
                                      "price": None, "area": None})
        if len(title) > len(item["title"]):
            item["title"] = title[:120]
        if item["price"] is None and (m := PRICE_RE.search(block)):
            item["price"] = parse_int(m.group(1))
        if item["area"] is None and (m := AREA_RE.search(block)):
            item["area"] = int(m.group(1))

    for item in found.values():
        if len(item["title"]) > 70 or "€" in item["title"] or item["title"].lower() in GENERIC_TITLES:
            item["title"] = ""
        if not item["title"]:
            slug = item["url"].rstrip("/").split("/")[-1].split("?")[0]
            slug = re.sub(r"-[0-9a-f]{20,}$|(-\d+){2,}$|-h\d+$", "", slug)
            item["title"] = re.sub(r"[-+]", " ", slug).title() or "Woning"
    return list(found.values()), len(raw_links)


def matches(item):
    p, a = item["price"], item["area"]
    if p is not None and p >= 100 and not (MIN_P <= p <= MAX_P):
        return False
    if CONFIG.get("min_area") and a is not None and a < CONFIG["min_area"]:
        return False
    return True   # onbekende prijs/m²: liever wél melden


def line(item):
    price = f"€ {item['price']:,}".replace(",", ".") if item["price"] else "prijs ?"
    area = f" · {item['area']} m²" if item["area"] else ""
    return (f"• <b>{html.escape(item['title'][:60])}</b> – {price}{area}\n"
            f"  {html.escape(item['url'])}")


def send_list(header, items, per_msg=12):
    if not items:
        telegram(header)
        return
    for i in range(0, len(items), per_msg):
        chunk = items[i:i + per_msg]
        head = header if i == 0 else header + " (vervolg)"
        telegram(head + "\n\n" + "\n\n".join(line(x) for x in chunk))


def fmt(item, source):
    price = f"€ {item['price']:,}".replace(",", ".") if item["price"] else "prijs onbekend"
    area = f" · {item['area']} m²" if item["area"] else ""
    return (f"🏠 <b>{html.escape(item['title'])}</b>\n"
            f"📍 {html.escape(item['place'].replace('-', ' ').title())} · {price}{area}\n"
            f"🔗 {html.escape(item['url'])}\n<i>via {html.escape(source)}</i>")


# ── main ─────────────────────────────────────────────────────────
def main():
    state = load_state()
    session = requests.Session()
    session.headers.update(HEADERS)
    new_items, report, overview = [], [], []

    for job in portal_jobs() + site_jobs():
        name, total, raw_total, errors, items_all = job["name"], 0, 0, [], []
        if job.get("api") == "vesteda":
            try:
                items_all = fetch_vesteda(session, job.get("radius", 10))
                total = len(items_all)
                raw_total = max(1, total)                 # lege regio is geen storing
            except (requests.RequestException, ValueError) as e:
                errors.append(f"{e.__class__.__name__}: {str(e)[:80]}")
        finished = set()                                  # pagina-reeksen die op hun einde zijn
        for url, place, seq in job["pages"]:
            if seq and seq in finished:
                continue
            try:
                r = get_page(session, url, prefer_browser=job.get("browser", False))
                if r.status_code == 404:
                    raw_total += 1                        # bestaat niet: geen storing
                    if seq:
                        finished.add(seq)
                    continue
                if r.status_code >= 400:
                    raise requests.HTTPError(f"{r.status_code} voor {url}")
                items, raw = extract(r.text, url, job, place)
                if seq and raw == 0:
                    finished.add(seq)                     # laatste pagina gehad
                    continue
                total += len(items)
                raw_total += raw
                items_all += items
            except requests.RequestException as e:
                errors.append(f"{str(e)[:90]}")
                if seq:
                    finished.add(seq)
            time.sleep(random.uniform(1.0, 2.0))
        items_all = list({i["url"]: i for i in items_all}.values())
        total = len(items_all)

        if OVERVIEW:
            hits = [i for i in items_all if matches(i)]
            if hits:
                overview.append((name, hits))
            continue

        if TEST:
            hits = [i for i in items_all if matches(i)]
            line = (f"<b>{html.escape(name)}</b>: {raw_total} gescand · {total} in regio · "
                    f"{len(hits)} binnen je filters")
            if errors:
                line += f"\n   ⚠️ {html.escape(errors[0])}"
            for it in items_all[:8]:
                p = f"€{it['price']}" if it["price"] else "€?"
                mark = "✅" if matches(it) else "🚫"
                line += f"\n   {mark} {html.escape(it['title'][:45])} ({html.escape(str(it['place']))}) {p}"
            if job.get("api") == "vesteda" and VESTEDA_SKIPPED:
                line += "\n   verhuurd/weggefilterd: " + html.escape(", ".join(VESTEDA_SKIPPED[:5]))
            report.append(line)
            continue

        first_time = name not in state["seeded"]
        for it in items_all:
            if it["url"] not in state["seen"]:
                state["seen"][it["url"]] = time.time()
                if not first_time and matches(it):
                    new_items.append((it, name))

        if raw_total == 0:
            n = state["fails"].get(name, 0) + 1
            state["fails"][name] = n
            print(f"{name}: 0 resultaten ({n}x op rij). {errors[:1]}")
            if n == FAIL_ALERT_AT or (n > FAIL_ALERT_AT and n % 144 == 0):
                telegram(f"⚠️ Huurbot: <b>{html.escape(name)}</b> levert al {n} runs niets op. "
                         f"Geblokkeerd, site veranderd, of er staat gewoon niets in je regio.")
        else:
            if state["fails"].get(name, 0) >= FAIL_ALERT_AT:
                telegram(f"✅ Huurbot: {html.escape(name)} werkt weer.")
            state["fails"][name] = 0
            if first_time:
                state["seeded"].append(name)
                hits = [i for i in items_all if matches(i)]
                send_list(f"🤖 <b>{html.escape(name)} gekoppeld</b> – nu beschikbaar "
                          f"({len(hits)}). Vanaf nu krijg je alleen nieuwe.", hits)
            print(f"{name}: {total} advertenties gezien")

    if TEST:
        telegram("🧪 <b>Huurbot test</b>\n\n" + "\n\n".join(report))
        return

    if OVERVIEW:
        if not overview:
            telegram("📋 Op dit moment staat er niets in je regio dat binnen je filters valt.")
        for name, hits in overview:
            send_list(f"📋 <b>Huidig aanbod – {html.escape(name)}</b>", hits)
        return

    for it, src in new_items:
        telegram(fmt(it, src))
        time.sleep(0.5)
    print(f"{len(new_items)} nieuwe woning(en) gemeld")
    save_state(state)


if __name__ == "__main__":
    main()
