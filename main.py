"""
Steam Scraper — store search, full app details and reviews.

Dependency-free (stdlib + Apify REST). No login, no API key, no browser.

Data paths (all public JSON endpoints of the Steam store):
  search:     https://store.steampowered.com/search/results/?query&start=&count=&term=&infinite=1
  app detail: https://store.steampowered.com/api/appdetails?appids=<id>&cc=&l=
  reviews:    https://store.steampowered.com/appreviews/<id>?json=1&cursor=&num_per_page=&...
store.steampowered.com/robots.txt allows /search/, /app/, /appreviews/ and /api/appdetails.

Normalized, de-duplicated, with provenance on every row.
"""
from __future__ import annotations
import json, os, re, ssl, uuid, time, math
from datetime import datetime, timezone
from urllib import request as urlrequest
from urllib.parse import urlencode, quote
from urllib.error import HTTPError, URLError

SCHEMA_VERSION = "1.0.0"
API = "https://api.apify.com/v2"
BASE = "https://store.steampowered.com"
UA = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/144.0.0.0 Safari/537.36",
    "Accept": "application/json, text/html;q=0.9, */*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}
_CTX = ssl.create_default_context()
_RX_APPID = re.compile(r'data-ds-appid="([0-9,]+)"')
_RX_APPID2 = re.compile(r'app/(\d+)')


def log(*a):
    print(*a, flush=True)


def _u(path):
    return f"{API}{path}{'&' if '?' in path else '?'}" + urlencode({"token": os.environ.get("APIFY_TOKEN", "")})


def _get(url, timeout=40):
    with urlrequest.urlopen(urlrequest.Request(url, headers=UA), timeout=timeout, context=_CTX) as r:
        return json.loads(r.read().decode("utf-8", "ignore"))


def get_input():
    store = os.environ.get("ACTOR_DEFAULT_KEY_VALUE_STORE_ID")
    if store and os.environ.get("APIFY_TOKEN"):
        try:
            return json.loads(_get_kv(_u(f"/key-value-stores/{store}/records/{os.environ.get('ACTOR_INPUT_KEY','INPUT')}")))
        except Exception as e:
            log(f"input fetch failed: {e}")
    if os.path.exists("input.json"):
        return json.load(open("input.json"))
    return {}


def _get_kv(url, timeout=35):
    with urlrequest.urlopen(urlrequest.Request(url, headers=UA), timeout=timeout, context=_CTX) as r:
        return r.read().decode("utf-8", "ignore")


def _now():
    return datetime.now(timezone.utc).isoformat()


def _iso(ts):
    if not ts:
        return None
    try:
        return datetime.fromtimestamp(int(ts), tz=timezone.utc).isoformat()
    except Exception:
        return None


def push_items(items):
    items = [_sanitize(r) for r in items]
    token = os.environ.get("APIFY_TOKEN"); ds = os.environ.get("ACTOR_DEFAULT_DATASET_ID")
    if not (token and ds):
        with open("dataset_local.jsonl", "a") as f:
            for it in items:
                f.write(json.dumps(it) + "\n")
        return len(items)
    n = 0
    for i in range(0, len(items), 300):
        chunk = items[i:i + 300]
        req = urlrequest.Request(_u(f"/datasets/{ds}/items"), data=json.dumps(chunk).encode(),
                                 method="POST", headers={"Content-Type": "application/json"})
        try:
            urlrequest.urlopen(req, timeout=120, context=_CTX).read()
        except HTTPError as e:
            try: body = e.read().decode()[:400]
            except Exception: body = ""
            log(f"push_items HTTP {e.code} ds={ds} token_set={bool(token)} chunk={len(chunk)} body={body}")
            raise
        n += len(chunk)
    return n


def _sanitize(o):
    """Recursively replace non-finite floats (NaN/Infinity) with None so the
    payload is strict JSON that the Apify API accepts."""
    if isinstance(o, float):
        return o if math.isfinite(o) else None
    if isinstance(o, dict):
        return {k: _sanitize(v) for k, v in o.items()}
    if isinstance(o, list):
        return [_sanitize(v) for v in o]
    return o


def charge(event_name, count):
    token = os.environ.get("APIFY_TOKEN"); rid = os.environ.get("ACTOR_RUN_ID")
    if not (token and rid) or count <= 0:
        return
    body = json.dumps({"eventName": event_name, "count": int(count)}).encode()
    req = urlrequest.Request(_u(f"/actor-runs/{rid}/charge"), data=body, method="POST",
                             headers={"Content-Type": "application/json", "idempotency-key": uuid.uuid4().hex})
    try:
        urlrequest.urlopen(req, timeout=30, context=_CTX).read()
    except HTTPError as e:
        try: log(f"charge {event_name} failed: {e.code} {e.read().decode()[:160]}")
        except Exception: log(f"charge {event_name} failed: {e.code}")
    except Exception as e:
        log(f"charge {event_name} failed: {e}")


