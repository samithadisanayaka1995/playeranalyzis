#!/usr/bin/env python3
"""
Enrichment step (run after build.py, then run build.py again):

1. Batting hand, bowling style and role from Wikipedia infoboxes, matched
   exactly via the ESPNcricinfo player ID recorded in Wikidata (Cricinfo itself
   blocks automated requests). Needed for "vs pace / vs spin" and "vs left / right-handers" analysis.
   Cached in pipeline/cache/player_meta.json; misses are retried after 14 days.
   Corrections go in pipeline/overrides/player_styles.csv.

2. YouTube highlights -> one video per match, via the YouTube Data API v3.
   Only runs when the YOUTUBE_API_KEY environment variable is set (add it as a
   repository secret). Without it the app links to a YouTube search instead.
   Cached in pipeline/cache/highlights.json.

Usage:  python pipeline/enrich.py [--max-players 600] [--max-videos 90]
"""
from __future__ import annotations

import argparse
import datetime as dt
import html
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE = os.path.join(ROOT, "pipeline", "cache")
UA = "playeranalyzis/1.0 (https://github.com/samithadisanayaka1995/playeranalyzis; cricket stats app)"

BAT = {"rhb": "Right hand Bat", "lhb": "Left hand Bat"}
BOWL = {
    "rf": "Right arm Fast", "rfm": "Right arm Fast medium", "rmf": "Right arm Medium fast",
    "rm": "Right arm Medium", "rsm": "Right arm Slow medium", "lf": "Left arm Fast",
    "lfm": "Left arm Fast medium", "lmf": "Left arm Medium fast", "lm": "Left arm Medium",
    "lsm": "Left arm Slow medium", "ob": "Right arm Offbreak", "lb": "Legbreak",
    "lbg": "Legbreak Googly", "sla": "Slow Left arm Orthodox", "lws": "Left arm Wrist spin",
    "lbr": "Legbreak", "rab": "Right arm Bowler", "lab": "Left arm Bowler",
}
TEAM_CODES = {
    "Afghanistan": ["afg"], "Australia": ["aus"], "Bangladesh": ["ban"], "England": ["eng"],
    "India": ["ind"], "Ireland": ["ire"], "New Zealand": ["nz"], "Pakistan": ["pak"],
    "South Africa": ["sa", "rsa"], "Sri Lanka": ["sl"], "West Indies": ["wi"], "Zimbabwe": ["zim"],
}


def load(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def save(path, obj):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=0, sort_keys=True, ensure_ascii=False)


def get(url, timeout=30):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Language": "en", "Accept": "application/json, text/html"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "replace")


def slug(name):
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def _walk(o):
    if isinstance(o, dict):
        yield o
        for v in o.values():
            yield from _walk(v)
    elif isinstance(o, list):
        for v in o:
            yield from _walk(v)


def parse_cricinfo(page, ci):
    out = {}
    m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', page, re.S)
    if m:
        try:
            data = json.loads(m.group(1))
            for d in _walk(data):
                if str(d.get("objectId")) == str(ci) and ("battingStyles" in d or "bowlingStyles" in d):
                    bats = d.get("longBattingStyles") or [BAT.get(x, x) for x in d.get("battingStyles") or []]
                    bowls = d.get("longBowlingStyles") or [BOWL.get(x, x) for x in d.get("bowlingStyles") or []]
                    roles = d.get("playingRoles") or []
                    if bats:
                        out["bat"] = bats[0]
                    if bowls:
                        out["bowl"] = bowls[0]
                    if roles:
                        out["role"] = roles[0].title() if isinstance(roles[0], str) else None
                    out["full"] = d.get("longName") or d.get("name")
                    break
        except ValueError:
            pass
    if not out:  # fall back to the visible profile text
        txt = html.unescape(re.sub(r"<[^>]+>", "|", page))
        txt = re.sub(r"\|+", "|", txt)
        for label, key in (("Batting Style", "bat"), ("Bowling Style", "bowl"), ("Playing Role", "role"), ("Full Name", "full")):
            mm = re.search(label + r"\|\s*([^|]{2,60})\|", txt)
            if mm:
                out[key] = mm.group(1).strip()
    return out


