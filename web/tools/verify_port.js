// Checks the JavaScript port against the Python model and the notebook's saved results.
// Run: node tools/verify_port.js [path/to/fixture.json]
const F1 = require("../site/js/model.js");
const R = require("../site/data/notebook_results.json");
const fs = require("fs");
let fails = 0;
function check(name, ok, msg) { console.log((ok ? "PASS " : "FAIL ") + name + "  " + msg); if (!ok) fails++; }
const p = F1.defaultParams();
check("alphas", Math.abs(p.alpha_vsc - R.alphas[0]) < 1e-12 && Math.abs(p.alpha_sc - R.alphas[1]) < 1e-12, p.alpha_vsc.toFixed(4) + " " + p.alpha_sc.toFixed(4));

const fx = process.argv[2] && fs.existsSync(process.argv[2]) ? JSON.parse(fs.readFileSync(process.argv[2])) : null;
if (fx) {
  const scen = F1.scenariosFromArrays(fx.status, fx.z_lap, fx.z_crew);
  fx.strategies.forEach((s0, j) => {
    const s = F1.strategy(s0.pit_laps, s0.compounds, s0.reactive_window);
    const t = F1.simulateAll(s, p, scen); let worst = 0;
    t.forEach((v, i) => { worst = Math.max(worst, Math.abs(v - fx.totals[j][i])); });
    check("same scenarios as Python: " + s.name, worst < 1e-8, "max |JS - Python| = " + worst.toExponential(2) + " s over " + t.length + " races");
  });
}
// deterministic benchmark (notebook 5.2)
const pd = F1.linearParams(p); Object.assign(pd, { random: false, p_gv: 0, p_gs: 0, p_lap1_sc: 0 });
let worst = 0, best = null, bestT = Infinity;
for (let L = 8; L < 55; L++) {
  const r = F1.simulateOne(F1.strategy([L], ["MEDIUM", "HARD"]), pd, F1.drawScenarios(1, pd, 0), 0, false);
  worst = Math.max(worst, Math.abs(r - R.det_bench[L])); if (r < bestT) { bestT = r; best = L; }
}
check("deterministic benchmark", worst < 1e-9 && best === 27, "max diff vs Python " + worst.toExponential(2) + " s, best lap " + best + ", L* = " + F1.optimalOneStopLap("MEDIUM", "HARD", pd).toFixed(2));
// exact expected totals (5.4)
for (const e of R.exact) {
  const q = F1.linearParams(F1.withParams(p, { p_gs: e.p_gs }));
  const s = e.name.startsWith("1") ? F1.strategy([26], ["MEDIUM", "HARD"]) : F1.strategy([18, 40], ["SOFT", "MEDIUM", "HARD"]);
  const ex = F1.exactExpectedTotal(s, q);
  const sc = F1.drawScenarios(40000, q, 777), w = new F1.Welford(); F1.simulateAll(s, q, sc).forEach(v => w.push(v));
  const z = (w.mean - ex) / (w.sd() / Math.sqrt(w.n));
  check("exact E[T] P_GS=" + e.p_gs + " " + e.name, Math.abs(ex - e.exact) < 1e-9 && Math.abs(z) < 3, "exact " + ex.toFixed(3) + " (python " + e.exact.toFixed(3) + "), MC " + w.mean.toFixed(3) + ", z=" + z.toFixed(2));
}
// stage 2 (independent RNG; must agree within the combined CI)
const SL = R.shortlist.map(s => F1.strategy(s.pit_laps, s.compounds, s.reactive_window));
const sc = F1.drawScenarios(10000, p, 20251027);
const X = SL.map(s => F1.simulateAll(s, p, sc));
for (let j = 1; j < 3; j++) {
  const w = new F1.Welford(); for (let i = 0; i < sc.n; i++) w.push(X[j][i] - X[0][i]);
  const nb = R.stage2[j]; const seJ = w.sd() / Math.sqrt(w.n), seN = (nb.diff_high_s - nb.diff_low_s) / 2 / R.bonferroni_z;
  const z = (w.mean - nb.diff_s) / Math.hypot(seJ, seN);
  check("stage-2 paired diff " + nb.name, Math.abs(z) < 3, "browser " + w.mean.toFixed(2) + " s vs notebook " + nb.diff_s.toFixed(2) + " s (z=" + z.toFixed(2) + ")");
}
const w0 = new F1.Welford(); X[0].forEach(v => w0.push(v));
const zm = (w0.mean - R.stage2[0].mean_s) / Math.hypot(w0.sd() / 100, (R.stage2[0].ci_high_s - R.stage2[0].mean_s) / R.bonferroni_z);
check("stage-2 mean 1-stop", Math.abs(zm) < 3, w0.mean.toFixed(2) + " vs " + R.stage2[0].mean_s.toFixed(2) + " (z=" + zm.toFixed(2) + ")");
// sweep
for (const r of R.sweep) {
  const q = F1.withParams(p, { p_gs: r.p_gs }); const s2 = F1.drawScenarios(10000, q, 99 + r.p_gs * 1e4);
  const Y = SL.map(s => F1.simulateAll(s, q, s2));
  [["two", 1], ["react", 2]].forEach(([k, j]) => {
    const w = new F1.Welford(); for (let i = 0; i < s2.n; i++) w.push(Y[j][i] - Y[0][i]);
    const z = (w.mean - r[k][0]) / Math.hypot(w.sd() / 100, (r[k][2] - r[k][0]) / 1.959964);
    check("sweep P_GS=" + r.p_gs + " " + k, Math.abs(z) < 3.5, w.mean.toFixed(2) + " vs " + r[k][0].toFixed(2) + " (z=" + z.toFixed(2) + ")");
  });
}
// Markov marginals
const sp = F1.statusProbabilities(p); let wm = 0;
sp.forEach((r, l) => r.forEach((v, k) => { wm = Math.max(wm, Math.abs(v - R.status_probs[l][k])); }));
check("status marginals", wm < 1e-12, "max diff " + wm.toExponential(2));
console.log(fails ? fails + " FAILED" : "ALL PASS"); process.exit(fails ? 1 : 0);