# ---------------------------------------------------------------- scraping ---

def steam_search(term, cc, lang, max_results):
    ids = []
    start = 0
    total = None
    while len(ids) < max_results:
        qs = urlencode({"query": "", "start": start, "count": 100, "term": term,
                        "infinite": 1, "cc": cc, "l": lang})
        d = _get(f"{BASE}/search/results/?{qs}")
        if not d.get("success"):
            break
        total = d.get("total_count")
        html = d.get("results_html") or ""
        page_ids = []
        for m in _RX_APPID.finditer(html):
            for part in m.group(1).split(","):
                if part.strip().isdigit():
                    page_ids.append(int(part.strip()))
        if not page_ids:
            break
        for i in page_ids:
            if i not in ids:
                ids.append(i)
        start += 100
        if total is not None and start >= int(total):
            break
        if len(ids) >= max_results:
            break
        time.sleep(0.4)
    return ids[:max_results]


def steam_appdetails(appid, cc, lang):
    d = _get(f"{BASE}/api/appdetails?" + urlencode({"appids": appid, "cc": cc, "l": lang}))
    node = d.get(str(appid)) or {}
    return node.get("data") if node.get("success") else None


def _genre(d):
    return [g.get("description") for g in (d.get("genres") or []) if isinstance(g, dict)]


def _cats(d):
    return [c.get("description") for c in (d.get("categories") or []) if isinstance(c, dict)]


def game_record(d, appid, source_type, source_input, cc, include_desc):
    po = d.get("price_overview") or {}
    rec = {
        "record_type": "game",
        "app_id": appid,
        "name": d.get("name"),
        "app_type": d.get("type"),
        "is_free": d.get("is_free"),
        "is_coming_soon": (d.get("release_date") or {}).get("coming_soon"),
        "release_date": (d.get("release_date") or {}).get("date"),
        "required_age": d.get("required_age"),
        "developers": d.get("developers") or None,
        "publishers": d.get("publishers") or None,
        "genres": _genre(d) or None,
        "categories": _cats(d) or None,
        "platforms_windows": (d.get("platforms") or {}).get("windows"),
        "platforms_mac": (d.get("platforms") or {}).get("mac"),
        "platforms_linux": (d.get("platforms") or {}).get("linux"),
        "price_currency": po.get("currency"),
        "price_initial": po.get("initial"),
        "price_final": po.get("final"),
        "price_discount_percent": po.get("discount_percent"),
        "price_formatted": po.get("final_formatted"),
        "is_discounted": (po.get("discount_percent") or 0) > 0 if po else None,
        "metacritic_score": (d.get("metacritic") or {}).get("score"),
        "recommendations_total": (d.get("recommendations") or {}).get("total"),
        "achievements_total": (d.get("achievements") or {}).get("total"),
        "controller_support": d.get("controller_support"),
        "supported_languages": d.get("supported_languages"),
        "website": d.get("website"),
        "header_image": d.get("header_image"),
        "capsule_image": d.get("capsule_image"),
        "background": d.get("background"),
        "short_description": d.get("short_description"),
        "screenshot_count": len(d.get("screenshots") or []),
        "screenshots": [s.get("path_full") for s in (d.get("screenshots") or []) if isinstance(s, dict)] or None,
        "movie_count": len(d.get("movies") or []),
        "dlc_count": len(d.get("dlc") or []),
        "dlc": d.get("dlc") or None,
        "store_url": f"{BASE}/app/{appid}",
        "source_type": source_type,
        "source_input": source_input,
        "schema_version": SCHEMA_VERSION,
        "fetched_at": _now(),
    }
    if include_desc:
        rec["detailed_description"] = re.sub(r"<[^>]+>", " ", d.get("detailed_description") or "").strip() or None
        rec["about_the_game"] = re.sub(r"<[^>]+>", " ", d.get("about_the_game") or "").strip() or None
    return rec


def review_record(r, appid, qs, source_input):
    a = r.get("author") or {}
    return {
        "record_type": "review",
        "recommendation_id": str(r.get("recommendationid")) if r.get("recommendationid") is not None else None,
        "app_id": appid,
        "language": r.get("language"),
        "review_text": r.get("review"),
        "voted_up": r.get("voted_up"),
        "votes_up": r.get("votes_up"),
        "votes_funny": r.get("votes_funny"),
        "weighted_vote_score": r.get("weighted_vote_score"),
        "comment_count": r.get("comment_count"),
        "timestamp_created": _iso(r.get("timestamp_created")),
        "timestamp_created_epoch": r.get("timestamp_created"),
        "timestamp_updated": _iso(r.get("timestamp_updated")),
        "steam_purchase": r.get("steam_purchase"),
        "received_for_free": r.get("received_for_free"),
        "refunded": r.get("refunded"),
        "written_during_early_access": r.get("written_during_early_access"),
        "primarily_steam_deck": r.get("primarily_steam_deck"),
        "author_steamid": a.get("steamid"),
        "author_personaname": a.get("personaname"),
        "author_profile_url": a.get("profile_url"),
        "author_num_games_owned": a.get("num_games_owned"),
        "author_num_reviews": a.get("num_reviews"),
        "author_playtime_forever": a.get("playtime_forever"),
        "author_playtime_at_review": a.get("playtime_at_review"),
        "review_score_desc": (qs or {}).get("review_score_desc"),
        "review_score": (qs or {}).get("review_score"),
        "total_positive": (qs or {}).get("total_positive"),
        "total_negative": (qs or {}).get("total_negative"),
        "total_reviews": (qs or {}).get("total_reviews"),
        "source_input": source_input,
        "schema_version": SCHEMA_VERSION,
        "fetched_at": _now(),
    }


