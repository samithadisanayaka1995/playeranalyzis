# Cricket Player Analyzer

A web app that analyses the performance, **strong areas** and **weak areas** of international cricketers — men's and women's, in Tests, ODIs and T20Is — over the last 12 months, with a highlights link for every match.

**Live app:** https://samithadisanayaka1995.github.io/playeranalyzis/

## What's in it

| View | What you can do |
|---|---|
| **Batters** | Sort by runs, average, strike rate, highest score, 50s/100s, 4s/6s, dot-ball %. Filter by country and minimum innings. Each row shows the player's main weakness. |
| **Bowlers** | Sort by wickets, economy, average, strike rate, best figures, dot-ball %. Filter by country. |
| **All players** | Every player who played for a full-member nation, sortable by name, country, role, batting/bowling style and matches per format. |
| **Countries** | Each team's record, top run-scorer and wicket-taker; click through for the squad's batting and bowling tables and match list. |
| **Matches** | Every match with result, venue, playing XIs, innings totals, fall of wickets and the YouTube highlights. |
| **Player page** | Stats per format, recent form, strengths & weaknesses, how they get out (vs the typical share), scoring by phase, pace vs spin, first-10-balls vulnerability, bowlers who trouble them, and a log of **every dismissal with a link to that match's highlights**. Bowlers get the bowling equivalent: how they take wickets, economy by phase, vs left/right-handers, favourite victims, batters who attack them, and every wicket. |

Use the **Men / Women** and **Test / ODI / T20I** switches at the top; search finds any player.

## How the analysis works

The analysis is built from **ball-by-ball data** for every delivery of every match, so it is based on what actually happened rather than opinion:

- **How they got out** — dismissal type, bowler, fielder, over, score and the batter's runs/balls, for every dismissal. Catches by a wicketkeeper are shown as *caught behind*.
- **Weak areas (batters)** — flagged when a player's numbers are clearly worse than the typical international player in that format, e.g. a high share of bowled/LBW (attacked at the stumps), caught behind (edges outside off), stumpings (drawn out vs spin), run-outs, many dismissals in the first 10 balls, slow scoring in a phase, a high dot-ball %, struggles vs pace or spin, frequent ducks, a bowler who keeps getting them out.
- **Strong areas (batters)** — fast scoring in a phase, dominance vs pace/spin, strike rotation, boundary hitting, converting fifties into hundreds, rarely out early.
- **Bowlers** — economy and wicket-taking vs typical, phase-by-phase economy (powerplay / middle / death, or new/old ball in Tests), wicket types, wides/no-balls, boundary balls, vs left- and right-handers, batters who target them.

These are statistical inferences, not ball-tracking: the data records *what happened* on each ball, not the line, length or shot played. Watch the linked highlights to see the dismissals themselves.

## Data sources

- **Matches, squads, ball-by-ball:** [Cricsheet](https://cricsheet.org) — open data that records every international scorecard (as published on ESPNcricinfo) delivery by delivery.
- **Player links:** each player links to their **ESPNcricinfo** profile via the Cricsheet register.
- **Batting hand / bowling style / role:** Wikipedia infoboxes, matched exactly through the ESPNcricinfo player ID stored in Wikidata. (ESPNcricinfo blocks automated downloads, so it can't be read directly.) Fix any mistake in `pipeline/overrides/player_styles.csv`.
- **Highlights:** YouTube. Every match links to a YouTube search for its highlights. To embed the actual video, add a free YouTube Data API key as a repository secret named `YOUTUBE_API_KEY` (Settings → Secrets and variables → Actions); the daily update then finds up to ~90 videos a day until every match has one. You can also pin a video by hand in `pipeline/overrides/highlights.csv`.

**Known gap:** Cricsheet does not currently publish Afghanistan's matches, so Afghanistan is missing.

## How it updates

`.github/workflows/update-and-deploy.yml` runs every day (and on every push):

1. `pipeline/build.py` downloads the latest Cricsheet data and builds `site/data/male.json` and `site/data/female.json`.
2. `pipeline/enrich.py` adds player styles and highlight videos (cached in `pipeline/cache/`).
3. The data is rebuilt, committed, and the `site/` folder is deployed to GitHub Pages.

You can also run it by hand: **Actions → Update data & deploy app → Run workflow** (optionally with a different number of days).

## Run locally

```bash
python pipeline/build.py           # needs internet access to cricsheet.org
python pipeline/enrich.py          # optional
python pipeline/build.py
cd site && python -m http.server 8000   # open http://localhost:8000
```

No dependencies beyond Python 3.10+; the site is plain HTML/CSS/JS with no build step.
