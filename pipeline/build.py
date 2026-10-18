#!/usr/bin/env python3
"""
Build the player-analysis dataset for the web app.

Source data
-----------
* Ball-by-ball match files from Cricsheet (https://cricsheet.org) — the open
  dataset that mirrors ESPNcricinfo scorecards delivery by delivery.
* The Cricsheet register (people.csv) — maps each player to their
  ESPNcricinfo player ID so the app can link to their Cricinfo profile.
* Optional enrichment (see enrich.py): batting hand / bowling style from
  ESPNcricinfo player pages, and YouTube highlight video IDs.

Output
------
site/data/male.json and site/data/female.json — everything the app needs.

Usage
-----
    python pipeline/build.py                 # download + build (last 365 days)
    python pipeline/build.py --days 730      # wider window
    python pipeline/build.py --src DIR       # use already-downloaded match JSON
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import io
import json
import os
import re
import sys
import urllib.request
import zipfile
from collections import Counter, defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE = os.path.join(ROOT, "pipeline", "cache")
OVERRIDES = os.path.join(ROOT, "pipeline", "overrides")
OUT = os.path.join(ROOT, "site", "data")

FULL_MEMBERS = [
    "Afghanistan", "Australia", "Bangladesh", "England", "India", "Ireland",
    "New Zealand", "Pakistan", "South Africa", "Sri Lanka", "West Indies",
    "Zimbabwe",
]
ZIPS = {
    "Test": "https://cricsheet.org/downloads/tests_json.zip",
    "ODI": "https://cricsheet.org/downloads/odis_json.zip",
    "T20I": "https://cricsheet.org/downloads/t20s_json.zip",
}
PEOPLE_URL = "https://cricsheet.org/register/people.csv"
FORMAT_OF = {"Test": "Test", "ODI": "ODI", "T20": "T20I", "IT20": "T20I"}
FORMATS = ["Test", "ODI", "T20I"]

BOWLER_KINDS = {"bowled", "caught", "lbw", "stumped", "caught and bowled", "hit wicket"}
NOT_OUT_KINDS = {"retired hurt", "retired not out"}

UA = "Mozilla/5.0 (playeranalyzis data builder; +https://github.com/samithadisanayaka1995/playeranalyzis)"


# --------------------------------------------------------------------------- io
def fetch(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=180) as r:
        return r.read()


def load_json(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def iter_matches(src: str | None, since: dt.date):
    """Yield (format, match_id, match_dict) for every international match on/after `since`."""
    if src:
        for name in sorted(os.listdir(src)):
            if name.endswith(".json"):
                with open(os.path.join(src, name), encoding="utf-8") as f:
                    m = json.load(f)
                fmt = FORMAT_OF.get(m["info"].get("match_type"))
                if fmt and _keep(m, since):
                    yield fmt, name[:-5], m
        return
    zdir = os.path.join(ROOT, ".zipcache")
    os.makedirs(zdir, exist_ok=True)
    for fmt, url in ZIPS.items():
        zp = os.path.join(zdir, os.path.basename(url))
        import time
        if not (os.path.exists(zp) and time.time() - os.path.getmtime(zp) < 6 * 3600):
            print(f"  downloading {url}", file=sys.stderr)
            with open(zp, "wb") as fh:
                fh.write(fetch(url))
        z = zipfile.ZipFile(zp)
        n = 0
        for name in z.namelist():
            if not name.endswith(".json"):
                continue
            m = json.loads(z.read(name))
            if FORMAT_OF.get(m["info"].get("match_type")) != fmt or not _keep(m, since):
                continue
            n += 1
            yield fmt, os.path.basename(name)[:-5], m
        print(f"    {fmt}: {n} matches in window", file=sys.stderr)


def _keep(m, since):
    info = m["info"]
    if info.get("team_type", "international") != "international":
        return False
    d = dt.date.fromisoformat(info["dates"][0])
    if d < since:
        return False
    return any(t in FULL_MEMBERS for t in info["teams"])


def load_people():
    """identifier -> {cricinfo id, unique name}."""
    path = os.path.join(CACHE, "people.csv")
    try:
        raw = fetch(PEOPLE_URL)
        with open(path, "wb") as f:
            f.write(raw)
    except Exception as e:  # offline: fall back to cached copy
        print(f"  people.csv download failed ({e}); using cache", file=sys.stderr)
        if not os.path.exists(path):
            return {}
        with open(path, "rb") as f:
            raw = f.read()
    out = {}
    for row in csv.DictReader(io.StringIO(raw.decode("utf-8"))):
        out[row["identifier"]] = {
            "ci": row.get("key_cricinfo") or None,
            "unique": row.get("unique_name") or row.get("name"),
        }
    return out


# --------------------------------------------------------------------- helpers
def phase_of(fmt: str, over: int) -> str:
    """Innings phase for an over index (0-based)."""
    if fmt == "T20I":
        return "pp" if over < 6 else ("mid" if over < 15 else "death")
    if fmt == "ODI":
        return "pp" if over < 10 else ("mid" if over < 40 else "death")
    # Tests: age of the ball
    if over < 30:
        return "new"
    if over < 80:
        return "old"
    return "new2"


PHASES = {
    "T20I": [("pp", "Powerplay (1-6)"), ("mid", "Middle (7-15)"), ("death", "Death (16-20)")],
    "ODI": [("pp", "Powerplay (1-10)"), ("mid", "Middle (11-40)"), ("death", "Death (41-50)")],
    "Test": [("new", "New ball (1-30)"), ("old", "Old ball (31-80)"), ("new2", "2nd new ball (81+)")],
}


def style_type(bowl_style: str | None) -> str | None:
    if not bowl_style:
        return None
    s = bowl_style.lower()
    if any(k in s for k in ("fast", "medium", "seam")):
        return "pace"
    if any(k in s for k in ("break", "spin", "orthodox", "googly", "chinaman", "wrist", "slow left")):
        return "spin"
    return None


def hand_of(bat_style: str | None) -> str | None:
    if not bat_style:
        return None
    s = bat_style.lower()
    return "L" if s.startswith("left") else ("R" if s.startswith("right") else None)


def ordinal(n):
    n = int(n)
    suf = "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suf}"


def result_text(info):
    o = info.get("outcome", {})
    if "winner" in o:
        by = o.get("by", {})
        if "innings" in by:
            return f"{o['winner']} won by an innings and {by.get('runs', 0)} runs"
        if "runs" in by:
            return f"{o['winner']} won by {by['runs']} run{'s' if by['runs'] != 1 else ''}"
        if "wickets" in by:
            return f"{o['winner']} won by {by['wickets']} wicket{'s' if by['wickets'] != 1 else ''}"
        if o.get("method") == "Awarded":
            return f"{o['winner']} awarded the match"
        return f"{o['winner']} won" + (f" ({o['eliminator']} super over)" if "eliminator" in o else "")
    if o.get("result") == "tie":
        return "Match tied" + (f" — {o['eliminator']} won the super over" if o.get("eliminator") else "")
    if o.get("result") == "draw":
        return "Match drawn"
    if o.get("result") == "no result":
        return "No result"
    return o.get("result", "—").capitalize()


def ratio(a, b, nd=2):
    return round(a / b, nd) if b else None


# -------------------------------------------------------------------- builders
def new_bat():
    return {
        "inns": 0, "no": 0, "runs": 0, "balls": 0, "hs": 0, "hsNo": False,
        "f50": 0, "h100": 0, "ducks": 0, "fours": 0, "sixes": 0, "dots": 0,
        "ones": 0, "outs": 0, "kinds": Counter(),
        "phase": defaultdict(lambda: [0, 0, 0]),       # runs, balls, outs
        "early": [0, 0, 0],                             # first 10 balls of innings
        "vs": defaultdict(lambda: [0, 0, 0]),           # pace/spin -> runs, balls, outs
        "pos": Counter(), "bowlers": defaultdict(lambda: [0, 0, 0]),
        "ballsToOut": [],
    }


def new_bowl():
    return {
        "inns": 0, "balls": 0, "runs": 0, "wkts": 0, "dots": 0, "fours": 0,
        "sixes": 0, "wides": 0, "nb": 0, "kinds": Counter(), "best": None,
        "phase": defaultdict(lambda: [0, 0, 0]),       # runs, balls, wkts
        "vsHand": defaultdict(lambda: [0, 0, 0]),       # L/R -> runs, balls, wkts
        "batters": defaultdict(lambda: [0, 0, 0]),      # runs, balls, outs
        "w4": 0, "w5": 0,
    }


def build(gender, matches, people, meta, highlights, keepers_manual):
    players = {}
    match_out = {}
    bat = defaultdict(dict)    # pid -> fmt -> stats
    bowl = defaultdict(dict)
    team_count = defaultdict(Counter)
    played = defaultdict(lambda: Counter())  # pid -> fmt -> matches
    dismissals = defaultdict(list)
    wicket_log = defaultdict(list)
    form = defaultdict(list)
    stumpers = set()
    # baselines per fmt: kinds counter, phase runs/balls/outs, early, dots, boundaries
    base = {f: {"kinds": Counter(), "outs": 0, "phase": defaultdict(lambda: [0, 0, 0]),
                "early": [0, 0, 0], "balls": 0, "dots": 0, "bdry": 0, "runs": 0,
                "bowlPhase": defaultdict(lambda: [0, 0, 0]), "extras": 0, "lballs": 0,
                "keeperCaught": 0} for f in FORMATS}

    def pname(reg, name):
        return reg.get(name) or ("x-" + re.sub(r"\W+", "-", name.lower()))

    # first pass: collect all keepers (stumpings) so caught-behind can be tagged
    for fmt, mid, m in matches:
        reg = m["info"].get("registry", {}).get("people", {})
        for inn in m.get("innings", []):
            for ov in inn.get("overs", []):
                for d in ov["deliveries"]:
                    for w in d.get("wickets", []):
                        if w["kind"] == "stumped":
                            for fl in w.get("fielders", []):
                                if fl.get("name"):
                                    stumpers.add(pname(reg, fl["name"]))
    keepers = stumpers | keepers_manual
    for pid, mt in meta.items():
        if "keeper" in (mt.get("role") or "").lower():
            keepers.add(pid)

    def ptype(pid):
        return style_type((meta.get(pid) or {}).get("bowl"))

    def phand(pid):
        return hand_of((meta.get(pid) or {}).get("bat"))

    for fmt, mid, m in sorted(matches, key=lambda x: x[2]["info"]["dates"][0]):
        info = m["info"]
        reg = info.get("registry", {}).get("people", {})
        teams = info["teams"]
        date = info["dates"][0]
        ev = info.get("event", {}) or {}
        squads = {}
        for team, names in info.get("players", {}).items():
            squads[team] = []
            for n in names:
                pid = pname(reg, n)
                squads[team].append(pid)
                team_count[pid][team] += 1
                played[pid][fmt] += 1
                if pid not in players:
                    pe = people.get(pid, {})
                    players[pid] = {"id": pid, "name": n, "ci": pe.get("ci")}
                players[pid]["name"] = n  # latest spelling
        mno = ev.get("match_number")
        q = f"{teams[0]} vs {teams[1]}{' Women' if gender == 'female' else ''} " \
            f"{(ordinal(mno) + ' ') if mno else ''}{fmt} {date[:4]} highlights"
        hl = highlights.get(mid, {})
        mo = {
            "id": mid, "date": date, "dates": info["dates"], "fmt": fmt, "teams": teams,
            "venue": info.get("venue"), "city": info.get("city"),
            "event": ev.get("name"), "mno": mno, "stage": ev.get("stage"),
            "result": result_text(info), "winner": info.get("outcome", {}).get("winner"),
            "toss": info.get("toss"),
            "pom": [pname(reg, n) for n in info.get("player_of_match", [])],
            "squads": squads, "hlq": q, "hl": hl.get("vid"), "hlTitle": hl.get("title"),
            "inns": [], "wkts": [],
        }

        # per-match innings tracking
        bat_match = defaultdict(lambda: {"runs": 0, "balls": 0})  # (inn, pid)
        bowl_match = defaultdict(lambda: [0, 0])                  # (inn, pid) runs, wkts
        bowled_in = set()

        for ii, inn in enumerate(m.get("innings", [])):
            if inn.get("super_over"):
                continue
            team = inn["team"]
            order = []
            total = wk = legal = 0
            for ov in inn.get("overs", []):
                over = ov["over"]
                ph = phase_of(fmt, over)
                for bi, d in enumerate(ov["deliveries"]):
                    b = pname(reg, d["batter"])
                    ns = pname(reg, d["non_striker"])
                    bw = pname(reg, d["bowler"])
                    for p in (b, ns):
                        if p not in order:
                            order.append(p)
                    r = d["runs"]
                    ex = d.get("extras", {})
                    wide = "wides" in ex
                    nb = "noballs" in ex
                    total += r["total"]
                    if not (wide or nb):
                        legal += 1
                    # ---- batting
                    bs = bat[b].setdefault(fmt, new_bat())
                    key = (ii, b)
                    if not wide:
                        bs["balls"] += 1
                        bat_match[key]["balls"] += 1
                        bs["runs"] += r["batter"]
                        bat_match[key]["runs"] += r["batter"]
                        if r["batter"] == 0:
                            bs["dots"] += 1
                        if r["batter"] == 1:
                            bs["ones"] += 1
                        if r["batter"] == 4 and not r.get("non_boundary"):
                            bs["fours"] += 1
                        if r["batter"] == 6:
                            bs["sixes"] += 1
                        bs["phase"][ph][0] += r["batter"]
                        bs["phase"][ph][1] += 1
                        if bat_match[key]["balls"] <= 10:
                            bs["early"][0] += r["batter"]
                            bs["early"][1] += 1
                        t = ptype(bw)
                        if t:
                            bs["vs"][t][0] += r["batter"]
                            bs["vs"][t][1] += 1
                        bs["bowlers"][bw][0] += r["batter"]
                        bs["bowlers"][bw][1] += 1
                        B = base[fmt]
                        B["balls"] += 1
                        B["runs"] += r["batter"]
                        B["phase"][ph][0] += r["batter"]
                        B["phase"][ph][1] += 1
                        if r["batter"] == 0:
                            B["dots"] += 1
                        if r["batter"] in (4, 6):
                            B["bdry"] += 1
                        if bat_match[key]["balls"] <= 10:
                            B["early"][0] += r["batter"]
                            B["early"][1] += 1
                    # ---- bowling
                    os_ = bowl[bw].setdefault(fmt, new_bowl())
                    bowled_in.add((ii, bw))
                    conceded = r["batter"] + ex.get("wides", 0) + ex.get("noballs", 0)
                    os_["runs"] += conceded
                    bowl_match[(ii, bw)][0] += conceded
                    os_["phase"][ph][0] += conceded
                    base[fmt]["bowlPhase"][ph][0] += conceded
                    if wide:
                        os_["wides"] += 1
                    if nb:
                        os_["nb"] += 1
                    if wide or nb:
                        base[fmt]["extras"] += 1
                    if not (wide or nb):
                        os_["balls"] += 1
                        os_["phase"][ph][1] += 1
                        base[fmt]["bowlPhase"][ph][1] += 1
                        base[fmt]["lballs"] += 1
                        if conceded == 0:
                            os_["dots"] += 1
                    if r["batter"] == 4 and not r.get("non_boundary"):
                        os_["fours"] += 1
                    if r["batter"] == 6:
                        os_["sixes"] += 1
                    if not wide:
                        h = phand(b)
                        if h:
                            os_["vsHand"][h][0] += r["batter"]
                            os_["vsHand"][h][1] += 0 if nb else 1
                        os_["batters"][b][0] += r["batter"]
                        os_["batters"][b][1] += 0 if nb else 1
                    # ---- wickets
                    for w in d.get("wickets", []):
                        kind = w["kind"]
                        out = pname(reg, w["player_out"])
                        if kind in NOT_OUT_KINDS:
                            continue
                        wk += 1
                        fl = [pname(reg, f["name"]) for f in w.get("fielders", []) if f.get("name")]
                        kd = kind
                        if kind == "caught" and fl and fl[0] in keepers:
                            kd = "caught behind"
                        ob = bat[out].setdefault(fmt, new_bat())
                        ob["outs"] += 1
                        ob["kinds"][kd] += 1
                        okey = (ii, out)
                        obb = bat_match[okey]["balls"]
                        ob["ballsToOut"].append(obb)
                        B = base[fmt]
                        B["outs"] += 1
                        B["kinds"][kd] += 1
                        if kind in BOWLER_KINDS:
                            ob["phase"][ph][2] += 1
                            B["phase"][ph][2] += 1
                            if obb <= 10:
                                ob["early"][2] += 1
                                B["early"][2] += 1
                            t = ptype(bw)
                            if t and out == b:
                                ob["vs"][t][2] += 1
                            ob["bowlers"][bw][2] += 1
                            os_["wkts"] += 1
                            os_["kinds"][kd] += 1
                            os_["phase"][ph][2] += 1
                            base[fmt]["bowlPhase"][ph][2] += 1
                            bowl_match[(ii, bw)][1] += 1
                            h = phand(out)
                            if h:
                                os_["vsHand"][h][2] += 1
                            os_["batters"][out][2] += 1
                        elif obb <= 10:
                            ob["early"][2] += 1
                            B["early"][2] += 1
                        ov_str = f"{over}.{_ball_no(ov['deliveries'], bi)}"
                        score = f"{total}/{wk}"
                        rec = {
                            "m": mid, "fmt": fmt, "date": date, "inn": ii + 1, "ov": ov_str,
                            "kind": kd, "bat": out, "bowl": bw if kind in BOWLER_KINDS else None,
                            "fld": fl[0] if fl else None, "r": bat_match[okey]["runs"],
                            "b": obb, "score": score,
                            "opp": teams[1] if team == teams[0] else teams[0],
                        }
                        mo["wkts"].append(rec)
                        dismissals[out].append(rec)
                        if kind in BOWLER_KINDS:
                            wicket_log[bw].append(rec)
            mo["inns"].append({
                "team": team, "runs": total, "wkts": wk,
                "overs": f"{legal // 6}.{legal % 6}" if legal % 6 else f"{legal // 6}",
                "decl": bool(inn.get("declared")),
                "target": (inn.get("target") or {}).get("runs"),
            })
            # innings-level batting tallies
            outs_this = {w["bat"] for w in mo["wkts"] if w["inn"] == ii + 1}
            for pos, p in enumerate(order, 1):
                bm = bat_match.get((ii, p))
                if bm is None:
                    bm = {"runs": 0, "balls": 0}
                bs = bat[p].setdefault(fmt, new_bat())
                bs["inns"] += 1
                bs["pos"][pos] += 1
                out = p in outs_this
                if not out:
                    bs["no"] += 1
                rr = bm["runs"]
                if rr > bs["hs"] or (rr == bs["hs"] and not out):
                    bs["hs"], bs["hsNo"] = rr, not out
                if rr >= 100:
                    bs["h100"] += 1
                elif rr >= 50:
                    bs["f50"] += 1
                if rr == 0 and out:
                    bs["ducks"] += 1
                form[p].append({"m": mid, "fmt": fmt, "date": date, "r": rr, "b": bm["balls"],
                                "out": out, "opp": teams[1] if team == teams[0] else teams[0]})
        for (ii, bw), (rr, ww) in bowl_match.items():
            os_ = bowl[bw][fmt]
            os_["inns"] += 1
            if ww >= 5:
                os_["w5"] += 1
            elif ww >= 4:
                os_["w4"] += 1
            if os_["best"] is None or ww > os_["best"][0] or (ww == os_["best"][0] and rr < os_["best"][1]):
                os_["best"] = [ww, rr]
        match_out[mid] = mo

    # ----------------------------------------------------------- finalise
    baselines = {}
    for f in FORMATS:
        B = base[f]
        if not B["balls"]:
            continue
        bl = {
            "sr": ratio(B["runs"] * 100, B["balls"], 1),
            "dot": ratio(B["dots"] * 100, B["balls"], 1),
            "bdry": ratio(B["bdry"] * 100, B["balls"], 1),
            "kinds": {k: ratio(v * 100, B["outs"], 1) for k, v in B["kinds"].items()},
            "phase": {p: {"sr": ratio(v[0] * 100, v[1], 1), "avg": ratio(v[0], v[2], 1)} for p, v in B["phase"].items()},
            "bowlPhase": {p: {"econ": ratio(v[0] * 6, v[1], 2), "sr": ratio(v[1], v[2], 1)} for p, v in B["bowlPhase"].items()},
            "earlyAvg": ratio(B["early"][0], B["early"][2], 1),
            "earlyOutShare": ratio(B["early"][2] * 100, B["outs"], 1),
            "extras": ratio(B["extras"] * 100, B["lballs"], 2),
        }
        tot = B["bowlPhase"]
        r_, b_, w_ = (sum(v[i] for v in tot.values()) for i in range(3))
        bl["econ"] = ratio(r_ * 6, b_, 2)
        bl["bowlSr"] = ratio(b_, w_, 1)
        bl["bowlAvg"] = ratio(r_, w_, 1)
        baselines[f] = bl

    out_players = {}
    for pid, p in players.items():
        team = team_count[pid].most_common(1)[0][0]
        if team not in FULL_MEMBERS:
            continue
        mt = meta.get(pid, {})
        rec = {
            "id": pid, "name": p["name"], "team": team, "ci": p["ci"],
            "full": mt.get("full"), "role": mt.get("role"),
            "batStyle": mt.get("bat"), "bowlStyle": mt.get("bowl"),
            "type": style_type(mt.get("bowl")), "keeper": pid in keepers,
            "m": dict(played[pid]), "bat": {}, "bowl": {}, "ins": {},
        }
        for f, s in bat.get(pid, {}).items():
            if s["inns"] == 0:
                continue
            rec["bat"][f] = finish_bat(s, f)
        for f, s in bowl.get(pid, {}).items():
            if s["balls"] == 0:
                continue
            rec["bowl"][f] = finish_bowl(s)
        for f in FORMATS:
            if f in baselines and (f in rec["bat"] or f in rec["bowl"]):
                rec["ins"][f] = insights(rec, f, baselines[f], players, rec["bat"].get(f), rec["bowl"].get(f), bat[pid].get(f), bowl[pid].get(f))
        rec["dis"] = dismissals.get(pid, [])
        rec["wk"] = wicket_log.get(pid, [])
        rec["form"] = form.get(pid, [])[-15:][::-1]
        out_players[pid] = rec

    # Lean names map for players that are referenced but not full-member (opponents)
    names = {pid: p["name"] for pid, p in players.items()}
    teams = sorted({p["team"] for p in out_players.values()})
    return {
        "gender": gender, "teams": teams, "baselines": baselines, "phases": PHASES,
        "players": out_players, "matches": match_out, "names": names,
    }


def _ball_no(deliveries, idx):
    """Legal ball number within the over for display (e.g. 12.3)."""
    n = 0
    for d in deliveries[: idx + 1]:
        ex = d.get("extras", {})
        if "wides" not in ex and "noballs" not in ex:
            n += 1
    return max(n, 1) if idx < len(deliveries) else n


def _bowler_split(stats):
    """Top bowlers who dismissed / troubled a batter."""
    rows = []
    for bw, (r, b, o) in stats.items():
        if o or b >= 24:
            rows.append({"p": bw, "r": r, "b": b, "o": o, "avg": ratio(r, o, 1), "sr": ratio(r * 100, b, 1)})
    rows.sort(key=lambda x: (-x["o"], x["r"] / max(x["b"], 1)))
    return rows[:8]


def finish_bat(s, f):
    outs = s["inns"] - s["no"]
    phase = {k: {"r": v[0], "b": v[1], "o": v[2], "sr": ratio(v[0] * 100, v[1], 1), "avg": ratio(v[0], v[2], 1)}
             for k, v in s["phase"].items()}
    vs = {k: {"r": v[0], "b": v[1], "o": v[2], "sr": ratio(v[0] * 100, v[1], 1), "avg": ratio(v[0], v[2], 1)}
          for k, v in s["vs"].items()}
    return {
        "inns": s["inns"], "no": s["no"], "runs": s["runs"], "balls": s["balls"],
        "hs": f"{s['hs']}{'*' if s['hsNo'] else ''}", "hsN": s["hs"],
        "avg": ratio(s["runs"], outs, 2), "sr": ratio(s["runs"] * 100, s["balls"], 2),
        "f50": s["f50"], "h100": s["h100"], "ducks": s["ducks"], "fours": s["fours"],
        "sixes": s["sixes"], "dot": ratio(s["dots"] * 100, s["balls"], 1),
        "bdry": ratio((s["fours"] + s["sixes"]) * 100, s["balls"], 1),
        "kinds": dict(s["kinds"]), "outs": outs, "phase": phase, "vs": vs,
        "early": {"r": s["early"][0], "b": s["early"][1], "o": s["early"][2],
                  "avg": ratio(s["early"][0], s["early"][2], 1)},
        "pos": dict(s["pos"]),
        "bowlers": _bowler_split(s["bowlers"]),
        "bpd": ratio(sum(s["ballsToOut"]), len(s["ballsToOut"]), 1),
    }


def finish_bowl(s):
    phase = {k: {"r": v[0], "b": v[1], "w": v[2], "econ": ratio(v[0] * 6, v[1], 2), "sr": ratio(v[1], v[2], 1)}
             for k, v in s["phase"].items()}
    hand = {k: {"r": v[0], "b": v[1], "w": v[2], "econ": ratio(v[0] * 6, v[1], 2), "avg": ratio(v[0], v[2], 1)}
            for k, v in s["vsHand"].items()}
    vict = sorted(([b, v] for b, v in s["batters"].items() if v[2]), key=lambda x: -x[1][2])[:6]
    pun = sorted(([b, v] for b, v in s["batters"].items() if v[1] >= 18),
                 key=lambda x: -(x[1][0] * 100 / x[1][1]))[:6]
    return {
        "inns": s["inns"], "balls": s["balls"], "overs": f"{s['balls'] // 6}.{s['balls'] % 6}" if s["balls"] % 6 else f"{s['balls'] // 6}",
        "runs": s["runs"], "wkts": s["wkts"], "econ": ratio(s["runs"] * 6, s["balls"], 2),
        "avg": ratio(s["runs"], s["wkts"], 2), "sr": ratio(s["balls"], s["wkts"], 1),
        "dot": ratio(s["dots"] * 100, s["balls"], 1),
        "bdry": ratio((s["fours"] + s["sixes"]) * 100, s["balls"], 1),
        "wides": s["wides"], "nb": s["nb"], "extras": ratio((s["wides"] + s["nb"]) * 100, s["balls"], 2),
        "best": f"{s['best'][0]}/{s['best'][1]}" if s["best"] else None,
        "w4": s["w4"], "w5": s["w5"], "kinds": dict(s["kinds"]), "phase": phase, "hand": hand,
        "victims": [{"p": b, "o": v[2], "r": v[0], "b": v[1]} for b, v in vict],
        "punishers": [{"p": b, "r": v[0], "b": v[1], "o": v[2], "sr": ratio(v[0] * 100, v[1], 1)} for b, v in pun],
    }


# ------------------------------------------------------------------ insights
def insights(rec, f, bl, players, b, w, braw, wraw):
    """Rule-based strengths / weaknesses with the evidence for each."""
    out = {"bat": {"s": [], "w": []}, "bowl": {"s": [], "w": []}}
    phases = dict(PHASES[f])
    limited = f != "Test"
    nm = lambda pid: players.get(pid, {}).get("name", pid)

    if b and b["inns"] >= 3:
        S, W = out["bat"]["s"], out["bat"]["w"]
        outs = b["outs"]
        k = b["kinds"]

        def share(*kinds):
            return 100 * sum(k.get(x, 0) for x in kinds) / outs if outs else 0

        def bshare(*kinds):
            return sum(bl["kinds"].get(x, 0) for x in kinds)

        if outs >= 5:
            s_bl, base_bl = share("bowled", "lbw"), bshare("bowled", "lbw")
            if s_bl >= 30 and s_bl >= 1.35 * base_bl:
                W.append(("Attacked at the stumps",
                          f"{s_bl:.0f}% of dismissals are bowled or LBW ({base_bl:.0f}% is typical in {f}s). "
                          "Full, straight deliveries and balls nipping back in are the danger — likely issues with "
                          "the front pad / playing across the line."))
            s_cb, base_cb = share("caught behind"), bshare("caught behind")
            if s_cb >= 25 and s_cb >= 1.35 * base_cb:
                W.append(("Edges behind the wicket",
                          f"{s_cb:.0f}% of dismissals are caught by the keeper ({base_cb:.0f}% typical). "
                          "Vulnerable to deliveries in the channel outside off stump that move away."))
            s_c, base_c = share("caught", "caught and bowled"), bshare("caught", "caught and bowled")
            if s_c >= 55 and s_c >= 1.25 * base_c:
                W.append(("Caught in the field",
                          f"{s_c:.0f}% of dismissals are caught by fielders ({base_c:.0f}% typical) — "
                          "gets out to aerial/attacking shots; bowlers set traps in the deep or at catching positions."))
            s_st = share("stumped")
            if k.get("stumped", 0) >= 2 and s_st >= 15:
                W.append(("Stumped against spin",
                          f"Stumped {k['stumped']} times ({s_st:.0f}% of dismissals) — gets drawn down the pitch "
                          "and beaten by flight or turn."))
            if k.get("run out", 0) >= 2 and share("run out") >= 15:
                W.append(("Run-out risk",
                          f"Run out {k['run out']} times ({share('run out'):.0f}% of dismissals) — "
                          "running between the wickets is a weak point."))
            if outs >= 6 and bl.get("earlyOutShare") and b["early"]["o"] >= 3:
                es = 100 * b["early"]["o"] / outs
                if es >= 1.3 * bl["earlyOutShare"] and es >= 35:
                    W.append(("Vulnerable early",
                              f"{es:.0f}% of dismissals come within the first 10 balls "
                              f"({bl['earlyOutShare']:.0f}% typical); averages {b['early']['avg'] or 0} in that period. "
                              "Bowl at them hard before they settle."))
                elif b["early"]["o"] <= 1 and outs >= 6 and es < 0.5 * bl["earlyOutShare"]:
                    S.append(("Rarely out early",
                              f"Only {b['early']['o']} of {outs} dismissals in the first 10 balls — "
                              "sound start to innings."))

        # pace vs spin
        vs = b.get("vs", {})
        pc, sp = vs.get("pace"), vs.get("spin")
        if pc and sp and pc["b"] >= 60 and sp["b"] >= 60:
            pa, sa = pc["avg"] or pc["r"], sp["avg"] or sp["r"]
            if limited:
                if sp["sr"] < 0.8 * pc["sr"]:
                    W.append(("Slows down against spin",
                              f"Strike rate {sp['sr']} vs spin compared with {pc['sr']} vs pace."))
                elif pc["sr"] < 0.8 * sp["sr"]:
                    W.append(("Slows down against pace",
                              f"Strike rate {pc['sr']} vs pace compared with {sp['sr']} vs spin."))
            if sp["o"] >= 3 and sa < 0.65 * pa:
                W.append(("Struggles against spin",
                          f"Averages {sp['avg']} vs spin ({sp['o']} dismissals) against {pc['avg'] or '∞'} vs pace."))
            elif pc["o"] >= 3 and pa < 0.65 * sa:
                W.append(("Struggles against pace",
                          f"Averages {pc['avg']} vs pace ({pc['o']} dismissals) against {sp['avg'] or '∞'} vs spin."))
            if sp["sr"] >= 1.2 * pc["sr"] and limited and sp["b"] >= 90:
                S.append(("Dominates spin", f"Strike rate {sp['sr']} vs spin ({pc['sr']} vs pace)."))
            elif pc["sr"] >= 1.2 * sp["sr"] and limited and pc["b"] >= 90:
                S.append(("Strong against pace", f"Strike rate {pc['sr']} vs pace ({sp['sr']} vs spin)."))

        # phases
        for ph, v in b["phase"].items():
            bp = bl["phase"].get(ph, {})
            if v["b"] < (60 if limited else 240) or not bp.get("sr"):
                continue
            if limited:
                if v["sr"] >= 1.15 * bp["sr"]:
                    S.append((f"Fast scorer: {phases[ph]}",
                              f"Strike rate {v['sr']} in this phase ({bp['sr']} typical)."))
                elif v["sr"] <= 0.8 * bp["sr"]:
                    W.append((f"Slow scoring: {phases[ph]}",
                              f"Strike rate {v['sr']} in this phase ({bp['sr']} typical)."))
            else:
                if v["o"] >= 3 and bp.get("avg") and v["avg"] and v["avg"] < 0.6 * bp["avg"]:
                    W.append((f"Struggles vs the {phases[ph].split(' (')[0].lower()}",
                              f"Averages {v['avg']} in this phase ({bp['avg']} typical)."))
                elif v["o"] >= 2 and bp.get("avg") and v["avg"] and v["avg"] > 1.6 * bp["avg"]:
                    S.append((f"Scores heavily vs the {phases[ph].split(' (')[0].lower()}",
                              f"Averages {v['avg']} in this phase ({bp['avg']} typical)."))

        if b["balls"] >= (100 if limited else 300):
            if b["dot"] and bl["dot"] and b["dot"] >= bl["dot"] + 8:
                W.append(("Dot-ball pressure",
                          f"{b['dot']}% dot balls ({bl['dot']}% typical) — struggles to rotate strike, which builds pressure."))
            elif b["dot"] and bl["dot"] and b["dot"] <= bl["dot"] - 8:
                S.append(("Rotates strike well", f"Only {b['dot']}% dot balls ({bl['dot']}% typical)."))
            if b["bdry"] and bl["bdry"] and b["bdry"] >= 1.4 * bl["bdry"]:
                S.append(("Boundary hitter",
                          f"Hits a boundary every {round(100 / b['bdry'], 1)} balls "
                          f"({b['fours']}×4, {b['sixes']}×6)."))
        if b["avg"] and b["inns"] >= 5:
            if f == "Test" and b["avg"] >= 45 or f == "ODI" and b["avg"] >= 45 or f == "T20I" and b["avg"] >= 35 and (b["sr"] or 0) >= 130:
                S.append(("High-value run scorer", f"Averages {b['avg']} at a strike rate of {b['sr']}."))
        if b["f50"] + b["h100"] >= 3:
            conv = b["h100"] / (b["f50"] + b["h100"])
            if f != "T20I":
                if conv >= 0.4:
                    S.append(("Converts starts", f"{b['h100']} hundreds from {b['f50'] + b['h100']} scores of 50+."))
                elif b["h100"] == 0 and b["f50"] >= 4:
                    W.append(("Doesn't convert fifties", f"{b['f50']} fifties but no hundred in this period."))
        if b["ducks"] >= 3 and b["ducks"] / b["inns"] >= 0.2:
            W.append(("Frequent ducks", f"{b['ducks']} ducks in {b['inns']} innings."))
        nem = [x for x in b["bowlers"] if x["o"] >= 2]
        if nem:
            x = nem[0]
            W.append(("Nemesis bowler",
                      f"Dismissed {x['o']} times by {nm(x['p'])} ({x['r']} runs off {x['b']} balls)."))

    if w and w["balls"] >= (90 if limited else 300):
        S, Wk = out["bowl"]["s"], out["bowl"]["w"]
        if w["econ"] and bl["econ"]:
            if w["econ"] <= 0.88 * bl["econ"]:
                S.append(("Economical", f"Economy {w['econ']} ({bl['econ']} typical in {f}s)."))
            elif w["econ"] >= 1.15 * bl["econ"]:
                Wk.append(("Expensive", f"Economy {w['econ']} ({bl['econ']} typical)."))
        if w["sr"] and bl["bowlSr"] and w["wkts"] >= 5:
            if w["sr"] <= 0.75 * bl["bowlSr"]:
                S.append(("Strike bowler", f"Takes a wicket every {w['sr']} balls ({bl['bowlSr']} typical)."))
            elif w["sr"] >= 1.4 * bl["bowlSr"]:
                Wk.append(("Lacks wicket-taking threat", f"A wicket every {w['sr']} balls ({bl['bowlSr']} typical)."))
        elif w["wkts"] <= 1 and w["balls"] >= 180:
            Wk.append(("Lacks wicket-taking threat", f"{w['wkts']} wicket(s) from {w['overs']} overs."))
        for ph, v in w["phase"].items():
            bp = bl["bowlPhase"].get(ph, {})
            if v["b"] < (60 if limited else 240) or not bp.get("econ"):
                continue
            if v["econ"] <= 0.85 * bp["econ"]:
                S.append((f"Tight in the {phases[ph].split(' (')[0].lower()}",
                          f"Economy {v['econ']} ({bp['econ']} typical)" + (f", {v['w']} wickets." if v["w"] else ".")))
            elif v["econ"] >= 1.15 * bp["econ"]:
                Wk.append((f"Leaks runs in the {phases[ph].split(' (')[0].lower()}",
                           f"Economy {v['econ']} ({bp['econ']} typical)."))
            if v["w"] >= 4 and v["sr"] and bp.get("sr") and v["sr"] <= 0.7 * bp["sr"]:
                S.append((f"Wicket-taker: {phases[ph]}", f"{v['w']} wickets, one every {v['sr']} balls."))
        if w["wkts"] >= 6:
            k = w["kinds"]
            bl_share = 100 * (k.get("bowled", 0) + k.get("lbw", 0)) / w["wkts"]
            if bl_share >= 40:
                S.append(("Attacks the stumps",
                          f"{bl_share:.0f}% of wickets bowled or LBW — accurate, straight lines."))
            cb = 100 * k.get("caught behind", 0) / w["wkts"]
            if cb >= 25:
                S.append(("Finds the edge", f"{cb:.0f}% of wickets caught by the keeper — gets movement/bounce outside off."))
            if k.get("stumped", 0) >= 2:
                S.append(("Beats batters in flight", f"{k['stumped']} stumpings."))
        if w["dot"] and limited and bl.get("econ"):
            if w["dot"] >= 50 and f == "T20I" or w["dot"] >= 60 and f == "ODI":
                S.append(("Builds dot-ball pressure", f"{w['dot']}% dot balls."))
        if w["extras"] and bl.get("extras") and w["extras"] >= max(2 * bl["extras"], 4):
            Wk.append(("Discipline: wides & no-balls",
                       f"{w['wides']} wides and {w['nb']} no-balls ({w['extras']} per 100 balls; {bl['extras']} typical)."))
        if w["bdry"] and limited and f == "T20I" and w["bdry"] >= 20:
            Wk.append(("Boundary ball", f"Concedes a boundary every {round(100 / w['bdry'], 1)} balls."))
        h = w.get("hand", {})
        L, R = h.get("L"), h.get("R")
        if L and R and L["b"] >= 60 and R["b"] >= 60:
            if L["econ"] >= 1.25 * R["econ"]:
                Wk.append(("Struggles vs left-handers", f"Economy {L['econ']} vs LHB, {R['econ']} vs RHB."))
            elif R["econ"] >= 1.25 * L["econ"]:
                Wk.append(("Struggles vs right-handers", f"Economy {R['econ']} vs RHB, {L['econ']} vs LHB."))
        if w["punishers"]:
            x = w["punishers"][0]
            if x["sr"] and x["b"] >= 24 and x["sr"] >= (180 if f == "T20I" else 120 if f == "ODI" else 80):
                Wk.append(("Targeted by", f"{nm(x['p'])} scored {x['r']} off {x['b']} balls (SR {x['sr']})."))
    return out


# ---------------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=365)
    ap.add_argument("--src", help="directory of Cricsheet match JSON files (skip download)")
    ap.add_argument("--today", help="override today's date (YYYY-MM-DD)")
    args = ap.parse_args()
    today = dt.date.fromisoformat(args.today) if args.today else dt.date.today()
    since = today - dt.timedelta(days=args.days)
    print(f"Building data for matches since {since}", file=sys.stderr)

    people = load_people()
    meta = load_json(os.path.join(CACHE, "player_meta.json"), {})
    highlights = load_json(os.path.join(CACHE, "highlights.json"), {})
    # manual overrides beat scraped meta
    ovr_path = os.path.join(OVERRIDES, "player_styles.csv")
    keepers_manual = set()
    if os.path.exists(ovr_path):
        with open(ovr_path, encoding="utf-8") as fh:
            for row in csv.DictReader(fh):
                pid = row.get("id")
                if not pid:
                    continue
                d = meta.setdefault(pid, {})
                for k in ("bat", "bowl", "role"):
                    if row.get(k):
                        d[k] = row[k]
                if (row.get("keeper") or "").strip().lower() in ("1", "y", "yes", "true"):
                    keepers_manual.add(pid)
    hl_ovr = os.path.join(OVERRIDES, "highlights.csv")
    if os.path.exists(hl_ovr):
        with open(hl_ovr, encoding="utf-8") as fh:
            for row in csv.DictReader(fh):
                if row.get("match_id") and row.get("video_id"):
                    highlights[row["match_id"]] = {"vid": row["video_id"], "title": row.get("title") or None}

    by_gender = defaultdict(list)
    for fmt, mid, m in iter_matches(args.src, since):
        by_gender[m["info"].get("gender", "male")].append((fmt, mid, m))

    os.makedirs(OUT, exist_ok=True)
    summary = {}
    for g in ("male", "female"):
        data = build(g, by_gender.get(g, []), people, meta, highlights, keepers_manual)
        data["generated"] = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
        data["window"] = {"from": since.isoformat(), "to": today.isoformat()}
        with open(os.path.join(OUT, f"{g}.json"), "w", encoding="utf-8") as f:
            json.dump(data, f, separators=(",", ":"), ensure_ascii=False)
        summary[g] = {"matches": len(data["matches"]), "players": len(data["players"])}
        print(f"  {g}: {summary[g]}", file=sys.stderr)

    # list of player/match ids for the enrichment step
    with open(os.path.join(CACHE, "todo.json"), "w", encoding="utf-8") as f:
        todo = {"players": {}, "matches": {}}
        for g in ("male", "female"):
            d = load_json(os.path.join(OUT, f"{g}.json"), {})
            for pid, p in d.get("players", {}).items():
                todo["players"][pid] = {"name": p["name"], "ci": p["ci"]}
            for mid, m in d.get("matches", {}).items():
                todo["matches"][mid] = {"q": m["hlq"], "date": m["date"], "teams": m["teams"], "fmt": m["fmt"], "g": g}
        json.dump(todo, f)
    with open(os.path.join(OUT, "meta.json"), "w") as f:
        json.dump({"generated": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
                   "window": {"from": since.isoformat(), "to": today.isoformat()}, "summary": summary}, f)


if __name__ == "__main__":
    main()