def steam_reviews(appid, max_reviews, rfilter, lang, ptype, day_range, source_input):
    out = []
    cursor = "*"
    summary = None
    while len(out) < max_reviews and cursor is not None:
        params = {"json": 1, "num_per_page": min(100, max_reviews - len(out)),
                  "filter": rfilter, "language": lang, "purchase_type": ptype, "cursor": cursor}
        if day_range:
            params["day_range"] = day_range
        d = _get(f"{BASE}/appreviews/{appid}?{urlencode(params)}")
        if not d.get("success"):
            break
        summary = summary or d.get("query_summary")
        revs = d.get("reviews") or []
        if not revs:
            break
        for r in revs:
            out.append(review_record(r, appid, summary, source_input))
            if len(out) >= max_reviews:
                break
        nc = d.get("cursor")
        if not nc or nc == cursor:
            break
        cursor = nc
        time.sleep(0.3)
    return out


def norm_appids(vals):
    ids = []
    for v in vals or []:
        v = str(v).strip()
        if not v:
            continue
        m = _RX_APPID2.search(v)
        if m:
            ids.append(int(m.group(1)))
        elif v.isdigit():
            ids.append(int(v))
    return ids


def main():
    inp = get_input() or {}
    cc = (inp.get("country") or "US").upper()
    lang = (inp.get("language") or "english")
    include_desc = bool(inp.get("includeDescriptions"))
    include_reviews = bool(inp.get("includeReviews"))
    max_per_search = int(inp.get("maxResultsPerSearch") or 50)
    max_reviews = int(inp.get("maxReviewsPerApp") or 100)
    rfilter = inp.get("reviewFilter") or "recent"
    review_lang = inp.get("reviewLanguage") or "all"
    ptype = inp.get("reviewPurchaseType") or "all"
    day_range = inp.get("reviewDayRange")
    max_items = int(inp.get("maxItems") or 100000)

    search_terms = inp.get("searchQueries") or []
    if isinstance(search_terms, str):
        search_terms = [search_terms]
    app_ids = norm_appids(inp.get("appIds"))

    if not search_terms and not app_ids:
        search_terms = ["hades"]

    charge("actor-start", 1)
    rows = []; seen_apps = set(); seen_revs = set(); seen_apps_done = set(); errors = []

    # collect app ids from searches
    for term in search_terms:
        term = str(term).strip()
        if not term:
            continue
        try:
            ids = steam_search(term, cc, lang, max_per_search)
            for i in ids:
                if i not in seen_apps:
                    app_ids.append((i, "search", term))
            seen_apps.update(ids)
        except (HTTPError, URLError, ValueError) as e:
            errors.append(f"search '{term}': {str(e)[:60]}")

    # normalise app_ids entries to (id, source_type, source_label)
    norm = []
    for entry in app_ids:
        if isinstance(entry, tuple):
            if len(entry) == 3:
                norm.append(entry)
            else:
                norm.append((entry[0], "search", str(entry[1])))
        else:
            norm.append((entry, "app", str(entry)))

    for appid, src_type, src in norm:
        if appid in seen_apps_done:
            continue
        seen_apps_done.add(appid)
        try:
            d = steam_appdetails(appid, cc, lang)
            if not d:
                continue
            g = game_record(d, appid, src_type, src, cc, include_desc)
            rows.append(g)
            if include_reviews:
                revs = steam_reviews(appid, max_reviews, rfilter, review_lang, ptype, day_range, src)
                for r in revs:
                    k = r.get("recommendation_id")
                    if k and k not in seen_revs:
                        seen_revs.add(k)
                        rows.append(r)
            time.sleep(0.4)
        except (HTTPError, URLError, ValueError, KeyError) as e:
            errors.append(f"app {appid}: {str(e)[:60]}")

    rows = rows[:max_items]
    n_games = sum(1 for r in rows if r["record_type"] == "game")
    n_revs = len(rows) - n_games
    pushed = push_items(rows)
    charge("game", n_games)
    charge("review", n_revs)
    log(f"FINISHED games={n_games} reviews={n_revs} pushed={pushed} errors={len(errors)}")
    if errors:
        log("Errors: " + "; ".join(errors[:15]))


if __name__ == "__main__":
    main()
