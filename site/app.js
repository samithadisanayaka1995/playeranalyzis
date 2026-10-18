/* Cricket Player Analyzer — single-page app (no build step). */
(() => {
  "use strict";

  const FORMATS = ["Test", "ODI", "T20I"];
  const TEAM = {
    "Afghanistan": ["AFG", "#1b4fa0"], "Australia": ["AUS", "#d8a400"], "Bangladesh": ["BAN", "#006a4e"],
    "England": ["ENG", "#1d3c78"], "India": ["IND", "#1f6fd1"], "Ireland": ["IRE", "#169b62"],
    "New Zealand": ["NZ", "#222"], "Pakistan": ["PAK", "#01411c"], "South Africa": ["SA", "#007749"],
    "Sri Lanka": ["SL", "#0b2f80"], "West Indies": ["WI", "#7b0b2a"], "Zimbabwe": ["ZIM", "#c8102e"],
  };
  const KIND_LABEL = {
    "caught": "Caught (fielder)", "caught behind": "Caught behind", "bowled": "Bowled", "lbw": "LBW",
    "run out": "Run out", "stumped": "Stumped", "caught and bowled": "Caught & bowled",
    "hit wicket": "Hit wicket", "retired out": "Retired out", "obstructing the field": "Obstructing",
    "handled the ball": "Handled ball", "hit the ball twice": "Hit twice", "timed out": "Timed out",
  };
  const YT_ICON = '<svg viewBox="0 0 28 20" aria-hidden="true"><rect width="28" height="20" rx="5" fill="currentColor"/><path d="M11 5.5v9l7.5-4.5z" fill="#fff"/></svg>';

  const store = {
    get(k, d) { try { const v = localStorage.getItem("pa:" + k); return v == null ? d : JSON.parse(v); } catch { return d; } },
    set(k, v) { try { localStorage.setItem("pa:" + k, JSON.stringify(v)); } catch { /* storage unavailable */ } },
  };

  const S = {
    g: store.get("g", "male"),
    f: store.get("f", "T20I"),
    q: "",
    team: store.get("team", ""),
    sort: { batters: ["runs", -1], bowlers: ["wkts", -1], players: ["name", 1] },
    minInns: store.get("minInns", 3),
    role: "",
    data: {},
  };

  const $ = (s, el = document) => el.querySelector(s);
  const app = $("#app");
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const fmtN = (v, d = 2) => (v == null || Number.isNaN(v) ? "–" : Number(v).toFixed(d).replace(/\.0+$/, "").replace(/(\.\d*?)0+$/, "$1"));
  const D = () => S.data[S.g];
  const name = (pid) => (D().players[pid]?.name) || D().names[pid] || pid;
  const initials = (n) => n.split(/\s+/).filter(Boolean).slice(-2).map((w) => w[0]).join("").toUpperCase();
  const flag = (team) => { const t = TEAM[team]; return t ? `<span class="flag" style="background:${t[1]}" title="${esc(team)}">${t[0]}</span>` : ""; };
  const dateStr = (iso) => new Date(iso + "T00:00:00").toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" });
  const plink = (pid, label) => D().players[pid] ? `<a href="#/player/${pid}">${esc(label ?? name(pid))}</a>` : esc(label ?? name(pid));
  const ytUrl = (m) => m.hl ? `https://www.youtube.com/watch?v=${m.hl}` : `https://www.youtube.com/results?search_query=${encodeURIComponent(m.hlq)}`;
  const ciUrl = (p) => p.ci ? `https://www.espncricinfo.com/cricketers/${(p.full || p.name).toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "")}-${p.ci}` : null;

  // ------------------------------------------------------------ data
  async function load(g) {
    if (S.data[g]) return S.data[g];
    let d = window.__DATA__ && window.__DATA__[g];
    if (!d) {
      const r = await fetch(`data/${g}.json`, { cache: "no-cache" });
      if (!r.ok) throw new Error(`Could not load data/${g}.json (${r.status})`);
      d = await r.json();
    }
    prepare(d);
    S.data[g] = d;
    return d;
  }

  function prepare(d) {
    for (const p of Object.values(d.players)) {
      let bb = 0, wb = 0, m = 0;
      for (const f of FORMATS) { bb += p.bat[f]?.balls || 0; wb += p.bowl[f]?.balls || 0; m += p.m[f] || 0; }
      const bowls = wb / Math.max(m, 1) >= 9, bats = bb / Math.max(m, 1) >= 9;
      p.roleX = p.keeper ? "Wicketkeeper" : bowls && bats ? "All-rounder" : bowls ? "Bowler" : bats ? "Batter" : (p.role || "Squad");
      p.search = (p.name + " " + (p.full || "") + " " + p.team).toLowerCase();
    }
  }

  // ------------------------------------------------------------ routing
  function parseHash() {
    const h = location.hash.replace(/^#\/?/, "");
    const [path, qs] = h.split("?");
    const parts = path.split("/").filter(Boolean).map(decodeURIComponent);
    const params = new URLSearchParams(qs || "");
    if (params.get("g") && params.get("g") !== S.g) S.g = params.get("g");
    if (params.get("f") && FORMATS.includes(params.get("f"))) S.f = params.get("f");
    return { view: parts[0] || "batters", id: parts[1] };
  }

  async function render() {
    const r = parseHash();
    syncHeader(r.view);
    app.innerHTML = '<div class="loading">Loading match data…</div>';
    let d;
    try { d = await load(S.g); } catch (e) { app.innerHTML = `<div class="empty">${esc(e.message)}</div>`; return; }
    renderFooter(d);
    const views = { batters: viewBatters, bowlers: viewBowlers, players: viewPlayers, teams: viewTeams, team: viewTeam, matches: viewMatches, match: viewMatch, player: viewPlayer };
    (views[r.view] || viewBatters)(r.id);
    if (r.view === "player" || r.view === "match" || r.view === "team") window.scrollTo(0, 0);
  }

  function syncHeader(view) {
    document.querySelectorAll("#genderSeg button").forEach((b) => b.classList.toggle("on", b.dataset.g === S.g));
    document.querySelectorAll("#fmtSeg button").forEach((b) => b.classList.toggle("on", b.dataset.f === S.f));
    const tabView = { player: null, team: "teams", match: "matches" }[view] ?? view;
    document.querySelectorAll("#tabs a").forEach((a) => a.classList.toggle("on", a.dataset.v === tabView));
    store.set("g", S.g); store.set("f", S.f);
  }

  function renderFooter(d) {
    $("#foot").innerHTML = `Matches from <b>${dateStr(d.window.from)}</b> to <b>${dateStr(d.window.to)}</b> · ${Object.keys(d.matches).length} ${S.g === "female" ? "women's" : "men's"} internationals involving full-member nations · updated ${new Date(d.generated).toLocaleString()}<br>
      Ball-by-ball data: <a href="https://cricsheet.org" target="_blank" rel="noopener">Cricsheet</a> (scorecards as published on <a href="https://www.espncricinfo.com" target="_blank" rel="noopener">ESPNcricinfo</a>) · player styles from ESPNcricinfo profiles · highlights on YouTube.
      Strengths and weaknesses are statistical inferences from how and when players score and get out — not ball-tracking.`;
  }

  // ------------------------------------------------------------ shared UI
  function teamChips() {
    const teams = D().teams;
    return `<div class="chips" id="teamChips"><button class="chip ${!S.team ? "on" : ""}" data-team="">All countries</button>${teams.map((t) =>
      `<button class="chip ${S.team === t ? "on" : ""}" data-team="${esc(t)}">${flag(t)} ${esc(t)}</button>`).join("")}</div>`;
  }
  function bindChips(rerender) {
    $("#teamChips")?.addEventListener("click", (e) => {
      const b = e.target.closest("[data-team]"); if (!b) return;
      S.team = b.dataset.team; store.set("team", S.team); rerender();
    });
  }
  function sortRows(rows, view, getters) {
    const [k, dir] = S.sort[view];
    const g = getters[k] || ((r) => r[k]);
    return rows.sort((a, b) => {
      const x = g(a), y = g(b);
      if (x == null && y == null) return 0;
      if (x == null) return 1;
      if (y == null) return -1;
      return (typeof x === "string" ? x.localeCompare(y) : x - y) * dir;
    });
  }
  function header(view, cols) {
    const [k, dir] = S.sort[view];
    return `<tr>${cols.map(([key, label, cls = "", title = ""]) =>
      `<th class="${cls} ${key === k ? "on" : ""} ${key === k && dir === 1 ? "asc" : ""}" data-k="${key}" title="${esc(title)}">${label}</th>`).join("")}</tr>`;
  }
  function bindSort(view, rerender, defaults = {}) {
    app.querySelector("thead")?.addEventListener("click", (e) => {
      const th = e.target.closest("th[data-k]"); if (!th || !th.dataset.k) return;
      const k = th.dataset.k;
      const [ck, cd] = S.sort[view];
      S.sort[view] = [k, ck === k ? -cd : (defaults[k] ?? -1)];
      rerender();
    });
    app.querySelector("tbody")?.addEventListener("click", (e) => {
      if (e.target.closest("a")) return;
      const tr = e.target.closest("tr[data-href]"); if (tr) location.hash = tr.dataset.href;
    });
  }
  const topIns = (p, side, kind) => {
    const it = p.ins?.[S.f]?.[side]?.[kind]?.[0];
    return it ? `<span class="tag ${kind}" title="${esc(it[1])}">${esc(it[0])}</span>` : "";
  };
  const matchesQ = (p) => !S.q || p.search.includes(S.q.toLowerCase());

  // ------------------------------------------------------------ batters
  function viewBatters() {
    const f = S.f;
    let rows = Object.values(D().players).filter((p) => p.bat[f] && (!S.team || p.team === S.team) && matchesQ(p) && p.bat[f].inns >= S.minInns);
    const G = { name: (p) => p.name, inns: (p) => p.bat[f].inns, runs: (p) => p.bat[f].runs, avg: (p) => p.bat[f].avg, sr: (p) => p.bat[f].sr,
      hs: (p) => p.bat[f].hsN, f50: (p) => p.bat[f].f50, h100: (p) => p.bat[f].h100, fours: (p) => p.bat[f].fours, sixes: (p) => p.bat[f].sixes,
      dot: (p) => p.bat[f].dot, bdry: (p) => p.bat[f].bdry, team: (p) => p.team };
    rows = sortRows(rows, "batters", G);
    const cols = [["", "#", "l"], ["name", "Batter", "l"], ["team", "Team", "l hide-sm"], ["inns", "Inns"], ["runs", "Runs"], ["avg", "Avg"], ["sr", "SR"], ["hs", "HS"],
      ["f50", "50s"], ["h100", "100s"], ["fours", "4s", "hide-sm"], ["sixes", "6s", "hide-sm"], ["dot", "Dot %", "hide-sm", "Percentage of balls faced that were dot balls"], ["", "Main weakness", "l"]];
    app.innerHTML = `
      <div class="toolbar"><h1>${f} batters</h1><span class="muted">${S.g === "female" ? "Women" : "Men"} · last 12 months</span>
        <span style="margin-left:auto" class="row small">Min innings <select id="minInns">${[1, 2, 3, 5, 8, 10].map((n) => `<option ${n === S.minInns ? "selected" : ""}>${n}</option>`).join("")}</select></span></div>
      <div class="toolbar">${teamChips()}</div>
      <div class="panel tbl-wrap"><table><thead>${header("batters", cols)}</thead><tbody>
      ${rows.map((p, i) => { const b = p.bat[f]; return `<tr data-href="#/player/${p.id}">
        <td class="rank l">${i + 1}</td><td class="l"><span class="pn">${esc(p.name)}</span><span class="sub">${flag(p.team)} ${esc(p.roleX)}</span></td>
        <td class="l hide-sm">${esc(p.team)}</td><td>${b.inns}</td><td><b>${b.runs}</b></td><td>${fmtN(b.avg)}</td><td>${fmtN(b.sr)}</td><td>${b.hs}</td>
        <td>${b.f50}</td><td>${b.h100}</td><td class="hide-sm">${b.fours}</td><td class="hide-sm">${b.sixes}</td><td class="hide-sm">${fmtN(b.dot, 1)}</td>
        <td class="l">${topIns(p, "bat", "w") || topIns(p, "bat", "s")}</td></tr>`; }).join("") || `<tr><td colspan="14" class="l muted">No batters match these filters.</td></tr>`}
      </tbody></table></div>`;
    bindChips(viewBatters); bindSort("batters", viewBatters, { name: 1, team: 1 });
    $("#minInns").onchange = (e) => { S.minInns = +e.target.value; store.set("minInns", S.minInns); viewBatters(); };
  }

  // ------------------------------------------------------------ bowlers
  function viewBowlers() {
    const f = S.f;
    const minBalls = f === "Test" ? 120 : f === "ODI" ? 60 : 24;
    let rows = Object.values(D().players).filter((p) => p.bowl[f] && p.bowl[f].balls >= minBalls && (!S.team || p.team === S.team) && matchesQ(p));
    const G = { name: (p) => p.name, team: (p) => p.team, inns: (p) => p.bowl[f].inns, balls: (p) => p.bowl[f].balls, wkts: (p) => p.bowl[f].wkts,
      econ: (p) => p.bowl[f].econ, avg: (p) => p.bowl[f].avg, sr: (p) => p.bowl[f].sr, dot: (p) => p.bowl[f].dot,
      best: (p) => { const b = p.bowl[f].best; if (!b) return null; const [w, r] = b.split("/").map(Number); return w * 1000 - r; }, type: (p) => p.bowlStyle || "" };
    rows = sortRows(rows, "bowlers", G);
    const cols = [["", "#", "l"], ["name", "Bowler", "l"], ["type", "Style", "l hide-sm"], ["inns", "Inns"], ["balls", "Overs"], ["wkts", "Wkts"], ["econ", "Econ"],
      ["avg", "Avg"], ["sr", "SR", "", "Balls per wicket"], ["best", "Best"], ["dot", "Dot %", "hide-sm"], ["", "Key trait", "l"]];
    app.innerHTML = `
      <div class="toolbar"><h1>${f} bowlers</h1><span class="muted">${S.g === "female" ? "Women" : "Men"} · min ${minBalls / 6} overs</span></div>
      <div class="toolbar">${teamChips()}</div>
      <div class="panel tbl-wrap"><table><thead>${header("bowlers", cols)}</thead><tbody>
      ${rows.map((p, i) => { const w = p.bowl[f]; return `<tr data-href="#/player/${p.id}">
        <td class="rank l">${i + 1}</td><td class="l"><span class="pn">${esc(p.name)}</span><span class="sub">${flag(p.team)} ${esc(p.team)}</span></td>
        <td class="l hide-sm">${esc(p.bowlStyle || "—")}</td><td>${w.inns}</td><td>${w.overs}</td><td><b>${w.wkts}</b></td><td>${fmtN(w.econ)}</td>
        <td>${fmtN(w.avg)}</td><td>${fmtN(w.sr, 1)}</td><td>${w.best || "–"}</td><td class="hide-sm">${fmtN(w.dot, 1)}</td>
        <td class="l">${topIns(p, "bowl", "s") || topIns(p, "bowl", "w")}</td></tr>`; }).join("") || `<tr><td colspan="12" class="l muted">No bowlers match these filters.</td></tr>`}
      </tbody></table></div>`;
    bindChips(viewBowlers); bindSort("bowlers", viewBowlers, { name: 1, team: 1, type: 1, econ: 1, avg: 1, sr: 1 });
  }

  // ------------------------------------------------------------ all players
  function viewPlayers() {
    let rows = Object.values(D().players).filter((p) => (!S.team || p.team === S.team) && matchesQ(p) && (!S.role || p.roleX === S.role));
    const G = { name: (p) => p.name, team: (p) => p.team, role: (p) => p.roleX, bat: (p) => p.batStyle || "", bowl: (p) => p.bowlStyle || "",
      Test: (p) => p.m.Test || 0, ODI: (p) => p.m.ODI || 0, T20I: (p) => p.m.T20I || 0 };
    rows = sortRows(rows, "players", G);
    const roles = ["Batter", "Wicketkeeper", "All-rounder", "Bowler"];
    const cols = [["name", "Player", "l"], ["team", "Country", "l"], ["role", "Role", "l"], ["bat", "Batting", "l hide-sm"], ["bowl", "Bowling", "l hide-sm"],
      ["Test", "Tests"], ["ODI", "ODIs"], ["T20I", "T20Is"]];
    app.innerHTML = `
      <div class="toolbar"><h1>All players</h1><span class="muted">${rows.length} ${S.g === "female" ? "women" : "men"}</span>
        <div class="chips" id="roleChips" style="margin-left:auto"><button class="chip ${!S.role ? "on" : ""}" data-r="">All roles</button>${roles.map((r) => `<button class="chip ${S.role === r ? "on" : ""}" data-r="${r}">${r}</button>`).join("")}</div></div>
      <div class="toolbar">${teamChips()}</div>
      <div class="panel tbl-wrap"><table><thead>${header("players", cols)}</thead><tbody>
      ${rows.map((p) => `<tr data-href="#/player/${p.id}"><td class="l"><span class="pn">${esc(p.name)}</span></td><td class="l">${flag(p.team)} ${esc(p.team)}</td>
        <td class="l">${esc(p.roleX)}</td><td class="l hide-sm">${esc(p.batStyle || "—")}</td><td class="l hide-sm">${esc(p.bowlStyle || "—")}</td>
        <td>${p.m.Test || ""}</td><td>${p.m.ODI || ""}</td><td>${p.m.T20I || ""}</td></tr>`).join("")}
      </tbody></table></div>`;
    bindChips(viewPlayers); bindSort("players", viewPlayers, { name: 1, team: 1, role: 1, bat: 1, bowl: 1 });
    $("#roleChips").onclick = (e) => { const b = e.target.closest("[data-r]"); if (!b) return; S.role = b.dataset.r; viewPlayers(); };
  }

  // ------------------------------------------------------------ teams
  function teamRecord(team, f) {
    const ms = Object.values(D().matches).filter((m) => m.teams.includes(team) && (!f || m.fmt === f));
    const w = ms.filter((m) => m.winner === team).length;
    const l = ms.filter((m) => m.winner && m.winner !== team).length;
    return { ms, p: ms.length, w, l, o: ms.length - w - l };
  }
  function viewTeams() {
    const f = S.f;
    const ps = Object.values(D().players);
    app.innerHTML = `<div class="toolbar"><h1>Countries</h1><span class="muted">${f} · ${S.g === "female" ? "women" : "men"}</span></div>
      <div class="grid g3">${D().teams.map((t) => {
        const r = teamRecord(t, f);
        const tp = ps.filter((p) => p.team === t);
        const bat = tp.filter((p) => p.bat[f]).sort((a, b) => b.bat[f].runs - a.bat[f].runs)[0];
        const bowl = tp.filter((p) => p.bowl[f]).sort((a, b) => b.bowl[f].wkts - a.bowl[f].wkts)[0];
        return `<a class="panel team-card" href="#/team/${encodeURIComponent(t)}"><h2>${flag(t)} ${esc(t)}</h2>
          <div class="kv"><span class="muted">${f}s played</span><b class="num">${r.p}</b></div>
          <div class="kv"><span class="muted">Won · Lost · Other</span><b class="num">${r.w} · ${r.l} · ${r.o}</b></div>
          <div class="kv"><span class="muted">Top run-scorer</span><span>${bat ? `${esc(bat.name)} <b class="num">${bat.bat[f].runs}</b>` : "—"}</span></div>
          <div class="kv"><span class="muted">Top wicket-taker</span><span>${bowl && bowl.bowl[f].wkts ? `${esc(bowl.name)} <b class="num">${bowl.bowl[f].wkts}</b>` : "—"}</span></div>
          <div class="kv"><span class="muted">Players used</span><b class="num">${tp.filter((p) => p.m[f]).length}</b></div></a>`;
      }).join("")}</div>`;
  }
  function viewTeam(team) {
    const f = S.f;
    const r = teamRecord(team, f);
    const tp = Object.values(D().players).filter((p) => p.team === team && p.m[f]).sort((a, b) => (b.m[f] || 0) - (a.m[f] || 0));
    app.innerHTML = `
      <div class="hero"><div class="avatar" style="background:${TEAM[team]?.[1] || "var(--pitch)"}">${TEAM[team]?.[0] || ""}</div>
        <div class="meta"><h1>${esc(team)} ${S.g === "female" ? "Women" : ""}</h1>
        <div class="facts"><span><b>${r.p}</b> ${f}s</span><span><b>${r.w}</b> won</span><span><b>${r.l}</b> lost</span><span><b>${r.o}</b> drawn/tied/NR</span></div></div></div>
      <div class="grid g2">
        <div class="panel"><div class="pad"><h3>${f} squad — batting</h3></div><div class="tbl-wrap"><table><thead><tr><th class="l">Player</th><th>M</th><th>Runs</th><th>Avg</th><th>SR</th><th class="l">Watch-out</th></tr></thead><tbody>
          ${tp.filter((p) => p.bat[f]).sort((a, b) => b.bat[f].runs - a.bat[f].runs).map((p) => `<tr data-href="#/player/${p.id}"><td class="l"><span class="pn">${esc(p.name)}</span><span class="sub">${esc(p.roleX)}</span></td><td>${p.m[f]}</td><td><b>${p.bat[f].runs}</b></td><td>${fmtN(p.bat[f].avg)}</td><td>${fmtN(p.bat[f].sr)}</td><td class="l">${topIns(p, "bat", "w")}</td></tr>`).join("")}
        </tbody></table></div></div>
        <div class="panel"><div class="pad"><h3>${f} squad — bowling</h3></div><div class="tbl-wrap"><table><thead><tr><th class="l">Player</th><th>Ov</th><th>Wkts</th><th>Econ</th><th>Avg</th><th class="l">Key trait</th></tr></thead><tbody>
          ${tp.filter((p) => p.bowl[f]).sort((a, b) => b.bowl[f].wkts - a.bowl[f].wkts || a.bowl[f].econ - b.bowl[f].econ).map((p) => `<tr data-href="#/player/${p.id}"><td class="l"><span class="pn">${esc(p.name)}</span><span class="sub">${esc(p.bowlStyle || p.roleX)}</span></td><td>${p.bowl[f].overs}</td><td><b>${p.bowl[f].wkts}</b></td><td>${fmtN(p.bowl[f].econ)}</td><td>${fmtN(p.bowl[f].avg)}</td><td class="l">${topIns(p, "bowl", "s") || topIns(p, "bowl", "w")}</td></tr>`).join("")}
        </tbody></table></div></div>
      </div>
      <div class="section-title"><h2>${f} matches</h2></div>
      <div class="panel">${matchRows(r.ms.sort((a, b) => b.date.localeCompare(a.date)))}</div>`;
    app.querySelectorAll("tbody").forEach((tb) => tb.addEventListener("click", (e) => { const tr = e.target.closest("tr[data-href]"); if (tr) location.hash = tr.dataset.href; }));
  }

  // ------------------------------------------------------------ matches
  function matchRows(ms) {
    if (!ms.length) return '<div class="empty">No matches.</div>';
    return ms.map((m) => `<a class="match" href="#/match/${m.id}"><span class="d">${dateStr(m.date)}<br>${m.fmt}</span>
      <span><span class="t">${flag(m.teams[0])} ${esc(m.teams[0])} v ${flag(m.teams[1])} ${esc(m.teams[1])}</span><br><span class="r">${esc(m.result)}</span>
      <span class="muted small"> · ${esc(m.event || "")}${m.mno ? ` (${m.mno})` : ""}</span></span>
      <span class="yt">${YT_ICON}<span class="hide-sm">${m.hl ? "Watch" : "Find"}</span></span></a>`).join("");
  }
  function viewMatches() {
    const ms = Object.values(D().matches).filter((m) => m.fmt === S.f && (!S.team || m.teams.includes(S.team))).sort((a, b) => b.date.localeCompare(a.date));
    app.innerHTML = `<div class="toolbar"><h1>${S.f} matches</h1><span class="muted">${ms.length} matches</span></div>
      <div class="toolbar">${teamChips()}</div><div class="panel">${matchRows(ms)}</div>`;
    bindChips(viewMatches);
  }
  function dismissalText(w) {
    const F = w.fld ? name(w.fld) : "";
    const B = w.bowl ? name(w.bowl) : "";
    switch (w.kind) {
      case "caught": return `c ${F} b ${B}`;
      case "caught behind": return `c †${F} b ${B}`;
      case "caught and bowled": return `c & b ${B}`;
      case "bowled": return `b ${B}`;
      case "lbw": return `lbw b ${B}`;
      case "stumped": return `st †${F} b ${B}`;
      case "run out": return `run out${F ? ` (${F})` : ""}`;
      case "hit wicket": return `hit wicket b ${B}`;
      default: return w.kind;
    }
  }
  function viewMatch(id) {
    const m = D().matches[id];
    if (!m) { app.innerHTML = '<div class="empty">Match not found.</div>'; return; }
    const video = m.hl
      ? `<div class="video"><iframe src="https://www.youtube-nocookie.com/embed/${m.hl}" title="${esc(m.hlTitle || "Highlights")}" allow="accelerometer; encrypted-media; gyroscope; picture-in-picture" allowfullscreen loading="lazy"></iframe></div>`
      : `<a class="ytcard" href="${ytUrl(m)}" target="_blank" rel="noopener">${YT_ICON.replace('fill="currentColor"', 'fill="#ff2a1f"')}<div><b>Watch highlights on YouTube</b><span>Opens a search for “${esc(m.hlq)}”</span></div></a>`;
    const inns = m.inns.map((x, i) => {
      const ws = m.wkts.filter((w) => w.inn === i + 1);
      return `<div class="panel pad"><div class="score"><b>${flag(x.team)} ${esc(x.team)} <span class="muted small">${i >= 2 ? "2nd inns" : ""}</span></b><span class="tot">${x.runs}/${x.wkts}${x.decl ? "d" : ""}</span>
        <span class="muted small">${x.overs} overs${x.target ? ` · target ${x.target}` : ""}</span><span></span></div>
        ${ws.length ? `<h3 style="margin-top:12px">Fall of wickets</h3><div class="log">${ws.map((w) => `<div class="small"><b>${plink(w.bat)}</b> ${esc(dismissalText(w))} — ${w.r} (${w.b}) <span class="muted">· ${w.score} in ${w.ov} ov</span></div>`).join("")}</div>` : ""}</div>`;
    }).join("");
    app.innerHTML = `
      <div class="toolbar"><a class="btn" href="#/matches">← Matches</a></div>
      <div class="hero"><div class="meta"><span class="tag">${m.fmt}${m.event ? " · " + esc(m.event) : ""}${m.mno ? " · Match " + m.mno : ""}</span>
        <h1 style="margin-top:8px">${flag(m.teams[0])} ${esc(m.teams[0])} v ${flag(m.teams[1])} ${esc(m.teams[1])}</h1>
        <div class="facts"><span><b>${esc(m.result)}</b></span><span>${dateStr(m.date)}</span><span>${esc(m.venue || "")}${m.city && !String(m.venue).includes(m.city) ? ", " + esc(m.city) : ""}</span>
        ${m.toss ? `<span>Toss: ${esc(m.toss.winner)} (${esc(m.toss.decision)})</span>` : ""}${m.pom.length ? `<span>Player of the match: <b>${m.pom.map((p) => plink(p)).join(", ")}</b></span>` : ""}</div></div></div>
      <div class="grid g2"><div>${video}</div>
        <div class="panel pad"><h3>Playing XIs</h3><div class="grid g2" style="gap:10px">${m.teams.map((t) => `<div><b>${flag(t)} ${esc(t)}</b><div class="xi" style="columns:1">${(m.squads[t] || []).map((p) => `<a href="${D().players[p] ? "#/player/" + p : "javascript:void 0"}">${esc(name(p))}${D().players[p]?.keeper ? " †" : ""}</a>`).join("")}</div></div>`).join("")}</div></div></div>
      <div class="section-title"><h2>Innings</h2></div><div class="grid g2">${inns}</div>`;
  }

  // ------------------------------------------------------------ player
  function bars(items, { max, red = false, unit = "", mark } = {}) {
    const mx = max ?? Math.max(1, ...items.map((i) => i.v || 0), ...items.map((i) => i.base || 0));
    return `<div class="bars">${items.map((i) => `<div class="bar"><span>${esc(i.k)}</span><div class="track">
      <div class="fill ${i.red ?? red ? "red" : ""}" style="width:${Math.min(100, (100 * (i.v || 0)) / mx)}%"></div>
      ${i.base != null ? `<div class="mark" style="left:${Math.min(100, (100 * i.base) / mx)}%" title="Typical: ${i.base}${unit}"></div>` : ""}</div>
      <span class="val">${i.label ?? fmtN(i.v, 1) + unit}</span></div>`).join("")}</div>${mark ? `<div class="legend">${mark}</div>` : ""}`;
  }
  function swList(ins) {
    const s = ins?.s || [], w = ins?.w || [];
    if (!s.length && !w.length) return '<p class="muted small">Not enough data in this format yet for confident conclusions.</p>';
    return `<div class="grid g2"><div class="sw"><h3>Strong areas</h3>${s.map((x) => `<div class="sw-item s"><b>${esc(x[0])}</b><span>${esc(x[1])}</span></div>`).join("") || '<p class="muted small">None stand out yet.</p>'}</div>
      <div class="sw"><h3>Weak areas</h3>${w.map((x) => `<div class="sw-item w"><b>${esc(x[0])}</b><span>${esc(x[1])}</span></div>`).join("") || '<p class="muted small">No clear weakness in the data.</p>'}</div></div>`;
  }
  function stat(k, v) { return `<div class="stat"><div class="v">${v ?? "–"}</div><div class="k">${k}</div></div>`; }
  function logItem(w, mode) {
    const m = D().matches[w.m];
    const how = mode === "bat" ? `${dismissalText(w)} — ${w.r} (${w.b})` : `${name(w.bat)} ${dismissalText(w)} — ${w.r} (${w.b})`;
    return `<div class="log-item"><span class="how">${mode === "bat" ? esc(how) : plink(w.bat) + " " + esc(dismissalText(w)) + ` — ${w.r} (${w.b})`}</span>
      <span class="act">${m ? `<a class="yt" href="${ytUrl(m)}" target="_blank" rel="noopener" title="${m.hl ? "Watch match highlights" : "Search highlights on YouTube"}">${YT_ICON} Highlights</a>` : ""}</span>
      <span class="ctx">${esc(KIND_LABEL[w.kind] || w.kind)} · over ${w.ov} · ${w.score} · v ${esc(w.opp)} · <a href="#/match/${w.m}">${dateStr(w.date)}</a></span></div>`;
  }

  function viewPlayer(id) {
    const p = D().players[id];
    if (!p) { app.innerHTML = '<div class="empty">Player not found.</div>'; return; }
    const fmts = FORMATS.filter((f) => p.m[f]);
    const f = fmts.includes(S.f) ? S.f : fmts[0];
    const bl = D().baselines[f] || {};
    const b = p.bat[f], w = p.bowl[f];
    const phases = D().phases[f];
    const ci = ciUrl(p);
    const bowlerFirst = p.roleX === "Bowler";

    const batHtml = b ? `
      <div class="section-title"><h2>Batting</h2><span class="muted small">${b.inns} innings</span></div>
      <div class="panel pad"><div class="stats">${stat("Runs", b.runs)}${stat("Average", fmtN(b.avg))}${stat("Strike rate", fmtN(b.sr))}${stat("Highest", b.hs)}
        ${stat("50s / 100s", `${b.f50} / ${b.h100}`)}${stat("4s / 6s", `${b.fours} / ${b.sixes}`)}${stat("Dot ball %", fmtN(b.dot, 1))}${stat("Balls / dismissal", fmtN(b.bpd, 1))}</div></div>
      <div class="panel pad" style="margin-top:14px">${swList(p.ins[f]?.bat)}</div>
      <div class="grid g2" style="margin-top:14px">
        <div class="panel pad"><h3>How they get out</h3>${b.outs ? bars(Object.entries(b.kinds).sort((x, y) => y[1] - x[1]).map(([k, v]) => ({ k: KIND_LABEL[k] || k, v: (100 * v) / b.outs, base: bl.kinds?.[k], red: true, label: `${v} · ${Math.round((100 * v) / b.outs)}%` })), { max: 100, unit: "%", mark: "Bar = share of this player's dismissals · line = typical share in " + f + "s" }) : '<p class="muted small">Not dismissed in this period.</p>'}</div>
        <div class="panel pad"><h3>Scoring by phase</h3>${bars(phases.filter(([k]) => b.phase[k]).map(([k, label]) => ({ k: label.split(" (")[0], v: f === "Test" ? b.phase[k].avg ?? b.phase[k].r : b.phase[k].sr, base: f === "Test" ? bl.phase?.[k]?.avg : bl.phase?.[k]?.sr,
            label: f === "Test" ? `avg ${fmtN(b.phase[k].avg, 1)}` : `SR ${fmtN(b.phase[k].sr, 0)}` })), { mark: (f === "Test" ? "Average" : "Strike rate") + " by phase · line = typical" })}
          <div class="legend">${phases.filter(([k]) => b.phase[k]).map(([k, label]) => `${label}: ${b.phase[k].r} runs, ${b.phase[k].b} balls, ${b.phase[k].o} out`).join(" · ")}</div></div>
        ${b.vs && (b.vs.pace || b.vs.spin) ? `<div class="panel pad"><h3>Pace vs spin</h3>${bars(["pace", "spin"].filter((t) => b.vs[t]).map((t) => ({ k: t === "pace" ? "vs Pace" : "vs Spin", v: b.vs[t].sr, label: `SR ${fmtN(b.vs[t].sr, 0)}` })), {})}
          <div class="legend">${["pace", "spin"].filter((t) => b.vs[t]).map((t) => `vs ${t}: ${b.vs[t].r} runs off ${b.vs[t].b} balls, out ${b.vs[t].o}× (avg ${fmtN(b.vs[t].avg, 1)})`).join("<br>")}</div></div>` : ""}
        <div class="panel pad"><h3>First 10 balls</h3><div class="stats">${stat("Avg early", fmtN(b.early.avg, 1))}${stat("Out early", `${b.early.o}/${b.outs}`)}${stat("Typical avg", fmtN(bl.earlyAvg, 1))}</div>
          <div class="legend">Average and dismissals within the first ten balls of an innings — shows how vulnerable they are before settling in.</div></div>
        ${b.bowlers.length ? `<div class="panel" style="grid-column:1/-1"><div class="pad"><h3>Bowlers they have faced most</h3></div><div class="tbl-wrap"><table><thead><tr><th class="l">Bowler</th><th class="l hide-sm">Style</th><th>Balls</th><th>Runs</th><th>Outs</th><th>SR</th></tr></thead><tbody>
          ${b.bowlers.map((x) => `<tr><td class="l">${plink(x.p)}</td><td class="l hide-sm">${esc(D().players[x.p]?.bowlStyle || "")}</td><td>${x.b}</td><td>${x.r}</td><td><b>${x.o}</b></td><td>${fmtN(x.sr, 0)}</td></tr>`).join("")}</tbody></table></div></div>` : ""}
      </div>
      ${p.dis.filter((d) => d.fmt === f).length ? `<div class="section-title"><h2>Every dismissal</h2><span class="muted small">Newest first · each links to that match's highlights</span></div>
        <div class="log">${p.dis.filter((d) => d.fmt === f).slice().reverse().map((d) => logItem(d, "bat")).join("")}</div>` : ""}` : "";

    const bowlHtml = w ? `
      <div class="section-title"><h2>Bowling</h2><span class="muted small">${w.inns} innings · ${esc(p.bowlStyle || "")}</span></div>
      <div class="panel pad"><div class="stats">${stat("Wickets", w.wkts)}${stat("Overs", w.overs)}${stat("Economy", fmtN(w.econ))}${stat("Average", fmtN(w.avg))}
        ${stat("Strike rate", fmtN(w.sr, 1))}${stat("Best", w.best)}${stat("Dot ball %", fmtN(w.dot, 1))}${stat("Wides / NB", `${w.wides} / ${w.nb}`)}</div></div>
      <div class="panel pad" style="margin-top:14px">${swList(p.ins[f]?.bowl)}</div>
      <div class="grid g2" style="margin-top:14px">
        <div class="panel pad"><h3>How they take wickets</h3>${w.wkts ? bars(Object.entries(w.kinds).sort((x, y) => y[1] - x[1]).map(([k, v]) => ({ k: KIND_LABEL[k] || k, v: (100 * v) / w.wkts, base: bl.kinds?.[k], label: `${v} · ${Math.round((100 * v) / w.wkts)}%` })), { max: 100, unit: "%", mark: "Line = typical share across all " + f + " dismissals" }) : '<p class="muted small">No wickets in this period.</p>'}</div>
        <div class="panel pad"><h3>Economy by phase</h3>${bars(phases.filter(([k]) => w.phase[k]).map(([k, label]) => ({ k: label.split(" (")[0], v: w.phase[k].econ, base: bl.bowlPhase?.[k]?.econ, red: w.phase[k].econ > (bl.bowlPhase?.[k]?.econ || 99), label: `${fmtN(w.phase[k].econ)} · ${w.phase[k].w}w` })), { mark: "Runs per over · line = typical" })}
          <div class="legend">${phases.filter(([k]) => w.phase[k]).map(([k, label]) => `${label}: ${Math.floor(w.phase[k].b / 6)}.${w.phase[k].b % 6} ov, ${w.phase[k].r} runs, ${w.phase[k].w} wkts`).join(" · ")}</div></div>
        ${w.hand && (w.hand.L || w.hand.R) ? `<div class="panel pad"><h3>Right vs left-handers</h3>${bars(["R", "L"].filter((h) => w.hand[h]).map((h) => ({ k: h === "R" ? "vs Right-hand" : "vs Left-hand", v: w.hand[h].econ, label: `econ ${fmtN(w.hand[h].econ)} · ${w.hand[h].w}w` })), {})}</div>` : ""}
        ${w.victims.length ? `<div class="panel pad"><h3>Favourite victims</h3>${w.victims.map((x) => `<div class="kv"><span>${plink(x.p)}</span><span class="num">${x.o}× · ${x.r} runs / ${x.b} balls</span></div>`).join("")}</div>` : ""}
        ${w.punishers.length ? `<div class="panel pad"><h3>Batters who score fastest off them</h3>${w.punishers.map((x) => `<div class="kv"><span>${plink(x.p)}</span><span class="num">${x.r} off ${x.b} · SR ${fmtN(x.sr, 0)}</span></div>`).join("")}</div>` : ""}
      </div>
      ${p.wk.filter((d) => d.fmt === f).length ? `<div class="section-title"><h2>Every wicket</h2><span class="muted small">Newest first · each links to that match's highlights</span></div>
        <div class="log">${p.wk.filter((d) => d.fmt === f).slice().reverse().map((d) => logItem(d, "bowl")).join("")}</div>` : ""}` : "";

    const form = p.form.filter((x) => x.fmt === f);
    app.innerHTML = `
      <div class="toolbar"><a class="btn" href="javascript:history.back()">← Back</a></div>
      <div class="hero"><div class="avatar" style="background:${TEAM[p.team]?.[1] || "var(--pitch)"}">${esc(initials(p.name))}</div>
        <div class="meta"><h1>${esc(p.full || p.name)}</h1>
          <div class="facts"><span>${flag(p.team)} <b>${esc(p.team)}</b></span><span><b>${esc(p.role || p.roleX)}</b></span>
          ${p.batStyle ? `<span>${esc(p.batStyle)}</span>` : ""}${p.bowlStyle ? `<span>${esc(p.bowlStyle)}</span>` : ""}
          <span>${fmts.map((x) => `${p.m[x]} ${x}${p.m[x] > 1 ? "s" : ""}`).join(" · ")}</span></div></div>
        ${ci ? `<a class="btn" href="${ci}" target="_blank" rel="noopener">ESPNcricinfo profile ↗</a>` : ""}</div>
      <div class="ftabs">${fmts.map((x) => `<button class="chip ${x === f ? "on" : ""}" data-f="${x}">${x} · ${p.m[x]}</button>`).join("")}</div>
      ${form.length && b ? `<div class="panel pad"><h3>Recent ${f} innings</h3><div class="form">${form.map((x) => `<a href="#/match/${x.m}" class="${x.r >= (f === "T20I" ? 50 : f === "ODI" ? 70 : 80) ? "big" : x.out && x.r < 10 ? "low" : ""}" title="v ${esc(x.opp)}, ${dateStr(x.date)}">${x.r}${x.out ? "" : "*"}<small>v ${esc(TEAM[x.opp]?.[0] || x.opp.slice(0, 3))}</small></a>`).join("")}</div></div>` : ""}
      ${bowlerFirst ? bowlHtml + batHtml : batHtml + bowlHtml}
      ${!b && !w ? '<div class="empty">Selected for the XI but did not bat or bowl in this format.</div>' : ""}`;
    app.querySelector(".ftabs").onclick = (e) => { const c = e.target.closest("[data-f]"); if (c) { S.f = c.dataset.f; syncHeader("player"); viewPlayer(id); } };
  }

  // ------------------------------------------------------------ events
  document.querySelector("#genderSeg").onclick = (e) => {
    const b = e.target.closest("[data-g]"); if (!b || b.dataset.g === S.g) return;
    S.g = b.dataset.g; S.team = S.team; // keep country
    const r = parseHash();
    location.hash = ["player", "match"].includes(r.view) ? "#/" + (r.view === "match" ? "matches" : "batters") : (location.hash || "#/batters").split("?")[0];
    render();
  };
  document.querySelector("#fmtSeg").onclick = (e) => {
    const b = e.target.closest("[data-f]"); if (!b) return;
    S.f = b.dataset.f; const r = parseHash();
    if (r.view === "match") location.hash = "#/matches"; else render();
  };
  let qt;
  $("#q").addEventListener("input", (e) => {
    clearTimeout(qt);
    qt = setTimeout(() => {
      S.q = e.target.value.trim();
      const v = parseHash().view;
      if (!["batters", "bowlers", "players"].includes(v)) location.hash = "#/players"; else render();
    }, 150);
  });
  window.addEventListener("hashchange", render);
  render();
})();