WD_SPARQL = "https://query.wikidata.org/sparql"
WP_API = "https://en.wikipedia.org/w/api.php"


def clean_wiki(v):
    v = re.sub(r"<ref[^>]*/>|<ref.*?</ref>|<!--.*?-->", "", v, flags=re.S)
    v = re.sub(r"\{\{(?:nowrap|small|nobr)\|([^{}]*)\}\}", r"\1", v, flags=re.I)
    v = re.sub(r"\{\{[^{}]*\}\}", "", v)
    v = re.sub(r"\[\[(?:[^|\]]*\|)?([^\]]*)\]\]", r"\1", v)
    v = re.sub(r"<br\s*/?>", " / ", v)
    v = re.sub(r"<[^>]+>", "", v).replace("'''", "").replace("''", "")
    return re.sub(r"\s+", " ", v).strip(" ,;/")


def infobox(wikitext):
    out = {}
    for key, field in (("bat", "batting"), ("bowl", "bowling"), ("role", "role"), ("full", "fullname")):
        m = re.search(r"\n[ \t]*\|[ \t]*" + field + r"[ \t]*=[ \t]*([^\n]*)", wikitext, re.I)
        if m:
            val = clean_wiki(m.group(1))
            if val and not val.startswith("|") and val.lower() not in ("none", "-", "—"):
                out[key] = val[:80]
    if "bat" in out:
        b = out["bat"].lower()
        out["bat"] = "Left hand Bat" if b.startswith("left") else "Right hand Bat" if b.startswith("right") else out["bat"]
    if "bowl" in out:
        out["bowl"] = out["bowl"][0].upper() + out["bowl"][1:]
    if "role" in out:
        out["role"] = out["role"][0].upper() + out["role"][1:]
    return out


def enrich_players(todo, meta, limit):
    """Batting hand, bowling style and role from each player's Wikipedia infobox,
    matched exactly through the ESPNcricinfo player ID stored in Wikidata (P2697)."""
    today = dt.date.today()
    want = {}
    for pid, p in todo["players"].items():
        cur = meta.get(pid)
        if cur and not cur.get("err"):
            continue
        if cur and cur.get("err") and cur.get("src") == "wikipedia" and (today - dt.date.fromisoformat(cur["t"])).days < 14:
            continue
        if p.get("ci"):
            want[str(p["ci"])] = pid
        if len(want) >= limit:
            break
    if not want:
        return 0
    titles = {}
    ids = list(want)
    for i in range(0, len(ids), 150):
        chunk = ids[i:i + 150]
        q = ("SELECT ?ci ?article WHERE { VALUES ?ci { " + " ".join(f'"{c}"' for c in chunk) +
             " } ?item wdt:P2697 ?ci . ?article schema:about ?item ; schema:isPartOf <https://en.wikipedia.org/> . }")
        url = WD_SPARQL + "?" + urllib.parse.urlencode({"query": q, "format": "json"})
        try:
            res = json.loads(get(url, timeout=90))
        except Exception as e:
            print(f"  Wikidata query failed: {e}", file=sys.stderr)
            continue
        for b in res["results"]["bindings"]:
            t = urllib.parse.unquote(b["article"]["value"].rsplit("/wiki/", 1)[1]).replace("_", " ")
            titles[t] = want[b["ci"]["value"]]
        time.sleep(1)
    print(f"  Wikipedia articles found for {len(titles)} of {len(want)} players", file=sys.stderr)
    tl = list(titles)
    for i in range(0, len(tl), 40):
        chunk = tl[i:i + 40]
        url = WP_API + "?" + urllib.parse.urlencode({
            "action": "query", "prop": "revisions", "rvprop": "content", "rvslots": "main",
            "format": "json", "formatversion": "2", "redirects": "1", "titles": "|".join(chunk)})
        try:
            res = json.loads(get(url, timeout=90))
        except Exception as e:
            print(f"  Wikipedia fetch failed: {e}", file=sys.stderr)
            continue
        redir = {r["to"]: r["from"] for r in res["query"].get("redirects", [])}
        norm = {n["to"]: n["from"] for n in res["query"].get("normalized", [])}
        for page in res["query"]["pages"]:
            t = page.get("title")
            src = redir.get(t, t)
            src = norm.get(src, src)
            pid = titles.get(src) or titles.get(t)
            if not pid or "revisions" not in page:
                continue
            info = infobox(page["revisions"][0]["slots"]["main"]["content"])
            info["t"] = today.isoformat()
            info["src"] = "wikipedia"
            meta[pid] = info
        time.sleep(1)
    for ci, pid in want.items():
        if meta.get(pid, {}).get("src") != "wikipedia":
            meta[pid] = {"err": "no wikipedia infobox", "src": "wikipedia", "t": today.isoformat()}
    return len(want)


