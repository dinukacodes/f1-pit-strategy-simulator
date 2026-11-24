/* checks.js — the notebook's verification checks, re-run against the JavaScript port (in the Web Worker). */
(function (root) {
  "use strict";
  function erf(x) { const t = 1 / (1 + 0.3275911 * Math.abs(x)); const y = 1 - (((((1.061405429 * t - 1.453152027) * t) + 1.421413741) * t - 0.284496736) * t + 0.254829592) * t * Math.exp(-x * x); return x >= 0 ? y : -y; }
  function makeChecks(F1, NB) {
    const P0 = F1.defaultParams();
    const checks = [
      ["RK4 matches the exact tyre-wear solution", () => { const p = F1.withParams(P0, { eta_per_s: 0.08 }); const ex = F1.wearClosedForm(p, "SOFT", 1, 30), w = F1.solve("rk4", F1.wearRhs(p, "SOFT", 1, 1), 0, 0, 30, 30); return [Math.abs(w - ex) < 1e-8, "w(30) exact " + ex.toFixed(10) + " s, RK4 " + w.toFixed(10) + " s, error " + Math.abs(w - ex).toExponential(2) + " s (tolerance 1e-8)"]; }],
      ["Deterministic benchmark finds the derived optimal pit lap", () => {
        const pd = F1.linearParams(P0); Object.assign(pd, { random: false, p_gv: 0, p_gs: 0, p_lap1_sc: 0 }); let worst = 0, best = 0, bt = Infinity;
        const crew = pd.crew_shift_s + Math.exp(pd.crew_mu);
        for (let L = 8; L < 55; L++) { const s = F1.strategy([L], ["MEDIUM", "HARD"]); const t = F1.simulateOne(s, pd, F1.drawScenarios(1, pd, 0), 0); worst = Math.max(worst, Math.abs(t - (F1.greenTotalLinear(s, pd) + pd.dT_green_s + crew))); if (t < bt) { bt = t; best = L; } }
        const Ls = F1.optimalOneStopLap("MEDIUM", "HARD", pd);
        return [worst < 1e-6 && (best === Math.floor(Ls) || best === Math.ceil(Ls)), "max |sim − closed form| = " + worst.toExponential(2) + " s; L* = " + Ls.toFixed(2) + ", simulated best lap " + best + " (notebook: L* = " + NB.L_star.toFixed(2) + ", best 27)"]; }],
      ["Markov chain: stationary law, SC length law", () => {
        const p = P0, sc = F1.drawScenarios(1, F1.withParams(p, { n_laps: 100000 }), 11); const cnt = [0, 0, 0], runs = []; let r = 0;
        for (let l = 0; l < 100000; l++) { const s = sc.status[l]; cnt[s]++; if (s === 2) r++; else if (r) { runs.push(r); r = 0; } }
        const emp = cnt.map(c => c / 100000), rf = F1.renewalFractions(p), dmax = Math.max(...emp.map((v, i) => Math.abs(v - rf[i])));
        const mean = runs.reduce((a, b) => a + b) / runs.length, sd = Math.sqrt(runs.reduce((a, b) => a + (b - mean) ** 2, 0) / (runs.length - 1)), se = sd / Math.sqrt(runs.length);
        return [dmax < 0.01 && Math.min(...runs) >= p.sc_min_laps && Math.abs(mean - F1.scMeanDuration(p)) < 3 * se,
          "empirical [" + emp.map(v => v.toFixed(4)).join(", ") + "] vs renewal [" + rf.map(v => v.toFixed(4)).join(", ") + "]; " + runs.length + " SC periods, shortest " + Math.min(...runs) + " laps, mean " + mean.toFixed(3) + " vs E[D] = " + F1.scMeanDuration(p).toFixed(3)]; }],
      ["Exact expected race time = Monte Carlo mean (40,000 races)", () => {
        const out = []; let ok = true;
        for (const e of NB.exact) {
          const q = F1.linearParams(F1.withParams(P0, { p_gs: e.p_gs }));
          const s = e.name.indexOf("1-stop") === 0 ? F1.strategy([26], ["MEDIUM", "HARD"]) : F1.strategy([18, 40], ["SOFT", "MEDIUM", "HARD"]);
          const ex = F1.exactExpectedTotal(s, q), w = new F1.Welford(); F1.simulateAll(s, q, F1.drawScenarios(40000, q, 4242)).forEach(v => w.push(v));
          const z = (w.mean - ex) / (w.sd() / Math.sqrt(w.n)); ok = ok && Math.abs(z) < 3 && Math.abs(ex - e.exact) < 1e-6;
          out.push("P_GS " + e.p_gs + " " + e.name + ": exact " + ex.toFixed(3) + " (notebook " + e.exact.toFixed(3) + "), MC " + w.mean.toFixed(3) + ", z " + z.toFixed(2));
        }
        return [ok, out.join("<br>")]; }],
      ["Conservation and model rules", () => {
        const s1 = F1.strategy([26], ["MEDIUM", "HARD"]), sc = F1.drawScenarios(1, P0, 3), r = F1.simulateOne(s1, P0, sc, 0, true);
        const sum = r.laps.reduce((a, x) => a + x.time, 0), fuelOk = r.laps.every(x => x.fuel >= 0);
        const resets = r.laps[r.stops[0]].age === 0, same = F1.simulateAll(s1, P0, F1.drawScenarios(500, P0, 9)), same2 = F1.simulateAll(s1, P0, F1.drawScenarios(500, P0, 9));
        const crn0 = same.every((v, i) => v === same2[i]);
        const invalid = F1.validateStrategy(F1.strategy([26], ["HARD", "HARD"]), P0) && F1.validateStrategy(F1.strategy([70], ["SOFT", "HARD"]), P0);
        const ok = r.laps.length === 62 && Math.abs(sum - r.total) < 1e-9 && fuelOk && resets && crn0 && !!invalid;
        return [ok, "62 laps, total = sum of laps (" + Math.abs(sum - r.total).toExponential(1) + " s), fuel ≥ 0, tyre age resets after a stop, identical strategies differ by exactly 0 under CRN, single-compound and out-of-range plans rejected"]; }],
      ["Box–Muller crew times pass a Kolmogorov–Smirnov test", () => {
        const rng = F1.makeRng(99, 0), n = 5000, z = [], c = []; for (let i = 0; i < n; i++) z.push(rng.normal()); for (let i = 0; i < n; i++) c.push(F1.crewTimeFromNormal(rng.normal(), P0));
        const ncdf = (x) => 0.5 * (1 + erf(x / Math.SQRT2));
        const ks = (xs, F) => { const s = xs.slice().sort((a, b) => a - b); let D = 0; s.forEach((v, i) => { const f = F(v); D = Math.max(D, (i + 1) / n - f, f - i / n); }); return D; };
        const Dz = ks(z, ncdf), Dc = ks(c, (v) => ncdf((Math.log(v - P0.crew_shift_s) - P0.crew_mu) / P0.crew_sigma)), crit = 1.36 / Math.sqrt(n);
        return [Dz < crit && Dc < crit && Math.min(...c) > P0.crew_shift_s, "normal D = " + Dz.toFixed(4) + ", crew D = " + Dc.toFixed(4) + ", critical " + crit.toFixed(4)]; }],
      ["Monte Carlo error falls like 1/√N", () => {
        const s1 = F1.strategy([26], ["MEDIUM", "HARD"]), Ns = [100, 400, 1600], sds = Ns.map(n => { const m = []; for (let j = 0; j < 30; j++) { const a = F1.simulateAll(s1, P0, F1.drawScenarios(n, P0, 1000 * j + n)); m.push(a.reduce((x, y) => x + y) / n); } const mu = m.reduce((x, y) => x + y) / 30; return Math.sqrt(m.reduce((x, y) => x + (y - mu) ** 2, 0) / 29); });
        const lx = Ns.map(Math.log), ly = sds.map(Math.log), mx = lx.reduce((a, b) => a + b) / 3, my = ly.reduce((a, b) => a + b) / 3;
        let sxy = 0, sxx = 0; lx.forEach((x, i) => { sxy += (x - mx) * (ly[i] - my); sxx += (x - mx) ** 2; }); const slope = sxy / sxx;
        return [Math.abs(slope + 0.5) < 0.15, "log–log slope " + slope.toFixed(3) + " (expected −0.5 ± 0.15)"]; }],
    ];
    return checks;
  }
  root.makeChecks = makeChecks;
})(typeof self !== "undefined" ? self : this);
