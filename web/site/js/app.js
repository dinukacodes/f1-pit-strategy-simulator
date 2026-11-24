/* app.js — wires the model to the page: replay, explainers, Monte Carlo, lab, what-ifs, checks. */
(function () {
  "use strict";
  const $ = (s, r) => (r || document).querySelector(s);
  const el = (tag, attrs, html) => { const e = document.createElement(tag); if (attrs) for (const k in attrs) e.setAttribute(k, attrs[k]); if (html != null) e.innerHTML = html; return e; };
  const cssv = (n) => getComputedStyle(document.documentElement).getPropertyValue(n).trim();
  const NB = window.NB_RESULTS;
  // run at most once per animation frame: keeps sliders smooth however fast they move
  const rafThrottle = (fn) => { let queued = false, args = null; return function () { args = arguments; if (queued) return; queued = true; requestAnimationFrame(() => { queued = false; fn.apply(null, args); }); }; };
  const P0 = F1.defaultParams();
  const C = {};
  ["green", "vsc", "sc", "s1", "s2", "s3", "s4", "soft", "medium", "hard", "accent"].forEach(k => { C[k] = cssv("--" + k); });
  C.ink = "--ink"; C.muted = "--muted";          // theme-dependent: resolved by the chart code at draw time
  // light / dark theme toggle (remembered per browser)
  (function () {
    const btn = document.getElementById("theme-btn"), root = document.documentElement;
    const label = () => { btn.textContent = root.getAttribute("data-theme") === "dark" ? "☀ Light" : "☾ Dark"; };
    btn.addEventListener("click", () => {
      const dark = root.getAttribute("data-theme") !== "dark";
      if (dark) root.setAttribute("data-theme", "dark"); else root.removeAttribute("data-theme");
      try { localStorage.setItem("psl-theme", dark ? "dark" : "light"); } catch (e) { /* storage unavailable */ }
      label(); window.redrawAll();
    });
    label();
  })();
  const SCOL = [C.s1, C.s2, C.s3, C.s4];
  const TYRE = { SOFT: C.soft, MEDIUM: C.medium, HARD: C.hard };
  const STATUS_COL = [C.green, C.vsc, C.sc];
  const fx = (v, d) => (v >= 0 ? "+" : "−") + Math.abs(v).toFixed(d == null ? 2 : d);
  const f2 = (v, d) => v.toFixed(d == null ? 2 : d);
  function clock(s) { const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), r = s - 3600 * h - 60 * m; return (h ? h + ":" + String(m).padStart(2, "0") : m) + ":" + r.toFixed(1).padStart(4, "0"); }
  function tyreBadge(c) { return '<span class="tyre" style="--tc:' + TYRE[c] + '">' + c[0] + "</span>"; }
  function prettyName(s) {
    const comps = s.compounds.map(c => c[0]).join("→");
    if (s.reactive_window) return "Pit-if-neutralised " + comps + " (plan lap " + s.pit_laps[0] + ", box at first VSC/SC from lap " + s.reactive_window[0] + ")";
    return (s.pit_laps.length === 1 ? "One-stop " : s.pit_laps.length === 2 ? "Two-stop " : "Three-stop ") + comps + " (lap" + (s.pit_laps.length > 1 ? "s " : " ") + s.pit_laps.join(" & ") + ")";
  }
  const SHORT = NB.shortlist.map(s => { const x = F1.strategy(s.pit_laps, s.compounds, s.reactive_window); x.label = prettyName(x); return x; });
  SHORT[0].short = "One-stop"; SHORT[1].short = "Two-stop"; SHORT[2].short = "Pit-if-neutralised";

  // ------------------------------------------------------------ MC client (worker + fallback)
  const MC = (function () {
    let worker = null, seq = 0; const handlers = {};
    try {
      if (location.protocol === "file:") throw new Error("workers are blocked on file:// pages; run on the main thread");
      worker = new Worker("js/worker.js");
      worker.onmessage = (e) => { const h = handlers[e.data.id]; if (h) { h(e.data.state); if (e.data.state.finished) delete handlers[e.data.id]; } };
      worker.onerror = () => { worker = null; };
    } catch (e) { worker = null; }
    function checks(NB, onMsg) {
      const id = ++seq;
      if (worker) { handlers[id] = (st) => onMsg(st); worker.postMessage({ cmd: "checks", id, nb: NB }); return; }
      const list = window.makeChecks(F1, NB); onMsg({ titles: list.map(c => c[0]) });
      let i = 0; (function next() { if (i >= list.length) return; let ok, msg; try { [ok, msg] = list[i][1](); } catch (e) { ok = false; msg = String(e); } onMsg({ i, ok, msg }); i++; setTimeout(next, 0); })();
    }
    function run(job, onProgress) {
      const id = ++seq;
      if (worker) {
        handlers[id] = onProgress; worker.postMessage({ cmd: "run", id, job: JSON.parse(JSON.stringify(job)) });
        return () => { delete handlers[id]; if (worker) worker.postMessage({ cmd: "cancel", id }); };
      }
      return window.runMC(job, onProgress, (fn) => setTimeout(fn, 0));
    }
    return { run, checks };
  })();

  // ------------------------------------------------------------ helpers
  function stripCells(container, n, cls) {
    container.innerHTML = ""; container.style.gridTemplateColumns = "repeat(" + n + ", 1fr)";
    const cells = []; for (let i = 0; i < n; i++) { const c = el("i"); if (cls) c.className = cls(i); container.appendChild(c); cells.push(c); }
    return cells;
  }
  function statusRects(status, y0, y1) {
    const items = [];
    for (let l = 0; l < status.length; l++) if (status[l] !== 0) items.push({ x0: l + 0.5, x1: l + 1.5, y0, y1, color: STATUS_COL[status[l]] });
    return items;
  }
  function paramRows(target, rows) {
    const t = $(target); if (!t) return;
    t.innerHTML = "<tr><th>symbol</th><th>meaning</th><th>value</th><th>source</th></tr>" + rows.map(r =>
      "<tr><td>" + r[0] + "</td><td>" + r[1] + '</td><td class="v">' + r[2] + "</td><td>" + tag(r[3]) + "</td></tr>").join("");
  }
  function tag(kind) { return kind === "lit" ? '<span class="tag lit">literature</span>' : kind === "pub" ? '<span class="tag pub">public data</span>' : kind === "der" ? '<span class="tag pub">derived</span>' : '<span class="tag ass">assumed</span>'; }

  // run a section's setup only when it comes near the viewport (fast first paint)
  function lazy(sel, fn) {
    const t = $(sel); if (!("IntersectionObserver" in window)) { fn(); return; }
    const io = new IntersectionObserver((es) => { if (es.some(e => e.isIntersecting)) { io.disconnect(); fn(); } }, { rootMargin: "600px" });
    io.observe(t);
  }

  // the replay board's two charts take whatever height is left on a laptop screen
  function fitBoards() {
    const h = innerWidth > 1240 ? Math.max(170, Math.min(330, innerHeight - 460)) : 240;
    document.querySelectorAll("canvas.fit").forEach(cv => cv.setAttribute("data-h", h));
  }
  fitBoards();
  addEventListener("resize", rafThrottle(() => { fitBoards(); window.redrawAll(); }));

  // ============================================================ HERO KPIs (notebook values)
  (function () {
    const r = NB.stage2;
    $("#kpi-two").textContent = fx(r[1].diff_s) + " s";
    $("#kpi-two-ci").textContent = "CI [" + fx(r[1].diff_low_s) + ", " + fx(r[1].diff_high_s) + "] s";
    $("#kpi-react").textContent = fx(r[2].diff_s) + " s";
    $("#kpi-react-ci").textContent = "CI [" + fx(r[2].diff_low_s) + ", " + fx(r[2].diff_high_s) + "] s";
    $("#nb-ncand").textContent = NB.n_candidates;
  })();

  // ============================================================ RACE REPLAY
  const Replay = (function () {
    const S = (laps, t, rw, short) => { const s = F1.strategy(laps, t.split("-").map(c => ({ S: "SOFT", M: "MEDIUM", H: "HARD" })[c]), rw); s.short = short; s.label = prettyName(s); return s; };
    const seg = (N, list) => { const a = new Array(N).fill(0); list.forEach(([x, y, v]) => { for (let l = x; l <= Math.min(y, N); l++) a[l - 1] = v; }); return a; };
    const PRESETS = [
      { id: "random", name: "Random race", sub: "62 laps · Markov Safety Cars", n: 62, script: null, strategies: () => SHORT.map(s => Object.assign(F1.strategy(s.pit_laps, s.compounds, s.reactive_window), { short: s.short, label: s.label })),
        story: "A fresh random race from the model: Safety Cars and VSCs come from the Markov chain. Roll new races to see how often each plan wins." },
      { id: "ad2021", name: "Abu Dhabi 2021", sub: "58 laps · late SC laps 53–57", n: 58, script: seg(58, [[53, 57, 2]]),
        strategies: () => [S([14], "M-H", null, "Stay out"), S([14, 53], "M-H-S", null, "Box under the SC")],
        story: "<b>Abu Dhabi 2021 (approximate):</b> both title contenders stopped once early for hards. A Safety Car came out around lap 53 of 58. One stayed out on 40-lap-old hards, the other pitted for fresh softs, and racing resumed for the final lap. Here our single, Singapore-calibrated car runs both choices. <i>Try painting the Safety Car earlier (around lap 40) and watch the pit stop start to pay.</i> The model counts time only, not track position, and track position decided the real race." },
      { id: "sg2008", name: "Singapore 2008", sub: "61 laps · SC laps 14–17", n: 61, script: seg(61, [[14, 17, 2]]),
        strategies: () => [S([33], "H-M", null, "Planned one-stop"), S([12], "M-H", null, "Early stop (lap 12)"), S([28], "M-H", [12, 28], "Pit-if-neutralised")],
        story: "<b>Singapore 2008 (approximate):</b> the eventual winner stopped very early, around lap 12. A Safety Car followed two laps later, after a crash later found to be deliberate, and the pit lane stayed closed under the rules of the time. In pure time the early stop still loses here; its real value was track position." },
      { id: "sg2023", name: "Singapore 2023", sub: "62 laps · SC 20–23, VSC 44–45", n: 62, script: seg(62, [[20, 23, 2], [44, 45, 1]]),
        strategies: () => [S([20], "M-H", null, "Stop under SC"), S([20, 44], "M-H-M", null, "SC + VSC stops"), S([34], "H-M", null, "Ignore the SC")],
        story: "<b>Singapore 2023 (approximate):</b> a Safety Car around lap 20 gave most cars a cheap stop. A VSC around lap 44 tempted a second stop for fresh mediums. Delete the VSC (click its laps until they turn green) and see what the second stop would have cost." },
      { id: "sg2024", name: "Singapore 2024", sub: "62 laps · no Safety Car", n: 62, script: seg(62, []), strategies: () => SHORT.map(s => Object.assign(F1.strategy(s.pit_laps, s.compounds, s.reactive_window), { short: s.short, label: s.label })),
        story: "<b>Singapore 2024:</b> the first race here with no Safety Car at all. The pit-if-neutralised plan never gets its chance and simply stops on its planned lap. <i>Paint a Safety Car around lap 15–25 and watch it jump ahead.</i>" },
      { id: "lap1", name: "Lap-1 chaos", sub: "62 laps · SC laps 1–4", n: 62, script: seg(62, [[1, 4, 2]]),
        strategies: () => [S([34], "H-M", null, "Planned one-stop"), S([2], "S-H", null, "Box on lap 2"), S([2, 36], "S-H-M", null, "Box lap 2 + lap 36")],
        story: "<b>A creative one:</b> a start crash brings out the Safety Car for laps 1–4. Is a cheap stop on lap 2 a bargain? Watch the tyre-wear chart for the answer." },
    ];
    let preset = PRESETS[0], p = P0, seed = 7, script = null, strats = null, races = null, status = null, lap = 62, timer = null, cells = null;
    function buildPresets() {
      const box = $("#rp-presets"); box.innerHTML = "";
      PRESETS.forEach(pr => { const b = el("button", { class: "preset" + (pr === preset ? " on" : ""), type: "button", title: pr.sub }, pr.name + "<small>" + pr.sub + "</small>");
        b.addEventListener("click", () => { stop(); choose(pr); lap = 1; play(); }); box.appendChild(b); });
    }
    function choose(pr) {
      preset = pr; p = F1.withParams(P0, { n_laps: pr.n }); script = pr.script ? pr.script.slice() : null; strats = pr.strategies();
      $("#rp-story").innerHTML = pr.story; $("#rp-findsc-wrap").style.display = pr.script ? "none" : "";
      $("#rp-lap").max = pr.n; $("#rp-nlaps").textContent = pr.n; buildPresets();
      if (!pr.script) pickRandom(seed); else simulate();
    }
    function pickRandom(sd) {
      for (let tries = 0; tries < 400; tries++) {
        const st = Array.from(F1.drawScenarios(1, p, sd).status);
        if (!$("#rp-findsc").checked || st.slice(11, 40).some(v => v !== 0)) { script = st; break; }
        sd++;
      }
      seed = sd; $("#rp-seed").value = sd; simulate();
    }
    function simulate() {
      const scen = F1.drawScenarios(1, p, seed, script);     // the script pins every lap's status; noise comes from the seed
      status = Array.from(scen.status);
      races = strats.map(s => F1.simulateOne(s, p, scen, 0, true));
      $("#rp-refname").textContent = strats[0].short;
      events = commentary();
      buildStrip(); setLap(Math.min(lap, p.n_laps));
    }
    function buildStrip() {
      const box = $("#rp-strip"); box.innerHTML = ""; cells = [];
      const rows = [{ name: "Track status ✎", cls: (i) => status[i] === 1 ? "v" : status[i] === 2 ? "s" : "" }].concat(
        strats.map((s, j) => ({ name: s.short, color: SCOL[j], cls: (i) => "c-" + races[j].laps[i].compound + (races[j].laps[i].pit ? " pit" : "") })));
      rows.forEach((r, ri) => {
        const row = el("div", { class: "strip-row" }); const lab = el("span", null, (r.color ? '<i class="sw" style="background:' + r.color + '"></i>' : "") + r.name);
        const c = el("div", { class: "strip-cells" }); row.appendChild(lab); row.appendChild(c); box.appendChild(row);
        const rc = stripCells(c, p.n_laps, r.cls); cells.push(rc);
        rc.forEach((cell, i) => {
          cell.title = ri === 0 ? "Lap " + (i + 1) + ": click to cycle Green → VSC → SC" : "Lap " + (i + 1) + ": click to move " + strats[ri - 1].short + "'s nearest stop here";
          cell.addEventListener("click", () => { stop(); ri === 0 ? paint(i) : moveStop(ri - 1, i + 1); });
        });
      });
    }
    function paint(i) { script = status.slice(); script[i] = (script[i] + 1) % 3; simulate(); }
    function moveStop(j, L) {
      const s = strats[j], laps = s.pit_laps.slice();
      let k = 0; laps.forEach((x, q) => { if (Math.abs(x - L) < Math.abs(laps[k] - L)) k = q; });
      laps[k] = L;
      const rw = s.reactive_window ? [Math.min(s.reactive_window[0], L), L] : null;
      const ns = F1.strategy(laps, s.compounds, rw);
      if (F1.validateStrategy(ns, p)) return;
      ns.short = s.short; ns.label = prettyName(ns); strats[j] = ns; simulate();
    }
    function setLap(L) {
      lap = L; $("#rp-lap").value = L; $("#rp-lapn").textContent = L; $("#rp-lapn2").textContent = L;
      cells.forEach(row => row.forEach((c, i) => { c.classList.toggle("future", i >= L); c.classList.toggle("now", i === L - 1); }));
      const N = p.n_laps, ref = races[0].laps;
      const xs = [], gaps = strats.map(() => []);
      let lo = 0, hi = 0;
      for (let l = 0; l < N; l++) races.forEach((r) => { const g = r.laps[l].cum - ref[l].cum; lo = Math.min(lo, g); hi = Math.max(hi, g); });
      for (let l = 0; l < L; l++) { xs.push(l + 1); races.forEach((r, j) => gaps[j].push(r.laps[l].cum - ref[l].cum)); }
      const pad = (hi - lo) * 0.08 + 1, legend = strats.map((s, j) => ({ label: s.short, color: SCOL[j] }));
      const pits = []; races.forEach((r, j) => r.stops.filter(s => s <= L).forEach(s => pits.push({ x: s, y: r.laps[s - 1].cum - ref[s - 1].cum, j })));
      plot($("#rp-gap"), {
        x: { min: 0.5, max: N + 0.5 }, y: { min: lo - pad, max: hi + pad }, xLabel: "lap", yLabel: "gap to " + strats[0].short + " [s]", legend,
        layers: [{ type: "rects", items: statusRects(status, lo - pad, hi + pad), alpha: 0.2 },
          { type: "hline", y: 0, color: C.muted, dash: [2, 3] }, { type: "vline", x: L, color: C.ink, dash: [1, 3] }]
          .concat(gaps.map((g, j) => ({ type: "line", x: xs, y: g, color: SCOL[j], width: 2.6 })),
            pits.map(q => ({ type: "points", x: [q.x], y: [q.y], color: SCOL[q.j], r: 5 }))),
      });
      let wmax = 0; races.forEach(r => r.laps.forEach(x => { wmax = Math.max(wmax, x.wear); }));
      plot($("#rp-wear"), {
        x: { min: 0.5, max: N + 0.5 }, y: { min: 0, max: wmax * 1.1 + 0.1 }, xLabel: "lap", yLabel: "w [s]", legend,
        layers: [{ type: "rects", items: statusRects(status, 0, wmax * 1.1 + 0.1), alpha: 0.2 }, { type: "vline", x: L, color: C.ink, dash: [1, 3] }]
          .concat(races.map((r, j) => ({ type: "line", x: xs, y: r.laps.slice(0, L).map(x => x.wear), color: SCOL[j], width: 2.4 }))),
      });
      $("#rp-lapn3").textContent = L;
      const shown = events.filter(e => e.lap <= L).slice(-9).reverse();
      $("#rp-comm").innerHTML = shown.length ? shown.map((e, k) => '<li class="' + e.kind + (k === 0 && e.lap === L ? " fresh" : "") + '"><b>Lap ' + e.lap + "</b> " + e.text + "</li>").join("") : '<li class="muted">Lights out. Press play.</li>';
      $("#rp-cards").innerHTML = races.map((r, j) => {
        const x = r.laps[L - 1], gap = x.cum - ref[L - 1].cum, s = strats[j];
        const stopsDone = r.stops.filter(t => t <= L), justPitted = stopsDone.length && stopsDone[stopsDone.length - 1] === L;
        const nowComp = justPitted ? s.compounds[stopsDone.length] : x.compound, age = justPitted ? 0 : x.age + 1;
        return '<div class="card stratcard" style="--c:' + SCOL[j] + '"><div class="name">' + s.short + ' <span class="meta">· ' + s.label + '</span></div>' +
          '<div class="big">' + clock(x.cum) + (j ? ' <span class="' + (gap < -0.05 ? "good" : gap > 0.05 ? "bad" : "meh") + '">' + fx(gap, 1) + " s</span>" : "") + "</div>" +
          '<div class="meta">' + tyreBadge(nowComp) + " " + age + " laps old · stops: " + (stopsDone.length ? stopsDone.map(t => "lap " + t + (status[t - 1] ? " (" + ["", "VSC", "SC"][status[t - 1]] + ")" : "")).join(", ") : "none yet") + "</div>" +
          (L === N ? '<div class="meta"><b>Finish: ' + clock(r.total) + (j ? " (" + fx(r.total - races[0].total, 1) + " s)" : "") + "</b></div>" : "") + "</div>";
      }).join("");
      breakdown(L);
    }
    // auto-generated commentary: neutralisations, every pit stop with its cost, and changes of the lead
    let events = [];
    function commentary() {
      const N = p.n_laps, ev = [], NAME = ["Green", "Virtual Safety Car", "Safety Car"];
      const green = F1.pitLoss(0, 0, p);
      for (let l = 0; l < N; l++) {
        const st = status[l], prev = l ? status[l - 1] : 0;
        if (st !== prev && st !== 0) {
          let e = l; while (e + 1 < N && status[e + 1] === st) e++;
          ev.push({ lap: l + 1, kind: st === 2 ? "sc" : "vsc", text: NAME[st] + (e > l ? " (laps " + (l + 1) + "–" + (e + 1) + ")" : " (1 lap)") + ". Everyone laps at " + (st === 2 ? p.k_sc : p.k_vsc).toFixed(2) + " × t₀ = " + ((st === 2 ? p.k_sc : p.k_vsc) * p.t0_s).toFixed(1) + " s, tyres wear at " + Math.round(100 * (st === 2 ? p.phi_sc : p.phi_vsc)) + "% of the normal rate, and a pit stop is cheaper." });
        } else if (st === 0 && prev !== 0) ev.push({ lap: l + 1, kind: "grn", text: "Green flag, racing resumes." });
        races.forEach((r, j) => {
          const x = r.laps[l]; if (!x.pit) return;
          const lane = x.pit - x.crew, saved = green - lane;
          ev.push({ lap: l + 1, kind: "pit", j, text: '<i class="sw" style="background:' + SCOL[j] + '"></i>' + strats[j].short + " pits for " + strats[j].compounds[r.stops.indexOf(l + 1) + 1].toLowerCase() + "s: lane " + f2(lane, 1) + " s + crew " + f2(x.crew, 1) + " s = <b>" + f2(x.pit, 1) + " s</b>" + (saved > 0.05 ? ", " + f2(saved, 1) + " s cheaper than a Green-flag stop." : ".") });
        });
        if (l && races.length > 1) {
          const lead = (k) => races.reduce((b, r, j) => (r.laps[k].cum < races[b].laps[k].cum ? j : b), 0);
          const a = lead(l - 1), b = lead(l);
          if (a !== b) ev.push({ lap: l + 1, kind: "lead", text: '<i class="sw" style="background:' + SCOL[b] + '"></i>' + strats[b].short + " is now ahead of " + strats[a].short + " by " + f2(races[a].laps[l].cum - races[b].laps[l].cum, 1) + " s." });
        }
      }
      const order = races.map((r, j) => j).sort((a, b) => races[a].total - races[b].total);
      ev.push({ lap: N, kind: "fin", text: "🏁 " + strats[order[0]].short + " wins" + (order.length > 1 ? " by " + f2(races[order[1]].total - races[order[0]].total, 1) + " s over " + strats[order[1]].short : "") + "." });
      return ev;
    }
    function breakdown(L) {
      const parts = [["offset", "compound Δc", C.medium], ["wearTime", "tyre wear w", C.soft], ["fuelTime", "fuel γ·m", C.s1], ["sc", "VSC/SC pace", C.sc], ["pitLane", "pit lane", C.s3], ["crew", "crew time", C.s4]];
      const rows = races.map(r => { const x = r.laps[L - 1]; return { x, v: { offset: x.offset, wearTime: x.wearTime, fuelTime: x.fuelTime, sc: x.base - p.t0_s, pitLane: x.pit ? x.pit - x.crew : 0, crew: x.crew } }; });
      const max = Math.max(1, ...rows.map(r => Object.values(r.v).reduce((a, b) => a + b, 0)));
      $("#rp-breakdown").innerHTML = rows.map((r, j) => '<div class="bd-row"><span><i class="sw" style="background:' + SCOL[j] + '"></i>' + strats[j].short + "<br><b>" + f2(r.x.time, 2) + " s</b></span>" +
        '<div><div class="bd-bar">' + parts.map(([k, n, c]) => r.v[k] > 0 ? '<span style="width:' + (100 * r.v[k] / max) + "%;background:" + c + '" title="' + n + " " + f2(r.v[k], 2) + ' s">' + (r.v[k] / max > 0.07 ? f2(r.v[k], 1) : "") + "</span>" : "").join("") + "</div>" +
        '<div class="small" style="margin:2px 0 0">t₀ = ' + p.t0_s.toFixed(1) + " s + parts shown" + (r.x.status === 0 ? " + noise ε = " + fx(r.x.noise) + " s" : " (neutralised lap: k·t₀ = " + f2(r.x.base, 1) + " s)") + "</div></div></div>").join("") +
        '<div class="bd-legend">' + parts.map(([k, n, c]) => '<span><i class="sw" style="background:' + c + '"></i>' + n + "</span>").join("") + "</div>";
    }
    function play() {
      if (timer) { stop(); return; }
      if (lap >= p.n_laps) setLap(1);
      $("#rp-play").textContent = "❚❚ Pause";
      timer = setInterval(() => { if (lap >= p.n_laps) { stop(); return; } setLap(lap + 1); }, +$("#rp-speed").value);
    }
    function stop() { clearInterval(timer); timer = null; $("#rp-play").textContent = "▶ Play"; }
    $("#rp-play").addEventListener("click", play);
    $("#rp-speed").addEventListener("change", () => { if (timer) { stop(); play(); } });
    $("#rp-new").addEventListener("click", () => { stop(); if (preset.script) choose(PRESETS[0]); seed = +$("#rp-seed").value + 1; pickRandom(seed); lap = 1; play(); });
    $("#rp-seed").addEventListener("change", () => { stop(); seed = +$("#rp-seed").value; if (preset.script) simulate(); else pickRandom(seed); });
    $("#rp-reset").addEventListener("click", () => { stop(); choose(preset); });
    const sl = rafThrottle((v) => setLap(v));
    $("#rp-lap").addEventListener("input", (e) => { stop(); sl(+e.target.value); });
    ["#rp-gap", "#rp-wear"].forEach(id => $(id).addEventListener("pointermove", (e) => {
      const cv = e.currentTarget, sc = cv._scale; if (!sc) return;
      const r = cv.getBoundingClientRect(), L = Math.round(sc.ix(e.clientX - r.left));
      if (L >= 1 && L <= p.n_laps && L !== lap) { stop(); sl(L); }
    }));
    $("#rp-story").addEventListener("click", (e) => e.currentTarget.classList.toggle("open"));
    choose(PRESETS[0]);
    return { choose };
  })();

  // ============================================================ A. LAP TIME
  lazy("#laptime", function () {
    const p = P0;
    paramRows("#pt-lap", [
      ["t₀", "clean lap, new tyre, no fuel", "96.0 s", "ass"], ["Δc", "compound offset S / M / H", "0 / 0.35 / 0.70 s", "ass"],
      ["m₀, b", "start fuel, burn per lap", "100 kg, 1.6 kg/lap", "ass"], ["γ", "lap-time cost of fuel", "0.03 s/kg", "ass"],
      ["σ", "lap-time noise", "0.35 s", "ass"], ["k_VSC, k_SC", "neutralised lap / t₀", "1.40, 1.60", "lit"], ["N", "race distance", "62 laps", "pub"]]);
    function draw() {
      const c = $("#lt-comp").value, s = +$("#lt-start").value; $("#lt-start-v").textContent = s;
      const xs = [], off = [], wear = [], fuel = [];
      for (let l = s; l <= p.n_laps; l++) {
        xs.push(l); off.push(p.offset_s[c]); wear.push(F1.wearClosedForm(p, c, s, l - s)); fuel.push(p.gamma_s_per_kg * (p.m0_kg - p.burn_kg_per_lap * (l - 1)));
      }
      const a1 = fuel, a2 = fuel.map((v, i) => v + off[i]), a3 = a2.map((v, i) => v + wear[i]);
      const zeros = xs.map(() => 0);
      plot($("#lt-chart"), {
        x: { min: 1, max: p.n_laps }, y: { min: 0, max: Math.max(...a3) * 1.08 }, xLabel: "race lap", yLabel: "seconds above t₀ = 96 s",
        legend: [{ label: "fuel γ·m", color: C.s1 }, { label: "compound Δc", color: C.medium }, { label: "tyre wear w", color: C.soft }],
        layers: [{ type: "band", x: xs, lo: zeros, hi: a1, color: C.s1, alpha: 0.55 }, { type: "band", x: xs, lo: a1, hi: a2, color: C.medium, alpha: 0.6 },
          { type: "band", x: xs, lo: a2, hi: a3, color: C.soft, alpha: 0.6 }, { type: "line", x: xs, y: a3, color: C.ink, width: 2 }],
      });
    }
    $("#lt-comp").addEventListener("change", draw); $("#lt-start").addEventListener("input", rafThrottle(draw)); draw();
  });

  // ============================================================ B. TYRES / RK4
  lazy("#tyres", function () {
    paramRows("#pt-tyre", [
      ["k_c", "wear rate S / M / H", "0.100 / 0.060 / 0.035 s/lap", "ass"], ["η", "self-acceleration of wear", "0.02 1/s", "ass"],
      ["β", "extra wear per kg of fuel", "0.004 1/kg", "ass"], ["φ_VSC, φ_SC", "wear factor when neutralised", "0.50, 0.25", "lit"]]);
    function draw() {
      const eta = +$("#ty-eta").value, phi = +$("#ty-phi").value; $("#ty-eta-v").textContent = eta.toFixed(3);
      const p = F1.withParams(P0, { eta_per_s: eta }); const layers = []; let worst = 0;
      F1.COMPOUNDS.forEach(c => {
        const xs = [], ex = []; for (let a = 0; a <= 40; a += 0.5) { xs.push(a); ex.push(F1.wearClosedForm(p, c, 1, a, phi)); }
        const px = [], py = []; let w = 0;
        for (let a = 0; a <= 40; a++) { px.push(a); py.push(w); worst = Math.max(worst, Math.abs(w - F1.wearClosedForm(p, c, 1, a, phi))); w = F1.rk4Step(F1.wearRhs(p, c, a + 1, phi), 0, w, 1); }
        layers.push({ type: "line", x: xs, y: ex, color: TYRE[c], width: 2 }, { type: "points", x: px, y: py, color: TYRE[c], r: 2.6 });
      });
      plot($("#ty-curves"), { x: { min: 0, max: 40 }, y: { min: 0 }, xLabel: "tyre age a [laps] (stint from lap 1)", yLabel: "w [s]",
        legend: F1.COMPOUNDS.map(c => ({ label: c, color: TYRE[c] })), layers });
      $("#ty-err").textContent = "Largest gap between RK4 (one step per lap) and the exact solution over 40 laps: " + worst.toExponential(1) + " s. That is far below anything a stopwatch could see.";
    }
    function order() {
      const p = F1.withParams(P0, { eta_per_s: 0.08 }), f = F1.wearRhs(p, "SOFT", 1, 1), exact = F1.wearClosedForm(p, "SOFT", 1, 30);
      const hs = [6, 5, 3, 2, 1.5, 1, 0.5], layers = [], txt = [];
      [["euler", "Euler", C.soft], ["rk2", "RK2 (midpoint)", C.medium], ["rk4", "RK4", C.s1]].forEach(([m, n, col]) => {
        const errs = hs.map(h => Math.abs(F1.solve(m, f, 0, 0, 30, Math.round(30 / h)) - exact));
        const lx = hs.map(Math.log), ly = errs.map(Math.log), mx = lx.reduce((a, b) => a + b) / lx.length, my = ly.reduce((a, b) => a + b) / ly.length;
        let sxy = 0, sxx = 0; lx.forEach((x, i) => { sxy += (x - mx) * (ly[i] - my); sxx += (x - mx) * (x - mx); });
        const slope = sxy / sxx; txt.push(n + " slope " + slope.toFixed(2));
        layers.push({ type: "line", x: hs, y: errs, color: col, width: 2 }, { type: "points", x: hs, y: errs, color: col, r: 3 });
      });
      plot($("#ty-order"), { x: { log: true, min: 0.45, max: 7 }, y: { log: true }, xLabel: "step size h [laps]", yLabel: "|error| at lap 30 [s]",
        legend: [{ label: "Euler", color: C.soft }, { label: "RK2", color: C.medium }, { label: "RK4", color: C.s1 }], layers });
      $("#ty-order-txt").textContent = "Fitted log–log slopes: " + txt.join(", ") + ". The theory says 1, 2 and 4. Halving the step cuts the RK4 error 16-fold. (η = 0.08 here, as in the notebook, to make the curvature visible.)";
    }
    $("#ty-eta").addEventListener("input", rafThrottle(draw)); $("#ty-phi").addEventListener("change", draw); draw(); order();
  });

  // ============================================================ C. MARKOV
  lazy("#markov", function () {
    function params() { return F1.withParams(P0, { p_gs: +$("#mk-pgs").value, sc_min_laps: +$("#mk-m").value }); }
    function diagram(p) {
      const m = p.sc_min_laps, W = 560, H = 262, nodes = [];
      nodes.push({ id: "G", x: 80, y: 140, c: C.green, label: "Green" }, { id: "V", x: 250, y: 75, c: C.vsc, label: "VSC" });
      const span = Math.min(110, 400 / (m + 1));
      for (let i = 0; i < m; i++) nodes.push({ id: "S" + (i + 1), x: 200 + i * span, y: 215, c: C.sc, label: "SC" + (i + 1) });
      nodes.push({ id: "S+", x: 200 + m * span, y: 215, c: C.sc, label: "SC+" });
      const pos = {}; nodes.forEach(n => { pos[n.id] = n; });
      const arrows = [];
      const A = (a, b, t, bend) => arrows.push({ a: pos[a], b: pos[b], t, bend: bend || 0 });
      A("G", "V", F1.withParams(p).p_gv.toFixed(3), -0.25); A("V", "G", (1 - p.p_vv).toFixed(2), -0.25);
      A("G", "S1", p.p_gs.toFixed(3), 0.2);
      for (let i = 1; i < m; i++) A("S" + i, "S" + (i + 1), "1", 0);
      A("S" + m, "S+", p.p_ss.toFixed(2), 0); A("S+", "G", (1 - p.p_ss).toFixed(2), 0.35); if (m > 0) A("S" + m, "G", (1 - p.p_ss).toFixed(2), 0.15);
      let svg = '<svg viewBox="0 0 ' + W + " " + H + '" role="img" aria-label="Markov chain state diagram"><defs><marker id="ah" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" style="fill:var(--muted)"/></marker></defs>';
      arrows.forEach(({ a, b, t, bend }) => {
        const dx = b.x - a.x, dy = b.y - a.y, d = Math.hypot(dx, dy), ux = dx / d, uy = dy / d, r = 22;
        const x1 = a.x + ux * r, y1 = a.y + uy * r, x2 = b.x - ux * r, y2 = b.y - uy * r;
        const mx = (x1 + x2) / 2 - uy * bend * d, my = (y1 + y2) / 2 + ux * bend * d;
        svg += '<path d="M' + x1 + "," + y1 + " Q" + mx + "," + my + " " + x2 + "," + y2 + '" fill="none" style="stroke:var(--muted)" stroke-width="1.4" marker-end="url(#ah)"/>';
        svg += '<text x="' + ((x1 + x2) / 2 * 0.5 + mx * 0.5) + '" y="' + ((y1 + y2) / 2 * 0.5 + my * 0.5 - 4) + '" style="fill:var(--ink)" font-size="12" text-anchor="middle">' + t + "</text>";
      });
      const loops = [["G", (1 - p.p_gv - p.p_gs).toFixed(3)], ["V", p.p_vv.toFixed(2)], ["S+", p.p_ss.toFixed(2)]];
      loops.forEach(([id, t]) => { const n = pos[id]; svg += '<path d="M' + (n.x - 10) + "," + (n.y - 20) + " C" + (n.x - 30) + "," + (n.y - 62) + " " + (n.x + 30) + "," + (n.y - 62) + " " + (n.x + 10) + "," + (n.y - 20) + '" fill="none" style="stroke:var(--muted)" stroke-width="1.4" marker-end="url(#ah)"/><text x="' + n.x + '" y="' + (n.y - 52) + '" style="fill:var(--ink)" font-size="12" text-anchor="middle">' + t + "</text>"; });
      nodes.forEach(n => { svg += '<circle cx="' + n.x + '" cy="' + n.y + '" r="22" fill="' + n.c + '" fill-opacity="0.22" stroke="' + n.c + '" stroke-width="2"/><text x="' + n.x + '" y="' + (n.y + 4) + '" style="fill:var(--ink)" font-size="12" font-weight="700" text-anchor="middle">' + n.label + "</text>"; });
      svg += "</svg>"; $("#mk-diagram").innerHTML = svg;
    }
    function matrix(p) {
      const { P } = F1.expandedMatrix(p), names = ["G", "V"]; for (let i = 1; i <= p.sc_min_laps; i++) names.push("SC" + i); names.push("SC+");
      let h = "<table><tr><th></th>" + names.map(n => "<th>" + n + "</th>").join("") + "</tr>";
      P.forEach((r, i) => { h += "<tr><th>" + names[i] + "</th>" + r.map(v => v ? '<td class="nz" style="--a:' + (0.12 + 0.5 * v) + '">' + (v === 1 ? "1" : v.toFixed(3)) + "</td>" : '<td class="z">0</td>').join("") + "</tr>"; });
      $("#mk-matrix").innerHTML = h + "</table>";
    }
    function paths(p) {
      const scen = F1.drawScenarios(20, p, (Math.random() * 1e9) >>> 0), box = $("#mk-paths"); box.innerHTML = "";
      for (let i = 0; i < 20; i++) { const c = el("div", { class: "strip-cells" }); box.appendChild(c); stripCells(c, p.n_laps, (l) => { const s = scen.status[i * p.n_laps + l]; return s === 1 ? "v" : s === 2 ? "s" : ""; }); }
    }
    function draw() {
      const p = params(); $("#mk-pgs-v").textContent = p.p_gs.toFixed(3); $("#mk-m-v").textContent = p.sc_min_laps;
      diagram(p); matrix(p); paths(p);
      const pr = F1.statusProbabilities(p), xs = pr.map((_, i) => i + 1);
      plot($("#mk-probs"), { x: { min: 1, max: p.n_laps }, y: { min: 0 }, xLabel: "lap", yLabel: "probability",
        legend: [{ label: "P(SC on lap)", color: C.sc }, { label: "P(VSC on lap)", color: C.vsc }],
        layers: [{ type: "line", x: xs, y: pr.map(r => r[2]), color: C.sc, width: 2.4 }, { type: "line", x: xs, y: pr.map(r => r[1]), color: C.vsc, width: 2.4 }] });
      const rf = F1.renewalFractions(p), expSC = pr.reduce((a, r) => a + r[2], 0);
      const sc = F1.drawScenarios(4000, p, 5); let any = 0;
      for (let i = 0; i < 4000; i++) { for (let l = 0; l < p.n_laps; l++) if (sc.status[i * p.n_laps + l] === 2) { any++; break; } }
      $("#mk-stats").innerHTML = "Mean SC length E[D] = <b>" + F1.scMeanDuration(p).toFixed(2) + " laps</b>. Long-run share of laps: Green " + (100 * rf[0]).toFixed(1) + "%, VSC " + (100 * rf[1]).toFixed(1) + "%, SC " + (100 * rf[2]).toFixed(1) + "%. Expected SC laps per race: <b>" + expSC.toFixed(1) + "</b>. Races with at least one SC (4,000 simulated): <b>" + (100 * any / 4000).toFixed(0) + "%</b>.";
    }
    paramRows("#pt-markov", [["P_GS", "SC onset per Green lap", "0.020", "pub"], ["P_GV", "VSC onset per Green lap", "0.012", "pub"],
      ["P_lap1,SC", "SC on lap 1 (start crashes)", "0.15", "pub"], ["p_VV", "VSC continues", "0.60", "ass"], ["m", "minimum SC length", "3 laps", "pub"], ["p_SS", "SC continues after the minimum", "0.50", "ass"]]);
    const mkd = rafThrottle(draw); $("#mk-pgs").addEventListener("input", mkd); $("#mk-m").addEventListener("input", mkd); $("#mk-resample").addEventListener("click", () => paths(params()));
    draw();
  });

  // ============================================================ D. PIT LOSS
  lazy("#pitloss", function () {
    paramRows("#pt-pit", [["T_pit", "pit entry → exit through the lane", "36.0 s", "ass"], ["T_bypass", "same stretch on track at racing speed", "15.0 s", "ass"],
      ["ΔT_G", "net lane loss under Green", "21.0 s", "der"], ["α_VSC, α_SC", "loss reduction (derived)", "0.286, 0.429", "der"],
      ["c, μ, σ", "crew time: shift, log-location, log-spread", "2.0 s, −0.51, 0.50", "ass"]]);
    function draw() {
      const p = F1.withParams(P0, { t_pit_s: +$("#pl-tpit").value, t_bypass_s: Math.min(+$("#pl-tby").value, +$("#pl-tpit").value - 1) });
      $("#pl-tpit-v").textContent = p.t_pit_s.toFixed(1); $("#pl-tby-v").textContent = p.t_bypass_s.toFixed(1);
      const W = 560, H = 150;
      $("#pl-geo").innerHTML = '<svg viewBox="0 0 ' + W + " " + H + '" role="img" aria-label="pit lane geometry">' +
        '<path d="M20,40 H540" style="stroke:var(--muted)" stroke-width="10" stroke-linecap="round" opacity=".5"/>' +
        '<path d="M110,40 C140,40 150,100 190,100 H370 C410,100 420,40 450,40" fill="none" stroke="' + C.s3 + '" stroke-width="6"/>' +
        '<text x="280" y="28" style="fill:var(--ink)" font-size="13" text-anchor="middle">on track: T_bypass = ' + p.t_bypass_s.toFixed(1) + " s (×" + p.k_sc + " under SC = " + (p.k_sc * p.t_bypass_s).toFixed(1) + " s)</text>" +
        '<text x="280" y="124" fill="' + C.s3 + '" font-size="13" text-anchor="middle">pit lane at the speed limit: T_pit = ' + p.t_pit_s.toFixed(1) + " s (unchanged under SC)</text>" +
        '<rect x="262" y="90" width="36" height="20" rx="4" fill="' + C.accent + '"/><text x="280" y="104" font-size="11" text-anchor="middle" fill="#111" font-weight="700">BOX</text>' +
        '<text x="280" y="145" style="fill:var(--muted)" font-size="12" text-anchor="middle">ΔT_G = ' + p.dT_green_s.toFixed(1) + " s · α_VSC = " + p.alpha_vsc.toFixed(3) + " · α_SC = " + p.alpha_sc.toFixed(3) + "</text></svg>";
      const mc = F1.meanCrew(p), lane = [p.dT_green_s, (1 - p.alpha_vsc) * p.dT_green_s, (1 - p.alpha_sc) * p.dT_green_s];
      plot($("#pl-bars"), { height: 200, x: { min: -0.6, max: 2.6, ticks: [0, 1, 2], fmt: (v) => ["Green", "VSC", "SC"][v] || "" }, y: { min: 0, max: Math.max(...lane) + mc + 5 }, yLabel: "seconds lost",
        legend: [{ label: "lane loss (1−α)ΔT_G", color: C.s3 }, { label: "mean crew time", color: C.s4 }],
        layers: [{ type: "bars", x: [0, 1, 2], y: lane, w: 0.6, colors: [C.s3, C.s3, C.s3] }, { type: "bars", x: [0, 1, 2], y: lane.map(v => v + mc), base: 0, w: 0.6, colors: [C.s4, C.s4, C.s4], alpha: 0.0 },
          { type: "rects", items: lane.map((v, i) => ({ x0: i - 0.3, x1: i + 0.3, y0: v, y1: v + mc, color: C.s4 })) },
          { type: "labels", color: C.ink, align: "center", bold: true, items: lane.map((v, i) => ({ x: i, y: v + mc, dy: -10, text: (v + mc).toFixed(1) + " s" })) }] });
    }
    function crew() {
      const p = P0, rng = F1.makeRng(20251007, 0), n = 5000, xs = [];
      for (let i = 0; i < n; i++) xs.push(F1.crewTimeFromNormal(rng.normal(), p));
      const bw = 0.1, lo = 2, nb = 30, counts = new Array(nb).fill(0);
      xs.forEach(v => { const k = Math.floor((v - lo) / bw); if (k >= 0 && k < nb) counts[k]++; });
      const centers = counts.map((_, k) => lo + (k + 0.5) * bw), dens = counts.map(c => c / (n * bw));
      const px = [], py = []; for (let x = 2.001; x <= 5; x += 0.01) { const y = x - p.crew_shift_s; px.push(x); py.push(Math.exp(-Math.pow(Math.log(y) - p.crew_mu, 2) / (2 * p.crew_sigma * p.crew_sigma)) / (y * p.crew_sigma * Math.sqrt(2 * Math.PI))); }
      plot($("#pl-crew"), { x: { min: 2, max: 5 }, y: { min: 0 }, xLabel: "stationary time [s]", yLabel: "density",
        legend: [{ label: "Box–Muller samples", color: C.s4 }, { label: "exact shifted lognormal", color: C.ink, thin: true }],
        layers: [{ type: "bars", x: centers, y: dens, w: bw, color: C.s4, alpha: 0.7 }, { type: "line", x: px, y: py, color: C.ink, width: 2 }] });
      const s = xs.slice().sort((a, b) => a - b); let D = 0;
      const ncdf = (z) => 0.5 * (1 + erf(z / Math.SQRT2));
      s.forEach((v, i) => { const F = ncdf((Math.log(v - p.crew_shift_s) - p.crew_mu) / p.crew_sigma); D = Math.max(D, (i + 1) / n - F, F - i / n); });
      const mean = xs.reduce((a, b) => a + b) / n;
      $("#pl-crew-txt").textContent = "Sample mean " + mean.toFixed(3) + " s (theory " + F1.meanCrew(p).toFixed(3) + " s), minimum " + s[0].toFixed(3) + " s (never below the 2.0 s shift). Kolmogorov–Smirnov D = " + D.toFixed(4) + ", below the 5% critical value " + (1.36 / Math.sqrt(n)).toFixed(4) + ".";
    }
    const pld = rafThrottle(draw); $("#pl-tpit").addEventListener("input", pld); $("#pl-tby").addEventListener("input", pld); draw(); crew();
  });
  function erf(x) { const t = 1 / (1 + 0.3275911 * Math.abs(x)); const y = 1 - (((((1.061405429 * t - 1.453152027) * t) + 1.421413741) * t - 0.284496736) * t + 0.254829592) * t * Math.exp(-x * x); return x >= 0 ? y : -y; }

  // ============================================================ E. MONTE CARLO + CRN
  (function () {
    let cancel = null;
    function run() {
      if (cancel) cancel();
      const hist = { n: [], m: [], lo: [], hi: [], im: [], ilo: [], ihi: [] }, pts = { x: [], y: [] }, indep = $("#mc-indep").checked;
      cancel = MC.run({ p: P0, strategies: [SHORT[0], SHORT[1]], n: 10000, batch: 200, seed: 424242, ref: 0, indep }, (st) => {
        const d = st.diffs[1], h = 1.959964 * d.sd / Math.sqrt(d.n);
        hist.n.push(st.done); hist.m.push(d.mean); hist.lo.push(d.mean - h); hist.hi.push(d.mean + h);
        let ih = 0;
        if (st.indep) { const q = st.indep[1]; ih = 1.959964 * q.sd / Math.sqrt(q.n); hist.im.push(q.mean); hist.ilo.push(q.mean - ih); hist.ihi.push(q.mean + ih); }
        if (pts.x.length < 1500) st.sampleTotals[0].forEach((v, i) => { pts.x.push(v); pts.y.push(st.sampleTotals[1][i]); });
        const layers = [];
        if (st.indep) layers.push({ type: "band", x: hist.n, lo: hist.ilo, hi: hist.ihi, color: C.muted, alpha: 0.18 }, { type: "line", x: hist.n, y: hist.im, color: C.muted, width: 1.5 });
        layers.push({ type: "band", x: hist.n, lo: hist.lo, hi: hist.hi, color: C.s2, alpha: 0.35 }, { type: "line", x: hist.n, y: hist.m, color: C.s2, width: 2.2 },
          { type: "hline", y: NB.stage2[1].diff_s, color: C.accent, label: "notebook " + fx(NB.stage2[1].diff_s) + " s" });
        plot($("#mc-conv"), { x: { log: true, min: 200, max: 10000 }, y: st.indep ? { min: Math.max(-30, Math.min(...hist.ilo.slice(-1))) - 2, max: Math.min(45, Math.max(...hist.ihi.slice(-1))) + 2 } : {},
          xLabel: "races simulated (log scale)", yLabel: "two-stop − one-stop [s]",
          legend: [{ label: "with CRN", color: C.s2 }].concat(st.indep ? [{ label: "independent scenarios", color: C.muted }] : []), layers });
        const lo = Math.min(...pts.x, ...pts.y), hi = Math.max(...pts.x, ...pts.y);
        plot($("#mc-scatter"), { x: { min: lo - 10, max: hi + 10 }, y: { min: lo - 10, max: hi + 10 }, xLabel: "one-stop race time [s]", yLabel: "two-stop [s]",
          layers: [{ type: "line", x: [lo - 10, hi + 10], y: [lo - 10, hi + 10], color: C.muted, width: 1, dash: [4, 4] }, { type: "points", x: pts.x, y: pts.y, color: C.s2, r: 2, alpha: 0.55 }] });
        const ratio = st.indep ? Math.pow(st.indep[1].sd / d.sd, 2) : null;
        $("#mc-stats").innerHTML = [["races done", st.done.toLocaleString()], ["mean difference (CRN)", fx(d.mean) + " ± " + h.toFixed(2) + " s"],
          ["without CRN", st.indep ? fx(st.indep[1].mean) + " ± " + ih.toFixed(2) + " s" : "—"], ["variance reduction", ratio ? ratio.toFixed(0) + "×" : "—"],
          ["SD of one race time", st.totals[0].sd.toFixed(1) + " s"], ["SD of paired difference", d.sd.toFixed(2) + " s"]]
          .map(([k, v]) => '<div class="stat"><div class="k">' + k + '</div><div class="v">' + v + "</div></div>").join("");
        if (st.finished) cancel = null;
      });
    }
    $("#mc-run").addEventListener("click", run); $("#mc-indep").addEventListener("change", run);
    const io = new IntersectionObserver((es) => { if (es.some(e => e.isIntersecting)) { io.disconnect(); run(); } }, { rootMargin: "200px" });
    io.observe($("#montecarlo"));
  })();

  // ============================================================ STRATEGY LAB
  (function () {
    const SL = [
      ["p_gs", "Safety-Car onset P_GS / lap", 0, 0.08, 0.002, 3], ["p_gv", "VSC onset P_GV / lap", 0, 0.06, 0.002, 3],
      ["p_lap1_sc", "Lap-1 Safety-Car probability", 0, 0.5, 0.01, 2], ["sc_min_laps", "Minimum SC length m [laps]", 1, 6, 1, 0],
      ["p_ss", "SC continues (after minimum)", 0, 0.9, 0.05, 2], ["t_pit_s", "Pit-lane transit T_pit [s]", 26, 46, 0.5, 1],
      ["k_soft", "SOFT wear rate [s/lap]", 0.04, 0.18, 0.005, 3], ["k_medium", "MEDIUM wear rate [s/lap]", 0.02, 0.12, 0.005, 3],
      ["k_hard", "HARD wear rate [s/lap]", 0.015, 0.08, 0.0025, 4], ["eta_per_s", "Wear self-acceleration η", 0, 0.1, 0.005, 3],
      ["sigma_s", "Lap-time noise σ [s]", 0, 1.5, 0.05, 2], ["crew_sigma", "Crew-time spread σ_C", 0.1, 1.2, 0.05, 2]];
    const base = () => ({ p_gs: P0.p_gs, p_gv: P0.p_gv, p_lap1_sc: P0.p_lap1_sc, sc_min_laps: P0.sc_min_laps, p_ss: P0.p_ss, t_pit_s: P0.t_pit_s,
      k_soft: 0.1, k_medium: 0.06, k_hard: 0.035, eta_per_s: P0.eta_per_s, sigma_s: P0.sigma_s, crew_sigma: P0.crew_sigma });
    const WORLDS = [
      ["Baseline", "the study's world", {}],
      ["Safety-Car fest", "SC and VSC twice as often", { p_gs: 0.05, p_gv: 0.025 }],
      ["No Safety Cars", "like 2024 and 2025", { p_gs: 0, p_gv: 0, p_lap1_sc: 0 }],
      ["Tyre eater", "hot track, high wear", { k_soft: 0.14, k_medium: 0.09, k_hard: 0.055, eta_per_s: 0.04 }],
      ["60 km/h pit lane", "6 s slower stops", { t_pit_s: 42 }],
      ["Chaos", "noisy laps, messy stops", { sigma_s: 0.9, crew_sigma: 1.0, p_gs: 0.04 }],
    ];
    let vals = base(), worldName = "Baseline";
    let strats = [{ laps: "34", tyres: "H-M", react: "" }, { laps: "19,46", tyres: "M-H-S", react: "" }, { laps: "28", tyres: "M-H", react: "12" }];
    const N = P0.n_laps, LET = { SOFT: "S", MEDIUM: "M", HARD: "H" }, NEXT = { S: "M", M: "H", H: "S" };
    function params() {
      return F1.withParams(P0, { p_gs: vals.p_gs, p_gv: vals.p_gv, p_lap1_sc: vals.p_lap1_sc, sc_min_laps: vals.sc_min_laps, p_ss: vals.p_ss, t_pit_s: vals.t_pit_s,
        k_s_per_lap: { SOFT: vals.k_soft, MEDIUM: vals.k_medium, HARD: vals.k_hard }, eta_per_s: vals.eta_per_s, sigma_s: vals.sigma_s, crew_sigma: vals.crew_sigma });
    }
    function buildWorlds() {
      const box = $("#lab-presets"); box.innerHTML = "";
      WORLDS.forEach(([name, sub, ch]) => {
        const b = el("button", { class: "preset" + (name === worldName ? " on" : ""), type: "button", title: sub }, name + "<small>" + sub + "</small>");
        b.addEventListener("click", () => { vals = Object.assign(base(), ch); worldName = name; buildWorlds(); buildSliders(); schedule(); });
        box.appendChild(b);
      });
    }
    function buildSliders() {
      const box = $("#lab-params"); box.innerHTML = "";
      SL.forEach(([k, label, mn, mx, st, d]) => {
        const row = el("label", { class: "sl" }, "<span>" + label + '</span><input type="range" min="' + mn + '" max="' + mx + '" step="' + st + '" value="' + vals[k] + '"><b>' + (+vals[k]).toFixed(d) + "</b>");
        const inp = $("input", row), out = $("b", row);
        inp.addEventListener("input", () => { vals[k] = +inp.value; out.textContent = (+inp.value).toFixed(d); if (worldName) { worldName = ""; buildWorlds(); } schedule(); });
        box.appendChild(row);
      });
    }
    function parse(r) {
      const laps = r.laps.split(/[ ,;]+/).filter(Boolean).map(Number);
      const map = { S: "SOFT", M: "MEDIUM", H: "HARD" };
      const tyres = r.tyres.toUpperCase().split(/[^SMH]+|(?=[SMH])/).filter(Boolean).map(c => map[c[0]]);
      const rw = r.react ? [+r.react, laps[0]] : null;
      const s = F1.strategy(laps, tyres, rw);
      return { s, laps, tyres, err: laps.some(isNaN) ? "pit laps must be numbers" : F1.validateStrategy(s, P0) };
    }
    // ---- strategy rows with a draggable stint bar
    function buildStrats() {
      const b = $("#lab-strats"); b.innerHTML = "";
      strats.forEach((r, j) => {
        const row = el("div", { class: "srow", style: "--c:" + SCOL[j % 4] });
        row.innerHTML = '<span class="dot"></span><div class="body"><div class="fields">' + (j === 0 ? "<b>ref</b>" : "<b>#" + (j + 1) + "</b>") + ' pit laps <input type="text" data-k="laps" value="' + r.laps + '"> tyres <input type="text" data-k="tyres" value="' + r.tyres + '" style="width:5.5em"> <span title="If a VSC or Safety Car starts on or after this lap (and before the planned stop), box straight away">box at first VSC/SC from lap</span> <input type="text" data-k="react" value="' + r.react + '" placeholder="off" style="width:3.2em"></div>' +
          '<div class="stintbar" title="drag pit markers · click a stint to change tyre · double-click to add a stop"></div><div class="fields"><span class="err"></span></div></div>' +
          (strats.length > 2 ? '<button class="xbtn" title="remove">×</button>' : "<span></span>");
        row.querySelectorAll("input").forEach(inp => inp.addEventListener("input", () => { r[inp.dataset.k] = inp.value.trim(); refresh(row, r); schedule(); }));
        const x = $(".xbtn", row); if (x) x.addEventListener("click", () => { strats.splice(j, 1); buildStrats(); schedule(); });
        refresh(row, r); b.appendChild(row);
      });
      $("#lab-add").disabled = strats.length >= 4;
      const sel = $("#pw-which"), cur = +sel.value || 0; sel.innerHTML = strats.map((_, j) => '<option value="' + j + '">#' + (j + 1) + "</option>").join(""); sel.value = Math.min(cur, strats.length - 1);
      const ms = $("#mx-strat"), mcur = +ms.value || 1; ms.innerHTML = strats.slice(1).map((_, j) => '<option value="' + (j + 1) + '">#' + (j + 2) + "</option>").join(""); ms.value = Math.min(mcur, strats.length - 1);
    }
    function sync(row, r) { row.querySelectorAll("input").forEach(inp => { inp.value = r[inp.dataset.k]; }); }
    function refresh(row, r) {
      const { laps, tyres, err } = parse(r);
      $(".err", row).textContent = err ? "⚠ " + err : "";
      const bar = $(".stintbar", row); bar.innerHTML = "";
      if (laps.some(isNaN) || tyres.length !== laps.length + 1) return;
      const pct = (l) => (100 * l / N) + "%", edges = [0].concat(laps, [N]);
      if (r.react && !isNaN(+r.react) && laps[0] >= +r.react) { const w = el("div", { class: "win", title: "pit-if-neutralised window" }); w.style.left = pct(+r.react - 1); w.style.width = pct(laps[0] - +r.react + 1); bar.appendChild(w); }
      tyres.forEach((t, k) => {
        const s = el("div", { class: "stint", title: t + ": click to change tyre" }, LET[t]); s.style.left = pct(edges[k]); s.style.width = "calc(" + pct(edges[k + 1] - edges[k]) + " - 2px)"; s.style.background = TYRE[t];
        s.addEventListener("click", () => { const a = r.tyres.toUpperCase().split(/[^SMH]+|(?=[SMH])/).filter(Boolean).map(c => c[0]); a[k] = NEXT[a[k]]; r.tyres = a.join("-"); sync(row, r); refresh(row, r); schedule(); });
        bar.appendChild(s);
      });
      laps.forEach((L, k) => {
        const pin = el("div", { class: "pin", title: "lap " + L + ": drag to move, double-click to remove" }, "<span>" + L + "</span>"); pin.style.left = pct(L);
        pin.addEventListener("pointerdown", (e) => {
          e.preventDefault(); pin.setPointerCapture(e.pointerId);
          const rect = bar.getBoundingClientRect(), lo = k ? laps[k - 1] + 1 : 1, hi = k < laps.length - 1 ? laps[k + 1] - 1 : N - 1;
          const move = (ev) => {
            const v = Math.max(lo, Math.min(hi, Math.round((ev.clientX - rect.left) / rect.width * N)));
            if (v === laps[k]) return; laps[k] = v; r.laps = laps.join(",");
            if (k === 0 && r.react && +r.react > v) r.react = String(v);
            pin.style.left = pct(v); $("span", pin).textContent = v; sync(row, r); schedule();
          };
          const up = () => { pin.removeEventListener("pointermove", move); pin.removeEventListener("pointerup", up); refresh(row, r); };
          pin.addEventListener("pointermove", move); pin.addEventListener("pointerup", up);
        });
        pin.addEventListener("dblclick", (e) => { e.stopPropagation(); if (laps.length < 2) return; laps.splice(k, 1); const t = r.tyres.split("-"); t.splice(k + 1, 1); r.laps = laps.join(","); r.tyres = t.join("-"); sync(row, r); refresh(row, r); schedule(); });
        bar.appendChild(pin);
      });
      bar.ondblclick = (e) => {
        if (e.target.closest(".pin") || laps.length >= 3) return;
        const rect = bar.getBoundingClientRect(), v = Math.max(1, Math.min(N - 1, Math.round((e.clientX - rect.left) / rect.width * N)));
        if (laps.includes(v)) return;
        const all = laps.concat([v]).sort((a, b) => a - b), k = all.indexOf(v), t = r.tyres.split("-");
        t.splice(k + 1, 0, t[k] === "H" ? "M" : "H"); r.laps = all.join(","); r.tyres = t.join("-"); sync(row, r); refresh(row, r); schedule();
      };
    }
    let timer = null, cancel = null, lastAnswer = null, MX = null;
    function schedule() { clearTimeout(timer); timer = setTimeout(() => { run(); explore(); if (MX) MX.refresh(); }, 120); }
    function run() {
      if (cancel) cancel();
      const parsed = strats.map(parse); if (parsed.some(x => x.err)) return;
      const S = parsed.map(x => x.s), p = params();
      if (p.p_gs + p.p_gv >= 1) return;
      const n = +$("#lab-n").value, diffs = S.map(() => []);
      const z = F1.bonferroniZ(Math.max(1, S.length - 1));
      cancel = MC.run({ p, strategies: S, n, batch: 250, seed: 9001, ref: 0 }, (st) => {
        $("#lab-bar").style.width = (100 * st.done / st.n) + "%";
        st.newDiffs.forEach((a, j) => { if (j) for (const v of a) diffs[j].push(v); });
        const ciX = [], ciLo = [], ciHi = [], ciM = [];
        let html = "";
        S.forEach((s, j) => {
          const t = st.totals[j], d = st.diffs[j], h = z * d.sd / Math.sqrt(Math.max(1, d.n));
          let verdict = '<span class="chip ref">reference</span>';
          if (j) { verdict = d.mean + h < 0 ? '<span class="chip good">faster</span>' : d.mean - h > 0 ? '<span class="chip bad">slower</span>' : '<span class="chip meh">can\'t tell apart</span>'; ciX.push(j); ciM.push(d.mean); ciLo.push(d.mean - h); ciHi.push(d.mean + h); }
          html += '<div class="ans" style="--c:' + SCOL[j % 4] + '"><div class="top"><b>#' + (j + 1) + " " + prettyName(s).replace(/ \(.*$/, "") + "</b>" + verdict + "</div>" +
            '<div class="row"><span>mean race ' + clock(t.mean) + " ±" + (1.959964 * t.sd / Math.sqrt(t.n)).toFixed(2) + " s</span>" +
            (j ? '<span class="d">' + fx(d.mean) + " s <small>[" + fx(d.mean - h) + ", " + fx(d.mean + h) + "]</small></span>" : "<span class=\"d\">0 by definition</span>") + "</div>" +
            '<div class="row small2"><span>' + prettyName(s).replace(/^[^(]*\(/, "(") + "</span><span>1st stop under VSC/SC: " + (100 * st.pitNeutral[j]).toFixed(1) + "%</span></div></div>";
        });
        $("#lab-table").innerHTML = html;
        $("#lab-count").textContent = st.done.toLocaleString() + " / " + st.n.toLocaleString() + " races · z = " + z.toFixed(3);
        lastAnswer = { st, z, n: st.n, S };
        if (st.finished && MX) MX.answerReady();
        const ciItems = ciX.map((x, i) => ({ y: S.length - x, x0: ciLo[i], x1: ciHi[i], color: SCOL[x % 4] }));
        plot($("#lab-ci"), { y: { min: 0.5, max: S.length - 0.15, ticks: ciX.map(x => S.length - x), fmt: (v) => "#" + (S.length - v + 1) }, x: { includeZero: true }, xLabel: "strategy − reference [s]", pad: { l: 34 },
          layers: [{ type: "vline", x: 0, color: C.muted, dash: [] }, { type: "hbars", items: ciItems, h: 8, alpha: 0.85 },
            { type: "points", x: ciM, y: ciX.map(x => S.length - x), color: C.ink, r: 4 },
            { type: "labels", color: C.ink, bold: true, items: ciM.map((m, i) => ({ x: m, y: S.length - ciX[i], dy: -11, text: fx(m) + " s" })), align: "center" }] });
        const all = [].concat(...diffs.slice(1)); if (!all.length) return;
        all.sort((a, b) => a - b);
        const lo = all[Math.floor(all.length * 0.005)], hi = all[Math.floor(all.length * 0.995)], nb = 50, bw = (hi - lo) / nb || 1;
        const layers = [{ type: "vline", x: 0, color: C.muted }];
        diffs.forEach((a, j) => { if (!j || !a.length) return; const c = new Array(nb).fill(0); a.forEach(v => { const k = Math.floor((v - lo) / bw); if (k >= 0 && k < nb) c[k]++; });
          layers.push({ type: "step", x: c.map((_, k) => lo + k * bw), y: c.map(v => v / a.length), color: SCOL[j % 4], width: 2 }); });
        plot($("#lab-hist"), { x: { min: lo, max: hi + bw }, y: { min: 0 }, xLabel: "strategy − reference, race by race [s]", yLabel: "share of races", layers });
        if (st.finished) cancel = null;
      });
    }
    // ---- pit-window explorer: sweep the first stop of one strategy over common scenarios
    let exTok = 0, exPts = null, exJ = 0;
    function explore() {
      const tok = ++exTok, j = Math.min(+$("#pw-which").value || 0, strats.length - 1); exJ = j;
      const { s, err } = parse(strats[j]); if (err) return;
      const p = params(), scen = F1.drawScenarios(1000, p, 2468);
      const cur = F1.simulateAll(s, p, scen), loL = 3, hiL = s.pit_laps.length > 1 ? s.pit_laps[1] - 2 : N - 3;
      const pts = []; let L = loL;
      (function step() {
        if (tok !== exTok) return;
        for (let c = 0; c < 6 && L <= hiL; c++, L++) {
          const laps = s.pit_laps.slice(); laps[0] = L;
          const rw = s.reactive_window ? [Math.min(s.reactive_window[0], L), L] : null;
          const t = F1.simulateAll(F1.strategy(laps, s.compounds, rw), p, scen), w = new F1.Welford();
          for (let i = 0; i < t.length; i++) w.push(t[i] - cur[i]);
          const h = 1.959964 * w.sd() / Math.sqrt(w.n); pts.push({ L, m: w.mean, lo: w.mean - h, hi: w.mean + h });
        }
        draw(pts, s);
        if (L <= hiL) setTimeout(step, 0); else exPts = pts;
      })();
    }
    function draw(pts, s) {
      const best = pts.reduce((a, b) => (b.m < a.m ? b : a), pts[0]);
      plot($("#pw-chart"), { x: { min: 1, max: N }, y: {}, xLabel: "first pit stop on lap", yLabel: "vs your plan [s] (below 0 = faster)",
        legend: [{ label: "#" + (exJ + 1) + " with its first stop moved", color: SCOL[exJ % 4] }, { label: "95% CI", color: SCOL[exJ % 4], thin: true }],
        layers: [{ type: "band", x: pts.map(q => q.L), lo: pts.map(q => q.lo), hi: pts.map(q => q.hi), color: SCOL[exJ % 4], alpha: 0.2 },
          { type: "line", x: pts.map(q => q.L), y: pts.map(q => q.m), color: SCOL[exJ % 4], width: 2.4 },
          { type: "hline", y: 0, color: C.muted, dash: [] }, { type: "vline", x: s.pit_laps[0], color: C.ink, label: "your plan: lap " + s.pit_laps[0] },
          { type: "points", x: [best.L], y: [best.m], color: C.accent, r: 6 }] });
      $("#pw-txt").innerHTML = "Best first stop for #" + (exJ + 1) + " in this world: <b>lap " + best.L + "</b>, " + (best.m < 0 ? "<b>" + f2(-best.m) + " s faster</b> than your plan [" + fx(best.lo) + ", " + fx(best.hi) + "]." : "your plan is already the best lap tested.") + " Click the chart to move the stop there.";
    }
    $("#pw-chart").addEventListener("click", (e) => {
      const cv = e.currentTarget, sc = cv._scale; if (!sc || !exPts) return;
      const L = Math.round(sc.ix(e.clientX - cv.getBoundingClientRect().left)), q = exPts.find(x => x.L === L); if (!q) return;
      const r = strats[exJ], laps = r.laps.split(/[ ,;]+/).filter(Boolean); laps[0] = String(L); r.laps = laps.join(",");
      if (r.react && +r.react > L) r.react = String(L);
      buildStrats(); schedule();
    });
    $("#pw-which").addEventListener("change", explore);
    $("#lab-add").addEventListener("click", () => { strats.push({ laps: "22,44", tyres: "S-M-H", react: "" }); buildStrats(); schedule(); });
    $("#lab-run").addEventListener("click", run); $("#lab-n").addEventListener("change", schedule);
    $("#lab-reset").addEventListener("click", () => { vals = base(); worldName = "Baseline"; buildWorlds(); buildSliders(); schedule(); });
    // ---- "open the black box": the lab's own computation, slowed down, with every number substituted
    function makeMX() {
      const STEPS = [
        ["Sliders → model inputs", "the numbers the race actually uses"],
        ["Draw one random race", "Safety Cars, noise, crew luck"],
        ["Drive it lap by lap", "lap-time equation + tyre ODE"],
        ["Same race, two plans", "what cancels, what doesn't"],
        ["Repeat and average", "mean, standard error, CI"],
      ];
      let step = 0, playing = false, timerA = null, lapCur = 1, who = 1, c = null, mc = null;
      const body = $("#mx-body"), sbox = $("#mx-steps");
      const P = (v, d) => (v < 0 ? "(−" + Math.abs(v).toFixed(d) + ")" : v.toFixed(d));     // a number inside a formula
      const card = (t, eq, note) => '<div class="eqcard"><div class="eqt">' + t + '</div><div class="eq">' + eq + "</div>" + (note ? '<div class="small">' + note + "</div>" : "") + "</div>";
      const sname = (k) => "#" + (k + 1) + (k ? "" : " (ref)");
      function ctx() {
        const parsed = strats.map(parse); if (parsed.some(x => x.err)) return null;
        const S = parsed.map(x => x.s), p = params(); if (p.p_gs + p.p_gv >= 1) return null;
        const j = Math.min(Math.max(1, +$("#mx-strat").value || 1), S.length - 1);
        const i = Math.max(1, Math.min(250, Math.round(+$("#mx-race").value) || 1));
        const scen = F1.drawScenarios(250, p, 9001);          // the lab's first batch, so race #i here is race #i in the answer
        const R = S.map(s => F1.simulateOne(s, p, scen, i - 1, true));
        return { S, p, j, i, scen, R, N: p.n_laps };
      }
      function stopAnim() { clearTimeout(timerA); timerA = null; }
      function setPlaying(v) { playing = v; $("#mx-play").textContent = v ? "❚❚ Pause" : "▶ Play this step"; if (!v) stopAnim(); }
      function drawSteps() {
        sbox.innerHTML = STEPS.map((s, k) => '<li class="' + (k === step ? "on" : k < step ? "done" : "") + '" data-k="' + k + '"><span class="n">' + (k + 1) + "</span><span><b>" + s[0] + "</b><small>" + s[1] + "</small></span></li>").join("");
        sbox.querySelectorAll("li").forEach(li => li.addEventListener("click", () => go(+li.dataset.k)));
        $("#mx-prev").disabled = step === 0; $("#mx-next").disabled = step === STEPS.length - 1;
      }
      function go(k) { setPlaying(false); step = Math.max(0, Math.min(STEPS.length - 1, k)); if (step === 2) lapCur = 1; if (step === 4) mc = null; drawSteps(); render(); }
      function render() {
        c = ctx(); if (!c) { body.innerHTML = '<p class="warn">Fix the strategy or world errors above first.</p>'; return; }
        who = Math.min(who, c.S.length - 1);
        [s0, s1, s2, s3, s4][step]();
      }

      // ---- step 1: parameters to derived inputs
      function s0() {
        const p = c.p, m = F1.meanCrew(p), g = p.dT_green_s, lane = [0, p.alpha_vsc, p.alpha_sc].map(a => (1 - a) * g);
        body.innerHTML = '<p class="mx-intro">Before any race runs, the slider values become the few numbers the simulation really uses. Move a slider in the World panel and watch them change.</p><div class="eqgrid">' +
          card("Pit-lane time lost at racing speed", "ΔT<sub>G</sub> = T<sub>pit</sub> − T<sub>bypass</sub> = " + f2(p.t_pit_s, 1) + " − " + f2(p.t_bypass_s, 1) + " = <b>" + f2(g, 1) + " s</b>", "T<sub>pit</sub> is a slider. T<sub>bypass</sub> is how long the same stretch of track takes at racing speed.") +
          card("Why stops are cheaper under VSC / SC", "α<sub>VSC</sub> = (k<sub>VSC</sub> − 1)·T<sub>bypass</sub> / ΔT<sub>G</sub> = (" + p.k_vsc.toFixed(2) + " − 1)×" + f2(p.t_bypass_s, 1) + " / " + f2(g, 1) + " = <b>" + f2(p.alpha_vsc, 3) + "</b><br>α<sub>SC</sub> = (" + p.k_sc.toFixed(2) + " − 1)×" + f2(p.t_bypass_s, 1) + " / " + f2(g, 1) + " = <b>" + f2(p.alpha_sc, 3) + "</b>", "The field drives slowly, so the pit lane loses less against it. The lane costs (1 − α)·ΔT<sub>G</sub>.") +
          card("Average pit-crew time", "E[C] = c<sub>0</sub> + e<sup>μ + σ²/2</sup> = " + f2(p.crew_shift_s, 1) + " + e<sup>" + f2(p.crew_mu, 2) + " + " + f2(p.crew_sigma, 2) + "²/2</sup> = <b>" + f2(m, 2) + " s</b>", "σ is the crew-time spread slider. Every real stop draws its own crew time.") +
          card("So an average stop costs", ["Green", "VSC", "SC"].map((n, k) => n + ": " + f2(lane[k], 1) + " + " + f2(m, 2) + " = <b>" + f2(lane[k] + m, 1) + " s</b>").join("<br>"), "Lane loss (1 − α)·ΔT<sub>G</sub> plus the crew time.") +
          card("How often the race is neutralised", "from a Green lap: P(SC) = <b>" + f2(p.p_gs, 3) + "</b>, P(VSC) = <b>" + f2(p.p_gv, 3) + "</b><br>on lap 1: P(SC) = <b>" + f2(p.p_lap1_sc, 2) + "</b><br>mean SC length = m + p/(1 − p) = " + p.sc_min_laps + " + " + f2(p.p_ss, 2) + "/" + f2(1 - p.p_ss, 2) + " = <b>" + f2(F1.scMeanDuration(p), 2) + " laps</b>", "These feed the Markov chain that writes each race's Green / VSC / SC sequence.") +
          card("Tyres and fuel", "dw/da = k<sub>c</sub>·(1 + β·m)·(1 + η·w)·φ<br>k<sub>S</sub> = <b>" + p.k_s_per_lap.SOFT.toFixed(3) + "</b>, k<sub>M</sub> = <b>" + p.k_s_per_lap.MEDIUM.toFixed(3) + "</b>, k<sub>H</sub> = <b>" + p.k_s_per_lap.HARD.toFixed(4) + "</b> s/lap, η = <b>" + p.eta_per_s.toFixed(3) + "</b><br>fuel m<sub>l</sub> = " + p.m0_kg + " − " + p.burn_kg_per_lap + "·(l − 1) kg, worth γ = " + p.gamma_s_per_kg + " s/kg", "φ = 1 on Green, " + p.phi_vsc + " under VSC and " + p.phi_sc + " under SC: tyres barely wear behind the Safety Car.") +
          "</div>";
      }

      // ---- step 2: one random race
      function s1() {
        const { p, i, scen, N, R, j } = c, st = Array.from(scen.status.slice((i - 1) * N, i * N)), per = [];
        for (let l = 0; l < N; l++) if (st[l] && (!l || st[l - 1] !== st[l])) { let e = l; while (e + 1 < N && st[e + 1] === st[l]) e++; per.push((st[l] === 2 ? "Safety Car" : "VSC") + " laps " + (l + 1) + (e > l ? "–" + (e + 1) : "")); }
        const zs = [], z0 = (i - 1) * N;
        for (let l = 0; l < N && zs.length < 5; l++) if (!st[l]) zs.push("lap " + (l + 1) + ": z = " + P(scen.zLap[z0 + l], 2) + ", so ε = σ·z = " + f2(p.sigma_s, 2) + "×" + P(scen.zLap[z0 + l], 2) + " = <b>" + fx(p.sigma_s * scen.zLap[z0 + l]) + " s</b>");
        const nStops = Math.max(R[0].stops.length, R[j].stops.length), cr = [];
        for (let k = 0; k < nStops; k++) { const z = scen.zCrew[(i - 1) * F1.MAX_STOPS + k]; cr.push("stop " + (k + 1) + ": z = " + P(z, 2) + ", so C = " + f2(p.crew_shift_s, 1) + " + e<sup>" + f2(p.crew_mu, 2) + " + " + f2(p.crew_sigma, 2) + "×" + P(z, 2) + "</sup> = <b>" + f2(F1.crewTimeFromNormal(z, p), 2) + " s</b>"); }
        body.innerHTML = '<p class="mx-intro">Race #' + i + " is one row of the lab's random races. Three separate random streams are drawn for it, and <b>every strategy gets this exact same row</b>. That is what \"common random numbers\" means.</p>" +
          '<div class="mx-race"><div class="mx-strip" style="grid-template-columns:repeat(' + N + ',1fr)">' + st.map((v, l) => '<i class="' + (v === 1 ? "v" : v === 2 ? "s" : "") + '" title="lap ' + (l + 1) + '"></i>').join("") + '</div><div class="mx-axis"><span>lap 1</span><span>lap ' + N + "</span></div></div>" +
          '<div class="eqgrid">' +
          card("① Track status (Markov chain)", per.length ? per.join("<br>") : "All Green: no VSC or Safety Car in this race.", "Each lap: from Green, the chain starts a Safety Car with probability " + f2(p.p_gs, 3) + " and a VSC with " + f2(p.p_gv, 3) + ". Once out, an SC stays for at least " + p.sc_min_laps + " laps.") +
          card("② Lap-time noise (Green laps only)", zs.join("<br>") + "<br>…one z per lap", "z is a standard normal draw (Box–Muller), scaled by the noise slider σ.") +
          card("③ Pit-crew luck", cr.join("<br>") || "no stops", "Stop k of every strategy uses the same z, so neither plan gets luckier crews.") +
          '</div><p class="small">Try another race number at the top right. Race numbers 1–250 are exactly the first 250 races in the Answer panel.</p>';
      }

      // ---- step 3: the lap loop for one strategy
      function s2() {
        const { S, j } = c;
        if (who !== 0) who = j;
        body.innerHTML = '<div class="mx-who">Showing <button class="tab' + (who === 0 ? " on" : "") + '" data-w="0">' + sname(0) + '</button><button class="tab' + (who === j ? " on" : "") + '" data-w="' + j + '">' + sname(j) + "</button> <span class=\"small\">" + prettyName(S[who === 0 ? 0 : j]) + '</span></div>' +
          '<div class="mx-lapgrid"><div><div class="lapline"><input id="mx-lap" type="range" min="1" max="' + c.N + '" value="' + lapCur + '" aria-label="lap"><span class="lapread">Lap <b id="mx-lapn"></b> / ' + c.N + '</span></div><div id="mx-eq"></div></div>' +
          '<figure class="mx-fig"><figcaption>Time of each lap above t₀ [s] <small>(pit laps include the stop)</small></figcaption><canvas id="mx-laps" data-h="220"></canvas><div class="mx-total" id="mx-total"></div></figure></div>';
        body.querySelectorAll("[data-w]").forEach(b => b.addEventListener("click", () => { who = +b.dataset.w; s2(); }));
        $("#mx-lap").addEventListener("input", (e) => { setPlaying(false); lapCur = +e.target.value; lapView(); });
        lapView();
      }
      function lapView() {
        const { p, R, S, N, scen, i } = c, r = R[who], s = S[who], x = r.laps[lapCur - 1], l = lapCur;
        $("#mx-lapn").textContent = l; $("#mx-lap").value = l;
        const comp = x.compound, cn = comp.toLowerCase();
        let eq;
        if (x.status === 0) {
          const z = scen.zLap[(i - 1) * N + l - 1];
          eq = '<div class="eqrow">t<sub>' + l + "</sub> = t₀ + Δc + w + γ·m<sub>" + l + "</sub> + σ·z<sub>" + l + "</sub></div>" +
            '<div class="eqrow terms"><span><b>' + f2(p.t0_s) + "</b><small>base pace</small></span>+<span><b>" + f2(x.offset) + "</b><small>" + cn + " offset</small></span>+<span><b>" + f2(x.wear, 3) + "</b><small>tyre wear, " + x.age + " laps old</small></span>+<span><b>" + p.gamma_s_per_kg + "×" + f2(x.fuel, 1) + "</b><small>fuel " + f2(x.fuel, 1) + " kg</small></span>+<span><b>" + f2(p.sigma_s, 2) + "×" + P(z, 2) + "</b><small>noise</small></span></div>" +
            '<div class="eqrow">= ' + f2(p.t0_s) + " + " + f2(x.offset) + " + " + f2(x.wear, 3) + " + " + f2(x.fuelTime, 3) + " + " + P(x.noise, 3) + " = <b>" + f2(x.time - x.pit, 3) + " s</b></div>";
        } else {
          const k = x.status === 2 ? p.k_sc : p.k_vsc, nm = x.status === 2 ? "SC" : "VSC";
          eq = '<div class="eqrow">' + nm + " lap: t<sub>" + l + "</sub> = k<sub>" + nm + "</sub>·t₀ = " + k.toFixed(2) + " × " + f2(p.t0_s) + " = <b>" + f2(x.base) + ' s</b></div><div class="small">Everyone follows the ' + (x.status === 2 ? "Safety Car" : "VSC delta") + " at the same pace, so tyre, fuel and noise terms do not apply on this lap.</div>";
        }
        if (x.pit) {
          const a = x.status === 0 ? 0 : x.status === 1 ? p.alpha_vsc : p.alpha_sc;
          eq += '<div class="eqrow pitrow">+ pit stop: (1 − α)·ΔT<sub>G</sub> + C = (1 − ' + f2(a, 3) + ")×" + f2(p.dT_green_s, 1) + " + " + f2(x.crew, 2) + " = <b>" + f2(x.pit, 2) + " s</b>, so the lap takes <b>" + f2(x.time, 3) + " s</b></div>";
        }
        // the RK4 step that produces next lap's wear
        const kp = p.k_s_per_lap[comp] * [1, p.phi_vsc, p.phi_sc][x.status], b = p.beta_per_kg, et = p.eta_per_s, w = x.wear;
        const g0 = kp * (1 + b * x.fuel), gh = kp * (1 + b * (x.fuel - p.burn_kg_per_lap * 0.5)), g1 = kp * (1 + b * (x.fuel - p.burn_kg_per_lap));
        const k1 = g0 * (1 + et * w), k2 = gh * (1 + et * (w + 0.5 * k1)), k3 = gh * (1 + et * (w + 0.5 * k2)), k4 = g1 * (1 + et * (w + k3)), wn = w + (k1 + 2 * k2 + 2 * k3 + k4) / 6;
        eq += '<div class="eqcard rk"><div class="eqt">Tyre wear for the next lap: one RK4 step of dw/da = k·(1 + β·m)·(1 + η·w)·φ, step h = 1 lap</div><div class="eq">' +
          "k₁ = " + f2(k1, 4) + ", k₂ = " + f2(k2, 4) + ", k₃ = " + f2(k3, 4) + ", k₄ = " + f2(k4, 4) + "<br>w<sub>next</sub> = w + (k₁ + 2k₂ + 2k₃ + k₄)/6 = " + f2(w, 4) + " + " + f2(wn - w, 4) + " = <b>" + f2(wn, 4) + " s</b>" +
          (x.pit ? '<br><span class="good">New tyres fitted at this stop, so w restarts from 0 next lap.</span>' : "") + "</div></div>";
        $("#mx-eq").innerHTML = eq;
        const xs = r.laps.map(q => q.lap), ys = r.laps.map(q => q.time - p.t0_s);
        const cols = r.laps.map((q, k) => k >= l ? "--line" : q.pit ? C.s3 : q.status ? STATUS_COL[q.status] : TYRE[q.compound]);
        plot($("#mx-laps"), { x: { min: 0.5, max: N + 0.5 }, y: { min: 0, max: Math.max(...ys) * 1.05 }, xLabel: "lap", yLabel: "t − t₀ [s]",
          layers: [{ type: "bars", x: xs, y: ys, w: 1, colors: cols }, { type: "vline", x: l, color: C.ink, dash: [1, 3] }] });
        $("#mx-total").innerHTML = "Running total after lap " + l + ": Σ t = <b>" + clock(x.cum) + "</b>" + (l === N ? " ← race time T for " + sname(who) : "");
      }

      // ---- step 4: same race, both strategies, component by component
      function s3() {
        const { R, j, p } = c, comp = (r) => {
          const o = { racing: 0, slow: 0, offset: 0, wear: 0, fuel: 0, noise: 0, lane: 0, crew: 0 };
          r.laps.forEach(x => { if (x.status) o.slow += x.base; else o.racing += x.base; o.offset += x.offset; o.wear += x.wearTime; o.fuel += x.fuelTime; o.noise += x.noise; if (x.pit) { o.lane += x.pit - x.crew; o.crew += x.crew; } });
          return o; };
        const A = comp(R[0]), B = comp(R[j]);
        const rows = [["racing", "Green laps at base pace t₀"], ["slow", "VSC / SC laps at k·t₀"], ["fuel", "Fuel weight γ·m"], ["noise", "Lap-time noise σ·z"], ["offset", "Compound offsets Δc"], ["wear", "Tyre wear w"], ["lane", "Pit-lane loss (1 − α)·ΔT<sub>G</sub>"], ["crew", "Crew time C"]];
        const D = R[j].total - R[0].total, mx = Math.max(0.01, ...rows.map(([k]) => Math.abs(B[k] - A[k])));
        body.innerHTML = '<p class="mx-intro">Both plans drove race #' + c.i + ". Add up every lap, term by term. Terms that depend only on the race (not on the plan) are <b>identical</b> and cancel in the difference. Only the plan-dependent terms are left. This is why paired comparisons are so precise.</p>" +
          '<table class="mx-table"><tr><th>term, summed over all ' + c.N + " laps</th><th>" + sname(0) + "</th><th>" + sname(j) + "</th><th>difference</th><th></th></tr>" +
          rows.map(([k, n]) => { const d = B[k] - A[k], z = Math.abs(d) < 1e-9;
            return "<tr" + (z ? ' class="cancel"' : "") + "><td>" + n + "</td><td>" + f2(A[k], 2) + "</td><td>" + f2(B[k], 2) + "</td><td>" + (z ? '<span class="chip ref">0, cancels</span>' : "<b>" + fx(d) + "</b>") + '</td><td class="barcell">' + (z ? "" : '<span class="dbar ' + (d < 0 ? "neg" : "pos") + '" style="width:' + (50 * Math.abs(d) / mx) + "%\"></span>") + "</td></tr>"; }).join("") +
          '<tr class="tot"><td>Race time T</td><td>' + f2(R[0].total, 2) + "</td><td>" + f2(R[j].total, 2) + "</td><td><b>" + fx(D) + "</b></td><td></td></tr></table>" +
          '<div class="verdict">In race #' + c.i + ", D<sub>" + c.i + "</sub> = T<sub>" + sname(j) + "</sub> − T<sub>ref</sub> = " + f2(R[j].total, 2) + " − " + f2(R[0].total, 2) + " = <b>" + fx(D) + " s</b>. " + (D < 0 ? sname(j) + " was faster in this race." : sname(j) + " was slower in this race.") + " One race proves little, so next we repeat this for thousands of races.</div>";
      }

      // ---- step 5: Monte Carlo, slowed down at the start
      function s4() {
        const n = +$("#lab-n").value;
        body.innerHTML = '<p class="mx-intro">Now repeat step 4 for ' + n.toLocaleString() + " races, keeping a running average of D. The first races go one at a time so you can follow the arithmetic; then it speeds up. The races come in the same batches as the Answer panel, so the final number must match it exactly.</p>" +
          '<div class="mx-mcgrid"><div id="mx-mceq" class="eqcard"></div><div class="grid2" style="margin:0"><figure class="mx-fig"><figcaption>Each race\'s difference D<sub>i</sub> <small>(first 250 races)</small></figcaption><canvas id="mx-dots" data-h="210"></canvas></figure>' +
          '<figure class="mx-fig"><figcaption>Running mean with its 95% CI <small>(narrows like 1/√n)</small></figcaption><canvas id="mx-conv" data-h="210"></canvas></figure></div></div>';
        if (!mc) mcReset();
        mcView();
      }
      function mcReset() {
        const n = +$("#lab-n").value, k = Math.max(1, c.S.length - 1);
        mc = { n, done: 0, b: 0, buf: null, pos: 0, w: new F1.Welford(), dots: [], hist: [], last: null, prevMean: 0, z: F1.bonferroniZ(k), k };
      }
      function mcStep() {                      // returns how many races were added this tick
        const { S, p, j } = c;
        let add = mc.done < 12 ? 1 : mc.done < 60 ? 4 : mc.done < 250 ? 25 : 250;
        let added = 0;
        while (added < add && mc.done < mc.n) {
          if (!mc.buf || mc.pos >= mc.buf.length) {
            const m = Math.min(250, mc.n - mc.done), scen = F1.drawScenarios(m, p, (9001 + 7919 * mc.b) >>> 0); mc.b++;
            const a = F1.simulateAll(S[0], p, scen), bb = F1.simulateAll(S[j], p, scen), d = new Float64Array(m);
            for (let q = 0; q < m; q++) d[q] = bb[q] - a[q];
            mc.buf = d; mc.pos = 0;
          }
          const d = mc.buf[mc.pos++]; mc.prevMean = mc.w.mean; mc.w.push(d); mc.done++; mc.last = d; added++;
          if (mc.done <= 250) mc.dots.push(d);
          if (mc.done < 30 || mc.done % 10 === 0 || mc.done === mc.n) { const h = mc.w.n > 1 ? mc.z * mc.w.sd() / Math.sqrt(mc.w.n) : NaN; mc.hist.push([mc.done, mc.w.mean, mc.w.mean - h, mc.w.mean + h]); }
        }
        return added;
      }
      function mcView() {
        const w = mc.w, n = w.n, j = c.j;
        const sd = w.sd(), se = n > 1 ? sd / Math.sqrt(n) : NaN, h = mc.z * se;
        let eq;
        if (!n) eq = '<div class="eqt">Press ▶ Play to start racing.</div><div class="eq">D<sub>i</sub> = T<sub>' + sname(j) + ",i</sub> − T<sub>ref,i</sub> for races i = 1, 2, …, " + mc.n.toLocaleString() + "</div>";
        else {
          eq = '<div class="eqt">After race <b>' + n.toLocaleString() + "</b> of " + mc.n.toLocaleString() + "</div><div class=\"eq\">" +
            "newest race: D<sub>" + n + "</sub> = <b>" + fx(mc.last) + " s</b><br>" +
            "mean: D̄<sub>" + n + "</sub> = D̄<sub>" + (n - 1) + "</sub> + (D<sub>" + n + "</sub> − D̄<sub>" + (n - 1) + "</sub>)/" + n + " = " + P(mc.prevMean, 3) + " + (" + P(mc.last, 3) + " − " + P(mc.prevMean, 3) + ")/" + n + " = <b>" + fx(w.mean, 3) + " s</b><br>" +
            (n > 1 ? "spread of the D's: s = <b>" + f2(sd, 3) + " s</b><br>standard error: SE = s/√n = " + f2(sd, 3) + "/√" + n + " = <b>" + f2(se, 3) + " s</b><br>" +
              "95% CI: D̄ ± z·SE = " + fx(w.mean, 3) + " ± " + mc.z.toFixed(3) + "×" + f2(se, 3) + " = <b>[" + fx(w.mean - h) + ", " + fx(w.mean + h) + "] s</b>" +
              (mc.k > 1 ? '<br><small>z = ' + mc.z.toFixed(3) + " instead of 1.960: a Bonferroni correction because " + mc.k + " strategies are compared with the reference at once.</small>" : "") : "you need at least 2 races for a spread") + "</div>";
          if (n > 1) eq += '<div class="verdict">' + (w.mean + h < 0 ? sname(j) + " is <b class=\"good\">faster</b>: the whole CI is below 0." : w.mean - h > 0 ? sname(j) + " is <b class=\"bad\">slower</b>: the whole CI is above 0." : "The CI still contains 0, so we <b>can't tell them apart</b> yet.") + "</div>";
          if (mc.done >= mc.n && lastAnswer && lastAnswer.st.finished && lastAnswer.S.length === c.S.length) {
            const a = lastAnswer.st.diffs[j];
            eq += '<div class="small match">' + (Math.abs(a.mean - w.mean) < 1e-9 ? "✓ Matches the Answer panel exactly: " + fx(a.mean, 3) + " s. Same races, same order, same arithmetic." : "The Answer panel shows " + fx(a.mean, 3) + " s; it may still be catching up with your last change.") + "</div>";
          }
        }
        $("#mx-mceq").innerHTML = eq;
        const dots = mc.dots, col = SCOL[j % 4];
        plot($("#mx-dots"), { x: { min: 0, max: 251 }, y: { includeZero: true }, xLabel: "race i", yLabel: "D_i [s]",
          layers: [{ type: "hline", y: 0, color: C.muted, dash: [] }, { type: "points", x: dots.map((_, k) => k + 1), y: dots, color: col, r: 2.6, alpha: 0.75 }]
            .concat(n ? [{ type: "hline", y: w.mean, color: C.ink, dash: [5, 4], label: "mean " + fx(w.mean) }] : []) });
        const H = mc.hist.filter(q => isFinite(q[2]));
        plot($("#mx-conv"), { x: { log: true, min: 1, max: mc.n }, y: { includeZero: true }, xLabel: "races so far (log scale)", yLabel: "mean D [s]",
          layers: [{ type: "hline", y: 0, color: C.muted, dash: [] }, { type: "band", x: H.map(q => q[0]), lo: H.map(q => q[2]), hi: H.map(q => q[3]), color: col, alpha: 0.2 },
            { type: "line", x: mc.hist.map(q => q[0]), y: mc.hist.map(q => q[1]), color: col, width: 2.2 }] });
      }

      // ---- playback
      const speed = () => +$("#mx-speed").value;
      function tick() {
        if (!playing) return;
        if (step === 2) {
          if (lapCur >= c.N) { next(); return; }
          lapCur++; lapView(); timerA = setTimeout(tick, speed() / 2);
        } else if (step === 4) {
          if (mc.done >= mc.n) { setPlaying(false); return; }
          mcStep(); mcView(); timerA = setTimeout(tick, mc.done <= 12 ? speed() * 2 : mc.done <= 250 ? speed() / 2 : 30);
        } else timerA = setTimeout(next, speed() * 12);
      }
      function next() { if (step >= STEPS.length - 1) { setPlaying(false); return; } const was = playing; go(step + 1); if (was) { setPlaying(true); timerA = setTimeout(tick, speed()); } }
      $("#mx-play").addEventListener("click", () => {
        if (playing) { setPlaying(false); return; }
        if (step === 2 && lapCur >= c.N) { lapCur = 1; lapView(); }
        if (step === 4 && mc && mc.done >= mc.n) { mcReset(); mcView(); }
        setPlaying(true); tick();
      });
      $("#mx-next").addEventListener("click", () => go(step + 1));
      $("#mx-prev").addEventListener("click", () => go(step - 1));
      $("#mx-strat").addEventListener("change", () => { mc = null; render(); });
      $("#mx-race").addEventListener("change", () => render());
      $("#lab-explain").addEventListener("click", () => { $("#lab-math").scrollIntoView({ behavior: "smooth", block: "start" }); go(0); });
      drawSteps(); render();
      return {
        refresh() { setPlaying(false); mc = null; render(); },
        answerReady() { if (step === 4 && mc && mc.done >= mc.n) mcView(); },
      };
    }
    buildWorlds(); buildSliders(); buildStrats();
    MX = makeMX();
    const io = new IntersectionObserver((es) => { if (es.some(e => e.isIntersecting)) { io.disconnect(); run(); explore(); } }, { rootMargin: "300px" });
    io.observe($("#lab"));
  })();

  // ============================================================ NOTEBOOK RESULTS + live re-run
  (function () {
    const z = NB.bonferroni_z;
    function table(live) {
      let h = "<tr><th>strategy</th><th>notebook mean</th><th>notebook diff vs one-stop</th><th>browser re-run diff</th><th>agree?</th></tr>";
      NB.stage2.forEach((r, j) => {
        let lv = "…", ok = "";
        if (live && live.diffs[j] && j) {
          const d = live.diffs[j], hh = z * d.sd / Math.sqrt(d.n); lv = fx(d.mean) + " s [" + fx(d.mean - hh) + ", " + fx(d.mean + hh) + "] (n=" + d.n.toLocaleString() + ")";
          const se = Math.hypot(d.sd / Math.sqrt(d.n), (r.diff_high_s - r.diff_s) / z); const zz = (d.mean - r.diff_s) / se;
          ok = live.finished ? (Math.abs(zz) < 3 ? '<span class="good">✓ within noise (z = ' + zz.toFixed(2) + ")</span>" : '<span class="bad">✗ z = ' + zz.toFixed(2) + "</span>") : "running";
        } else if (!j) { lv = "reference"; ok = ""; }
        h += '<tr><td><i class="sw" style="background:' + SCOL[j] + '"></i>' + SHORT[j].label + "</td><td>" + clock(r.mean_s) + " ±" + (r.ci_high_s - r.mean_s).toFixed(2) + "</td><td>" +
          (j ? fx(r.diff_s) + " s [" + fx(r.diff_low_s) + ", " + fx(r.diff_high_s) + "]" : "reference") + "</td><td>" + lv + "</td><td>" + ok + "</td></tr>";
      });
      $("#nb-table").innerHTML = h + '<tr><td colspan="5" class="small" style="font-family:inherit">Notebook: seed 20251005+22, N = 10,000, Bonferroni z = ' + z.toFixed(3) + ". CRN variance reduction for the two-stop vs one-stop difference: " + NB.crn_ratio.toFixed(0) + "×. The browser re-run uses a different random generator, so it should agree within noise, not digit for digit.</td></tr>";
    }
    table(null);
    const io = new IntersectionObserver((es) => { if (es.some(e => e.isIntersecting)) { io.disconnect(); MC.run({ p: P0, strategies: SHORT, n: 10000, batch: 500, seed: 31337, ref: 0 }, table); } }, { rootMargin: "300px" });
    io.observe($("#results"));
    const xs = NB.sweep.map(r => r.p_gs);
    plot($("#nb-sweep"), { x: { min: 0, max: 0.06 }, y: { includeZero: true }, xLabel: "P_GS (Safety-Car onset per Green lap)", yLabel: "paired difference [s]",
      legend: [{ label: "two-stop − one-stop", color: C.s2 }, { label: "pit-if-neutralised − one-stop", color: C.s3 }],
      layers: [{ type: "band", x: xs, lo: NB.sweep.map(r => r.two[1]), hi: NB.sweep.map(r => r.two[2]), color: C.s2, alpha: 0.3 }, { type: "line", x: xs, y: NB.sweep.map(r => r.two[0]), color: C.s2, width: 2.2 },
        { type: "points", x: xs, y: NB.sweep.map(r => r.two[0]), color: C.s2 },
        { type: "band", x: xs, lo: NB.sweep.map(r => r.react[1]), hi: NB.sweep.map(r => r.react[2]), color: C.s3, alpha: 0.3 }, { type: "line", x: xs, y: NB.sweep.map(r => r.react[0]), color: C.s3, width: 2.2 },
        { type: "points", x: xs, y: NB.sweep.map(r => r.react[0]), color: C.s3 },
        { type: "hline", y: 0, color: C.muted, dash: [] }, { type: "vline", x: 0.02, color: C.muted, label: "baseline" }, { type: "vline", x: 0.0419, color: C.accent, label: "switch ≈ 0.042" }] });
    const names = { p_gs: "P_GS", alpha_sc: "α_SC", sc_min_laps: "min SC length m", crew_sigma: "crew spread σ_C", k_hard: "HARD wear rate" };
    const groups = Object.keys(names), items = [], labels = [];
    groups.forEach((g, i) => {
      const rr = NB.sensitivity.filter(r => r.param === g), lo = Math.min(...rr.map(r => r.mean)), hi = Math.max(...rr.map(r => r.mean));
      items.push({ y: groups.length - i, x0: lo, x1: hi, color: C.s2 });
      labels.push({ x: hi, y: groups.length - i, dx: 6, text: names[g] + " (" + rr.map(r => r.value).join(" / ") + ")  swing " + (hi - lo).toFixed(2) + " s" });
    });
    plot($("#nb-tornado"), { x: { min: 2, max: 24 }, y: { min: 0.3, max: groups.length + 0.7, ticks: [] }, xLabel: "two-stop − one-stop mean difference [s]", pad: { l: 14 },
      layers: [{ type: "hbars", items, h: 20, alpha: 0.75 }, { type: "vline", x: NB.stage2[1].diff_s, color: C.accent, label: "baseline" }, { type: "labels", color: C.ink, items: labels }] });
  })();

  // ============================================================ WHAT IF
  lazy("#whatif", function () {
    const S = (laps, t, rw, name) => { const s = F1.strategy(laps, t.split("-").map(c => ({ S: "SOFT", M: "MEDIUM", H: "HARD" })[c]), rw); s.label = name; return s; };
    const scr = (N, segs, def) => { const s = new Array(N).fill(def == null ? 0 : def); segs.forEach(([a, b, v]) => { for (let l = a; l <= Math.min(b, N); l++) s[l - 1] = v; }); return s; };
    const SCN = [
      { id: "lap14", tab: "Singapore 2008", label: "Inspired by Singapore 2008 · 61 laps",
        title: "What if the early stopper had not been rescued by a Safety Car?",
        story: "<p>In the first night race, the eventual winner pitted very early, around lap 12. A Safety Car came out a couple of laps later, after a crash that was later found to have been deliberate. Under the rules of the time, the pit lane stayed closed until the field had bunched up, so rivals could not stop straight away, and the early stopper vaulted up the order.</p><p>Here our car runs three plans through that race, with and without the Safety Car (laps 14–17).</p>",
        n_laps: 61, strategies: [S([33], "H-M", null, "Planned one-stop H→M, lap 33"), S([12], "M-H", null, "Early stop M→H, lap 12"), S([28], "M-H", [12, 28], "Pit-if-neutralised M→H (plan lap 28)")],
        variants: [{ label: "With the Safety Car (laps 14–17)", script: scr(61, [[14, 17, 2]]) }, { label: "No Safety Car at all", script: scr(61, []) }],
        verdict: (R) => "In pure time, the early stop is <b>" + fx(R[0][1].mean, 1) + " s</b> behind the planned one-stop even <i>with</i> the Safety Car. Without it, the gap grows to <b>" + fx(R[1][1].mean, 1) + " s</b>. The car that boxed <i>under</i> the Safety Car gains <b>" + f2(-R[0][2].mean, 1) + " s</b> over the plan. So the model says the early stop was not fast in itself. Its value in the real race came from track position and the pit-lane closure, which this one-car model does not include. This is an honest limit worth seeing." },
      { id: "late", tab: "Abu Dhabi 2021", label: "Inspired by Abu Dhabi 2021 · 58 laps",
        title: "Your tyres are 40 laps old and a Safety Car comes out. Do you box?",
        story: "<p>A championship was decided when a Safety Car came out with about five laps to go. The leader stayed out on old hard tyres, the chaser pitted for fresh softs, and racing resumed for a final lap.</p><p>Move the slider to choose <b>when</b> the Safety Car (5 laps) starts. Our car ran mediums to lap 14 then hards. It either stays out or pits for softs under the Safety Car.</p>",
        n_laps: 58, slider: { label: "Safety Car starts on lap", min: 20, max: 54, value: 53 },
        build: (L) => ({ strategies: [S([14], "M-H", null, "Stay out (one stop, lap 14)"), S([14, L], "M-H-S", null, "Box for softs under the SC (lap " + L + ")")],
          variants: [{ label: "Safety Car laps " + L + "–" + Math.min(L + 4, 57), script: scr(58, [[L, Math.min(L + 4, 57), 2]]) }] }),
        curve: true,
        verdict: (R, L, curve) => { const d = R[0][1].mean; const win = curve.filter(c => c.y < 0).map(c => c.x);
          return "With the Safety Car on lap " + L + ", boxing is <b>" + fx(d, 1) + " s</b> " + (d < 0 ? "faster" : "slower") + " in expected race time. " +
            (win.length ? "Pitting pays only if the SC starts between laps <b>" + win[0] + "</b> and <b>" + win[win.length - 1] + "</b>. Earlier than that, the softs have too many laps left to survive. Later, too few laps remain to repay even the cheaper stop." : "In this model, pitting never pays.") +
            " In the real race the stop was about track position on a one-lap restart, which a time-only model cannot capture." } },
      { id: "vsc", tab: "Singapore 2023", label: "Inspired by Singapore 2023 · 62 laps",
        title: "Is a second stop under a late Virtual Safety Car worth it?",
        story: "<p>A Safety Car around lap 20 let most of the field make their only stop cheaply. Then a Virtual Safety Car around lap 44 tempted some teams into a second stop for fresh mediums and a late charge.</p><p>Our car tries three plans. The what-if: what if that VSC had never happened?</p>",
        n_laps: 62, strategies: [S([20], "M-H", null, "One stop under the SC (lap 20)"), S([20, 44], "M-H-M", null, "SC stop + second stop under the VSC (lap 44)"), S([34], "H-M", null, "Ignore the SC: planned one-stop H→M, lap 34")],
        variants: [{ label: "As it happened (SC 20–23, VSC 44–45)", script: scr(62, [[20, 23, 2], [44, 45, 1]]) }, { label: "No VSC (SC 20–23 only)", script: scr(62, [[20, 23, 2]]) }],
        verdict: (R) => "Taking the cheap VSC stop costs only <b>" + fx(R[0][1].mean, 1) + " s</b> of pure race time over the remaining 18 laps, close to break-even. Without the VSC, the same stop at Green costs <b>" + fx(R[1][1].mean, 1) + " s</b>. Ignoring the Safety Car altogether costs <b>" + fx(R[0][2].mean, 1) + " s</b>. Near break-even in time, the fresher tyres became a chance to overtake, which is why the gamble looked attractive." },
      { id: "nosc", tab: "Singapore 2024/25", label: "Inspired by Singapore 2024 and 2025",
        title: "The street race that had a Safety Car every year until it didn't",
        story: "<p>From 2008 to 2023 every race here had at least one Safety Car. Then 2024 and 2025 ran without one. Strategists plan for the average, but each race happens only once.</p><p>Compare the same three plans in a race that stays Green, at the baseline SC rate, and at double the rate.</p>",
        n_laps: 62, strategies: SHORT.map(s => Object.assign({}, s)),
        variants: [{ label: "All Green (as in 2024/25)", script: scr(62, []) }, { label: "Random SCs, P_GS = 0.02 (baseline)", script: null }, { label: "Random SCs, P_GS = 0.04", script: null, p: { p_gs: 0.04 } }],
        verdict: (R) => "In an all-Green race, the pit-if-neutralised plan simply runs its planned stop and is <b>" + fx(R[0][2].mean, 1) + " s</b> behind the best one-stop. At the baseline rate the gap shrinks to <b>" + fx(R[1][2].mean, 1) + " s</b>, and at double the rate it is <b>" + fx(R[2][2].mean, 1) + " s</b>. The two-stop never pays: <b>" + fx(R[0][1].mean, 1) + "</b>, <b>" + fx(R[1][1].mean, 1) + "</b> and <b>" + fx(R[2][1].mean, 1) + " s</b>." },
      { id: "kmh", tab: "60 km/h pit lane", label: "What if the pit-lane limit had not been raised?",
        title: "What if the pit-lane speed limit had stayed at 60 km/h?",
        story: "<p>For 2025 the pit-lane speed limit here rose from 60 to 80 km/h, which cut the cost of a stop by roughly 6 seconds. Did that change which strategy is best?</p><p>We rerun the shortlisted plans with a 6-second-slower pit lane (T<sub>pit</sub> = 42 s), with random Safety Cars at the baseline rate.</p>",
        n_laps: 62, strategies: SHORT.map(s => Object.assign({}, s)),
        variants: [{ label: "80 km/h (T_pit = 36 s)", script: null }, { label: "60 km/h (T_pit = 42 s)", script: null, p: { t_pit_s: 42 } }],
        verdict: (R) => "A slower lane roughly doubles the two-stop's penalty, from <b>" + fx(R[0][1].mean, 1) + " s</b> to <b>" + fx(R[1][1].mean, 1) + " s</b>, because it pays the lane twice. The pit-if-neutralised plan barely moves (<b>" + fx(R[0][2].mean, 1) + "</b> → <b>" + fx(R[1][2].mean, 1) + " s</b>): both plans stop once, so the extra lane time cancels in the comparison. The faster lane mainly made multi-stop racing less punishing." },
      { id: "lap1", tab: "Lap-1 chaos", label: "A creative one · 62 laps",
        title: "What if the race started with a lap-1 Safety Car? Box straight away?",
        story: "<p>A start crash brings out the Safety Car for laps 1–4. A stop now is cheap (α<sub>SC</sub> = 0.43), and it gets your mandatory compound change out of the way. Should you take it?</p><p>After lap 4 the race continues with random Safety Cars from the Markov chain.</p>",
        n_laps: 62, strategies: [S([34], "H-M", null, "Planned one-stop H→M, lap 34"), S([2], "S-H", null, "Box on lap 2, then 60 laps on hards"), S([2, 36], "S-H-M", null, "Box on lap 2, again on lap 36")],
        variants: [{ label: "SC laps 1–4, then random", script: scr(62, [[1, 4, 2]], -1) }],
        verdict: (R) => "Boxing under the lap-1 Safety Car and running hards to the end costs <b>" + fx(R[0][1].mean, 1) + " s</b>. A 60-lap stint on hards wears the tyre far beyond its sweet spot. Adding a second stop to fix that still costs <b>" + fx(R[0][2].mean, 1) + " s</b>. A cheap stop is only a bargain if you needed to stop around then anyway." },
    ];
    const tabs = $("#wi-tabs"), body = $("#wi-body"); let cancels = [];
    SCN.forEach((sc, i) => { const b = el("button", { class: "tab" }, sc.tab); b.addEventListener("click", () => show(i)); tabs.appendChild(b); });
    function show(i) {
      cancels.forEach(c => c()); cancels = [];
      [...tabs.children].forEach((b, j) => b.classList.toggle("on", i === j));
      const sc = SCN[i];
      body.innerHTML = '<div class="card"><div class="wi-head"><div class="story"><span class="wi-label">' + sc.label + "</span><h3>" + sc.title + "</h3>" + sc.story +
        (sc.slider ? '<div class="controls tight"><label class="ctl">' + sc.slider.label + ' <input id="wi-sl" type="range" min="' + sc.slider.min + '" max="' + sc.slider.max + '" value="' + sc.slider.value + '"><b id="wi-sl-v">' + sc.slider.value + "</b></label></div>" : "") +
        '</div><div><div id="wi-strips"></div><div class="verdict" id="wi-verdict">Simulating…</div></div></div>' +
        '<div class="tablewrap"><table class="results" id="wi-table"></table></div>' +
        '<div class="grid2"><figure class="card" style="margin:0"><figcaption>Gap to the first plan in a typical race (no noise, median crew time) <small id="wi-gapcap"></small></figcaption><canvas id="wi-gap" data-h="250"></canvas></figure>' +
        (sc.curve ? '<figure class="card" style="margin:0"><figcaption>Pit for softs under the SC minus stay out, by SC start lap</figcaption><canvas id="wi-curve" data-h="250"></canvas></figure>' : '<figure class="card" style="margin:0"><figcaption>Expected difference vs the first plan, 95% CI</figcaption><canvas id="wi-ci" data-h="250"></canvas></figure>') + "</div></div>";
      const go = () => runScenario(sc, sc.slider ? +$("#wi-sl").value : null);
      if (sc.slider) { const g = rafThrottle(go); $("#wi-sl").addEventListener("input", (e) => { $("#wi-sl-v").textContent = e.target.value; g(); }); }
      go();
    }
    function runScenario(sc, L) {
      cancels.forEach(c => c()); cancels = [];
      const def = sc.build ? sc.build(L) : sc;
      const strategies = def.strategies, variants = def.variants;
      const pv = variants.map(v => F1.withParams(P0, Object.assign({ n_laps: sc.n_laps }, v.p || {})));
      // status strips
      $("#wi-strips").innerHTML = variants.map((v, k) => '<div class="small" style="margin:6px 0 2px">' + v.label + '</div><div class="strip-cells" id="wi-strip-' + k + '"></div>').join("") +
        '<div class="legend-inline"><span><i class="sw g"></i>Green</span><span><i class="sw v"></i>VSC</span><span><i class="sw s"></i>SC</span><span style="opacity:.6"><i class="sw g" style="opacity:.25"></i>random (Markov)</span></div>';
      variants.forEach((v, k) => stripCells($("#wi-strip-" + k), sc.n_laps, (l) => { const s = v.script ? v.script[l] : -1; return s === 1 ? "v" : s === 2 ? "s" : s === -1 ? "future" : ""; }));
      // deterministic typical race for the first variant
      const pd = Object.assign({}, pv[0], { random: false });
      const scen = F1.drawScenarios(1, pd, 1, variants[0].script ? variants[0].script.map(v => v < 0 ? 0 : v) : null);
      const races = strategies.map(s => F1.simulateOne(s, pd, scen, 0, true)), xs = races[0].laps.map(x => x.lap);
      const gaps = races.map(r => r.laps.map((x, l) => x.cum - races[0].laps[l].cum)), all = [].concat(...gaps);
      const lo = Math.min(...all) - 2, hi = Math.max(...all) + 2;
      $("#wi-gapcap").textContent = "· " + variants[0].label + (variants[0].script && variants[0].script.includes(-1) || !variants[0].script ? " (random laps shown as Green)" : "");
      plot($("#wi-gap"), { x: { min: 0.5, max: sc.n_laps + 0.5 }, y: { min: lo, max: hi }, xLabel: "lap", yLabel: "gap [s]",
        legend: strategies.map((s, j) => ({ label: "#" + (j + 1), color: SCOL[j] })),
        layers: [{ type: "rects", items: statusRects(Array.from(scen.status), lo, hi), alpha: 0.2 }, { type: "hline", y: 0, color: C.muted, dash: [2, 3] }]
          .concat(gaps.map((g, j) => ({ type: "line", x: xs, y: g, color: SCOL[j], width: 2.4 }))) });
      if (sc.curve) {
        const pts = []; for (let s = 20; s <= 54; s++) {
          const st = [F1.strategy([14], ["MEDIUM", "HARD"]), F1.strategy([14, s], ["MEDIUM", "HARD", "SOFT"])];
          const sn = F1.drawScenarios(1, pd, 1, scr(58, [[s, Math.min(s + 4, 57), 2]]));
          pts.push({ x: s, y: F1.simulateOne(st[1], pd, sn, 0) - F1.simulateOne(st[0], pd, sn, 0) });
        }
        sc._curve = pts;
        plot($("#wi-curve"), { x: { min: 20, max: 54 }, y: { includeZero: true }, xLabel: "lap the Safety Car starts", yLabel: "pit − stay out [s]",
          layers: [{ type: "rects", items: pts.filter(p => p.y < 0).map(p => ({ x0: p.x - 0.5, x1: p.x + 0.5, y0: -100, y1: 100, color: C.green })), alpha: 0.12 },
            { type: "hline", y: 0, color: C.muted, dash: [] }, { type: "line", x: pts.map(p => p.x), y: pts.map(p => p.y), color: C.s2, width: 2.4 },
            { type: "vline", x: L, color: C.accent, label: "lap " + L }] });
      }
      // Monte Carlo for every variant, streamed
      const R = variants.map(() => null), done = variants.map(() => false);
      function render() {
        let h = "<tr><th>strategy</th>" + variants.map(v => "<th>" + v.label + "</th>").join("") + "</tr>";
        strategies.forEach((s, j) => {
          h += '<tr><td><i class="sw" style="background:' + SCOL[j] + '"></i>#' + (j + 1) + " " + s.label + "</td>" + variants.map((v, k) => {
            const r = R[k]; if (!r) return "<td>…</td>";
            if (!j) return "<td>" + clock(r[0].mean) + "</td>";
            const d = r[j], hh = 1.959964 * d.sd / Math.sqrt(Math.max(d.n, 1));
            return '<td class="' + (d.mean + hh < 0 ? "good" : d.mean - hh > 0 ? "bad" : "meh") + '">' + fx(d.mean, 2) + " s <small>±" + hh.toFixed(2) + "</small></td>";
          }).join("") + "</tr>";
        });
        const n = R[0] ? R[0][0].n : 0;
        $("#wi-table").innerHTML = h + '<tr><td colspan="' + (variants.length + 1) + '" class="small" style="font-family:inherit">Row 1: expected race time. Other rows: expected difference to row 1 (green = faster, red = slower, 95% CI). ' + n.toLocaleString() + " races per column, the same scenarios for every strategy.</td></tr>";
        if (!sc.curve && R.every(Boolean)) {
          const ticks = [], items = [];
          plot($("#wi-ci"), { x: { min: 0.5, max: strategies.length - 0.5, ticks: strategies.map((_, j) => j).slice(1), fmt: (v) => "#" + (v + 1) }, y: { includeZero: true }, yLabel: "difference vs #1 [s]",
            legend: variants.map((v, k) => ({ label: v.label.length > 28 ? v.label.slice(0, 26) + "…" : v.label, color: [C.ink, C.accent, C.s3][k] })),
            layers: [{ type: "hline", y: 0, color: C.muted, dash: [] }].concat(...variants.map((v, k) => strategies.slice(1).map((s, jj) => {
              const j = jj + 1, d = R[k][j], hh = 1.959964 * d.sd / Math.sqrt(d.n), x = j + (k - (variants.length - 1) / 2) * 0.18;
              return [{ type: "errbars", x: [x], lo: [d.mean - hh], hi: [d.mean + hh], color: [C.ink, C.accent, C.s3][k], width: 2 }, { type: "points", x: [x], y: [d.mean], color: [C.ink, C.accent, C.s3][k], r: 4 }];
            }).flat())) });
        }
        if (R.every(Boolean)) $("#wi-verdict").innerHTML = sc.verdict(R, L, sc._curve || []) + (done.every(Boolean) ? "" : ' <span class="small">(refining…)</span>');
      }
      variants.forEach((v, k) => {
        cancels.push(MC.run({ p: pv[k], strategies, n: 6000, batch: 500, seed: 777 + k, script: v.script, ref: 0 }, (st) => {
          R[k] = st.diffs.map((d, j) => j ? d : st.totals[0]); done[k] = st.finished; render();
        }));
      });
    }
    show(0);
  });

  // ============================================================ VERIFY
  (function () {
    let titles = null, pending = null;
    function runAll() {
      const list = $("#vf-list"); list.innerHTML = "";
      const rows = []; let started = 0;
      function row(i, t) { const r = el("div", { class: "check" }, '<span class="badge run">…</span><div><div class="t">' + t + '</div><div class="d">running in the background…</div></div>'); list.appendChild(r); rows[i] = r; }
      MC.checks(NB, (msg) => {
        if (msg.titles) { msg.titles.forEach((t, i) => row(i, t)); return; }
        const r = rows[msg.i]; if (!r) return;
        $(".badge", r).className = "badge " + (msg.ok ? "pass" : "fail"); $(".badge", r).textContent = msg.ok ? "PASS" : "FAIL"; $(".d", r).innerHTML = msg.msg;
      });
    }
    $("#vf-run").addEventListener("click", runAll);
    const io = new IntersectionObserver((es) => { if (es.some(e => e.isIntersecting)) { io.disconnect(); runAll(); } }, { rootMargin: "200px" });
    io.observe($("#verify"));
  })();
})();