def team_hit(title, team):
    t = title.lower()
    if team.lower() in t:
        return True
    return any(re.search(rf"\b{c}\b", t) for c in TEAM_CODES.get(team, []))


def enrich_videos(todo, hl, key, limit):
    today = dt.date.today()
    n = 0
    items = sorted(todo["matches"].items(), key=lambda kv: kv[1]["date"], reverse=True)
    for mid, m in items:
        if n >= limit:
            break
        cur = hl.get(mid)
        if cur and cur.get("vid"):
            continue
        if cur and (today - dt.date.fromisoformat(cur["t"])).days < 7:
            continue
        n += 1
        d = dt.date.fromisoformat(m["date"])
        params = {
            "part": "snippet", "type": "video", "maxResults": 8, "q": m["q"], "key": key,
            "publishedAfter": (d - dt.timedelta(days=1)).isoformat() + "T00:00:00Z",
            "publishedBefore": (d + dt.timedelta(days=21)).isoformat() + "T00:00:00Z",
            "relevanceLanguage": "en",
        }
        try:
            res = json.loads(get("https://www.googleapis.com/youtube/v3/search?" + urllib.parse.urlencode(params)))
        except Exception as e:
            print(f"  ✗ {m['q']}: {e}", file=sys.stderr)
            if "403" in str(e):
                print("  YouTube quota exhausted or key invalid; stopping.", file=sys.stderr)
                break
            continue
        best = None
        for it in res.get("items", []):
            title = html.unescape(it["snippet"]["title"])
            if "highlight" not in title.lower():
                continue
            if not (team_hit(title, m["teams"][0]) and team_hit(title, m["teams"][1])):
                continue
            if m["g"] == "female" and not re.search(r"wom|wmn|\bw\b", title.lower()):
                continue
            if m["g"] == "male" and re.search(r"women|\bwmn\b", title.lower()):
                continue
            best = {"vid": it["id"]["videoId"], "title": title, "ch": it["snippet"]["channelTitle"]}
            break
        hl[mid] = (best or {}) | {"t": today.isoformat()}
        print(f"  {'✓' if best else '–'} {m['q']}" + (f" → {best['title']}" if best else ""), file=sys.stderr)
    return n


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-players", type=int, default=600)
    ap.add_argument("--max-videos", type=int, default=90)
    a = ap.parse_args()
    todo = load(os.path.join(CACHE, "todo.json"), None)
    if not todo:
        sys.exit("run build.py first")
    mp = os.path.join(CACHE, "player_meta.json")
    meta = load(mp, {})
    try:
        print(f"Player profiles: {enrich_players(todo, meta, a.max_players)} fetched", file=sys.stderr)
    finally:
        save(mp, meta)
    key = os.environ.get("YOUTUBE_API_KEY")
    if key:
        hp = os.path.join(CACHE, "highlights.json")
        hl = load(hp, {})
        try:
            print(f"Highlights: {enrich_videos(todo, hl, key, a.max_videos)} searched", file=sys.stderr)
        finally:
            save(hp, hl)
    else:
        print("YOUTUBE_API_KEY not set — highlights will link to YouTube search.", file=sys.stderr)


if __name__ == "__main__":
    main()
