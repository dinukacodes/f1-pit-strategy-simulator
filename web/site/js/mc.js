/*
 * mc.js — progressive Monte Carlo runner shared by the Web Worker and the
 * main-thread fallback. Scenarios are drawn once per batch and re-used for
 * every strategy (common random numbers), so paired differences are tight.
 */
(function (root) {
  "use strict";
  const F1 = root.F1;

  /**
   * job = { p, strategies:[...], n, batch, seed, script, ref, indep }
   * Calls onProgress(state) after every batch; returns a cancel function.
   * Uses `schedule` (setTimeout-like) between batches so the UI stays live.
   */
  function runMC(job, onProgress, schedule) {
    const S = job.strategies, k = S.length, ref = job.ref || 0;
    const tot = S.map(() => new F1.Welford());
    const diff = S.map(() => new F1.Welford());
    const indep = job.indep ? S.map(() => new F1.Welford()) : null;
    const pitUnderNeutral = S.map(() => 0);
    let done = 0, cancelled = false, b = 0;
    const batch = job.batch || 250;
    function step() {
      if (cancelled) return;
      const m = Math.min(batch, job.n - done);
      const seed = (job.seed + 7919 * b) >>> 0; b++;
      const scen = F1.drawScenarios(m, job.p, seed, job.script || null);
      const X = S.map(s => F1.simulateAll(s, job.p, scen));
      const newDiffs = S.map(() => new Float64Array(m));
      for (let j = 0; j < k; j++) {
        for (let i = 0; i < m; i++) {
          tot[j].push(X[j][i]);
          if (j !== ref) { const d = X[j][i] - X[ref][i]; diff[j].push(d); newDiffs[j][i] = d; }
        }
        // how often did this strategy's first stop happen under VSC/SC?
        for (let i = 0; i < m; i++) {
          const L = F1.firstStopLap(S[j], scen, i);
          if (scen.status[i * scen.N + L - 1] !== F1.GREEN) pitUnderNeutral[j]++;
        }
      }
      if (indep) {                      // same strategies, but each on its own independent scenarios
        const scenB = F1.drawScenarios(m, job.p, (seed ^ 0x5bd1e995) >>> 0, job.script || null);
        for (let j = 0; j < k; j++) {
          if (j === ref) continue;
          const Y = F1.simulateAll(S[j], job.p, scenB);
          for (let i = 0; i < m; i++) indep[j].push(Y[i] - X[ref][i]);
        }
      }
      done += m;
      onProgress({
        done, n: job.n, finished: done >= job.n,
        totals: tot.map(w => ({ n: w.n, mean: w.mean, sd: w.sd() })),
        diffs: diff.map(w => ({ n: w.n, mean: w.mean, sd: w.sd() })),
        indep: indep ? indep.map(w => ({ n: w.n, mean: w.mean, sd: w.sd() })) : null,
        pitNeutral: pitUnderNeutral.map(c => c / done),
        newDiffs, sampleTotals: X.map(x => Array.from(x.slice(0, Math.min(60, m)))),
      });
      if (done < job.n) schedule(step);
    }
    schedule(step);
    return function cancel() { cancelled = true; };
  }
  root.runMC = runMC;
})(typeof self !== "undefined" ? self : this);
