/*
 * model.js — JavaScript port of the single-car pit-stop strategy simulator.
 *
 * It mirrors src/f1sim.py line for line (see simulate_race_loop there):
 *   tyre wear ODE solved with one RK4 step per lap, fuel-corrected lap times,
 *   a phase-type Markov chain for track status, a geometry-based pit-loss
 *   model, shifted-lognormal crew times and common random numbers.
 * Only the random number generator differs (xoshiro128** instead of NumPy's
 * PCG64), so Monte Carlo estimates agree statistically, while the same
 * scenario fed to both implementations gives identical race times.
 *
 * Works in the browser (window.F1), in a Web Worker (self.F1) and in Node.
 */
(function (root) {
  "use strict";

  const GREEN = 0, VSC = 1, SC = 2;
  const COMPOUNDS = ["SOFT", "MEDIUM", "HARD"];
  const MAX_STOPS = 3;

  // ------------------------------------------------------------------ params
  function defaultParams() {
    return deriveAlphas({
      n_laps: 62, t0_s: 96.0,
      offset_s: { SOFT: 0.0, MEDIUM: 0.35, HARD: 0.70 },
      k_s_per_lap: { SOFT: 0.100, MEDIUM: 0.060, HARD: 0.035 },
      eta_per_s: 0.02, beta_per_kg: 0.004, m0_kg: 100.0, burn_kg_per_lap: 1.6,
      gamma_s_per_kg: 0.03, sigma_s: 0.35,
      k_vsc: 1.40, k_sc: 1.60, phi_vsc: 0.50, phi_sc: 0.25,
      p_gv: 0.012, p_gs: 0.020, p_lap1_sc: 0.15, p_vv: 0.60, sc_min_laps: 3, p_ss: 0.50,
      t_pit_s: 36.0, t_bypass_s: 15.0,
      crew_shift_s: 2.0, crew_mu: -0.51, crew_sigma: 0.50,
      random: true,
    });
  }

  function deriveAlphas(p) {
    const d = p.t_pit_s - p.t_bypass_s;
    if (!(d > 0)) throw new Error("pit lane must be slower than the track");
    p.dT_green_s = d;
    p.alpha_vsc = (p.k_vsc - 1) * p.t_bypass_s / d;
    p.alpha_sc = (p.k_sc - 1) * p.t_bypass_s / d;
    return p;
  }

  function withParams(p, changes) {
    const q = JSON.parse(JSON.stringify(p));
    Object.assign(q, changes || {});
    if (!changes || (!("alpha_sc" in changes) && !("alpha_vsc" in changes))) deriveAlphas(q);
    return q;
  }

  // ------------------------------------------------------------- ODE solvers
  function wearRhs(p, compound, raceLap0, phi) {
    const k = p.k_s_per_lap[compound], beta = p.beta_per_kg, eta = p.eta_per_s;
    const m0 = p.m0_kg, b = p.burn_kg_per_lap;
    return function (a, w) {
      const fuel = m0 - b * (raceLap0 - 1 + a);
      return k * (1 + beta * fuel) * (1 + eta * w) * phi;
    };
  }
  function rk4Step(f, t, y, h) {
    const k1 = f(t, y), k2 = f(t + h / 2, y + h / 2 * k1);
    const k3 = f(t + h / 2, y + h / 2 * k2), k4 = f(t + h, y + h * k3);
    return y + h / 6 * (k1 + 2 * k2 + 2 * k3 + k4);
  }
  function solve(method, f, y0, t0, t1, n) {
    const h = (t1 - t0) / n; let y = y0, t = t0;
    for (let i = 0; i < n; i++) {
      if (method === "euler") y = y + h * f(t, y);
      else if (method === "rk2") y = y + h * f(t + h / 2, y + h / 2 * f(t, y));
      else y = rk4Step(f, t, y, h);
      t += h;
    }
    return y;
  }
  function wearClosedForm(p, compound, stintStartLap, age, phi) {
    phi = phi == null ? 1 : phi;
    const k = p.k_s_per_lap[compound], beta = p.beta_per_kg, eta = p.eta_per_s;
    const A = (1 + beta * (p.m0_kg - p.burn_kg_per_lap * (stintStartLap - 1))) * age - beta * p.burn_kg_per_lap * age * age / 2;
    if (eta === 0) return k * phi * A;
    return (Math.exp(eta * k * phi * A) - 1) / eta;
  }

  // -------------------------------------------------------------- random numbers
  // splitmix32 seeds xoshiro128**; each (seed, stream) pair is an independent stream.
  function splitmix32(a) {
    return function () {
      a |= 0; a = (a + 0x9e3779b9) | 0;
      let t = a ^ (a >>> 16); t = Math.imul(t, 0x21f0aaad);
      t = t ^ (t >>> 15); t = Math.imul(t, 0x735a2d97);
      return (t ^ (t >>> 15)) >>> 0;
    };
  }
  function makeRng(seed, stream) {
    const sm = splitmix32((seed >>> 0) ^ Math.imul((stream | 0) + 1, 0x85ebca6b));
    let s0 = sm(), s1 = sm(), s2 = sm(), s3 = sm();
    function next() {
      const r = Math.imul(rotl(Math.imul(s1, 5), 7), 9) >>> 0;
      const t = s1 << 9;
      s2 ^= s0; s3 ^= s1; s1 ^= s2; s0 ^= s3; s2 ^= t; s3 = rotl(s3, 11);
      return r;
    }
    function rotl(x, k) { return (x << k) | (x >>> (32 - k)); }
    // 53-bit uniform in [0, 1)
    function random() { return ((next() >>> 5) * 67108864 + (next() >>> 6)) / 9007199254740992; }
    let spare = null;
    function normal() {               // Box-Muller, both outputs used
      if (spare !== null) { const z = spare; spare = null; return z; }
      const u1 = 1 - random(), u2 = random();
      const r = Math.sqrt(-2 * Math.log(u1));
      spare = r * Math.sin(2 * Math.PI * u2);
      return r * Math.cos(2 * Math.PI * u2);
    }
    return { random, normal };
  }

  function crewTimeFromNormal(z, p) { return p.crew_shift_s + Math.exp(p.crew_mu + p.crew_sigma * z); }
  function meanCrew(p) { return p.crew_shift_s + Math.exp(p.crew_mu + p.crew_sigma * p.crew_sigma / 2); }

  // ------------------------------------------------------------ Markov chain
  function expandedMatrix(p) {
    const m = p.sc_min_laps | 0, n = 2 + m + 1;
    const P = []; for (let i = 0; i < n; i++) P.push(new Array(n).fill(0));
    const a = p.p_gv, c = p.p_gs;
    P[0][0] = 1 - a - c; P[0][1] = a; P[0][2] = c;
    P[1][0] = 1 - p.p_vv; P[1][1] = p.p_vv;
    for (let i = 0; i < m - 1; i++) P[2 + i][3 + i] = 1;
    const last = 2 + m - 1;
    for (const s of [last, n - 1]) { P[s][n - 1] = p.p_ss; P[s][0] = 1 - p.p_ss; }
    const collapse = [0, 1]; for (let i = 0; i <= m; i++) collapse.push(2);
    return { P, collapse };
  }
  function lap1Row(p) {
    const { P } = expandedMatrix(p); const row = new Array(P.length).fill(0);
    row[0] = 1 - p.p_lap1_sc - p.p_gv; row[1] = p.p_gv; row[2] = p.p_lap1_sc; return row;
  }
  function scMeanDuration(p) { return p.sc_min_laps + p.p_ss / (1 - p.p_ss); }
  function renewalFractions(p) {
    const ev = 1 / (1 - p.p_vv), es = scMeanDuration(p);
    const g = 1 / (1 + p.p_gv * ev + p.p_gs * es);
    return [g, p.p_gv * ev * g, p.p_gs * es * g];
  }
  /** Exact P(status on lap l), l = 1..N, from powers of the expanded chain. */
  function statusProbabilities(p) {
    const { P, collapse } = expandedMatrix(p); let row = lap1Row(p); const out = [];
    for (let l = 0; l < p.n_laps; l++) {
      const s = [0, 0, 0]; row.forEach((v, i) => { s[collapse[i]] += v; }); out.push(s);
      const nxt = new Array(row.length).fill(0);
      for (let i = 0; i < row.length; i++) for (let j = 0; j < row.length; j++) nxt[j] += row[i] * P[i][j];
      row = nxt;
    }
    return out;
  }
  function cumRows(P) { return P.map(r => { let c = 0; return r.map(v => (c += v)); }); }
  function invCdf(cum, u) { let k = 0; while (k < cum.length - 1 && u > cum[k]) k++; return k; }

  // --------------------------------------------------------------- pit loss
  function pitLoss(state, crew, p) {
    const alpha = state === GREEN ? 0 : state === VSC ? p.alpha_vsc : p.alpha_sc;
    return (1 - alpha) * p.dT_green_s + crew;
  }

  // -------------------------------------------------------------- strategies
  function strategy(pitLaps, compounds, reactiveWindow, name) {
    const s = { pit_laps: pitLaps.slice(), compounds: compounds.slice(), reactive_window: reactiveWindow || null };
    s.name = name || (pitLaps.length + "-stop " + compounds.map(c => c[0]).join("-") + " @" + pitLaps.join(",") +
      (reactiveWindow ? " react[" + reactiveWindow[0] + "-" + reactiveWindow[1] + "]" : ""));
    return s;
  }
  function validateStrategy(s, p) {
    const laps = s.pit_laps, comps = s.compounds, n = p.n_laps;
    if (comps.length !== laps.length + 1 || laps.length === 0 || laps.length > MAX_STOPS) return "need one compound per stint";
    if (comps.some(c => COMPOUNDS.indexOf(c) < 0) || new Set(comps).size < 2) return "use at least two different dry compounds";
    if (laps.some(l => !(l >= 1 && l <= n - 1))) return "pit laps must be inside the race";
    for (let i = 1; i < laps.length; i++) if (laps[i] <= laps[i - 1]) return "pit laps must increase";
    const w = s.reactive_window;
    if (w && !(1 <= w[0] && w[0] <= w[1] && w[1] <= laps[0])) return "reactive window must end at or before the first planned stop";
    return null;
  }

  // ------------------------------------------------- scenarios (common random numbers)
  /**
   * n race scenarios from three independent streams (status, lap noise, crew time).
   * script (optional, length N): -1 = Markov chain decides, 0/1/2 = force Green/VSC/SC on that lap.
   */
  function drawScenarios(n, p, seed, script) {
    const N = p.n_laps, rand = p.random !== false;
    const { P, collapse } = expandedMatrix(p); const cum = cumRows(P);
    const c1 = cumRows([lap1Row(p)])[0]; const last = P.length - 1;
    const status = new Int8Array(n * N), zLap = new Float64Array(n * N), zCrew = new Float64Array(n * MAX_STOPS);
    const gS = makeRng(seed, 1), gN = makeRng(seed, 2), gC = makeRng(seed, 3);
    for (let i = 0; i < n; i++) {
      let state = 0;
      for (let l = 0; l < N; l++) {
        const u = gS.random(), forced = script ? script[l] : -1;
        if (forced === GREEN) state = 0;
        else if (forced === VSC) state = 1;
        else if (forced === SC) state = (state >= 2) ? Math.min(state + 1, last) : 2;
        else if (!rand) state = 0;
        else state = l === 0 ? invCdf(c1, u) : invCdf(cum[state], u);
        status[i * N + l] = collapse[state];
      }
      if (rand) {
        for (let l = 0; l < N; l++) zLap[i * N + l] = gN.normal();
        for (let k = 0; k < MAX_STOPS; k++) zCrew[i * MAX_STOPS + k] = gC.normal();
      }
    }
    return { n, N, status, zLap, zCrew };
  }

  /** Wrap externally supplied scenarios (e.g. exported from the Python code). */
  function scenariosFromArrays(status2d, zLap2d, zCrew2d) {
    const n = status2d.length, N = status2d[0].length;
    const status = new Int8Array(n * N), zLap = new Float64Array(n * N), zCrew = new Float64Array(n * MAX_STOPS);
    for (let i = 0; i < n; i++) {
      for (let l = 0; l < N; l++) { status[i * N + l] = status2d[i][l]; zLap[i * N + l] = zLap2d[i][l]; }
      for (let k = 0; k < MAX_STOPS; k++) zCrew[i * MAX_STOPS + k] = zCrew2d[i][k];
    }
    return { n, N, status, zLap, zCrew };
  }

  function firstStopLap(s, scen, i) {
    let first = s.pit_laps[0]; const w = s.reactive_window;
    if (w) for (let l = w[0]; l <= w[1]; l++) if (scen.status[i * scen.N + l - 1] !== GREEN) { first = l; break; }
    return first;
  }

  /**
   * One race (scenario row i) for strategy s. Mirrors simulate_race_loop in f1sim.py.
   * With detail=true returns per-lap components so the page can show where every second comes from.
   */
  function simulateOne(s, p, scen, i, detail) {
    const N = p.n_laps, base = i * N, rand = p.random !== false;
    const stops = [firstStopLap(s, scen, i)].concat(s.pit_laps.slice(1));
    const phiOf = [1, p.phi_vsc, p.phi_sc], kOf = [1, p.k_vsc, p.k_sc];
    let stint = 0, w = 0, age = 0, total = 0;
    const laps = detail ? [] : null;
    for (let l = 1; l <= N; l++) {
      const st = scen.status[base + l - 1], c = s.compounds[stint];
      const fuel = p.m0_kg - p.burn_kg_per_lap * (l - 1);
      let t, noise = 0;
      if (st === GREEN) {
        noise = rand ? p.sigma_s * scen.zLap[base + l - 1] : 0;
        t = p.t0_s + p.offset_s[c] + w + p.gamma_s_per_kg * fuel + noise;
      } else t = kOf[st] * p.t0_s;
      const wBefore = w, ageBefore = age;
      // one RK4 step of the wear ODE over this lap, inlined (no closures) for speed:
      // f(a, w) = g(a) (1 + eta w),  g(a) = k phi (1 + beta (m0 - b (l - 1 + a)))
      const kp = p.k_s_per_lap[c] * phiOf[st], beta = p.beta_per_kg, eta = p.eta_per_s;
      const g0 = kp * (1 + beta * fuel), gh = kp * (1 + beta * (fuel - p.burn_kg_per_lap * 0.5)), g1 = kp * (1 + beta * (fuel - p.burn_kg_per_lap));
      const k1 = g0 * (1 + eta * w), k2 = gh * (1 + eta * (w + 0.5 * k1)), k3 = gh * (1 + eta * (w + 0.5 * k2)), k4 = g1 * (1 + eta * (w + k3));
      w = w + (k1 + 2 * k2 + 2 * k3 + k4) / 6; age += 1;
      let pit = 0, crew = 0;
      if (stint < stops.length && l === stops[stint]) {
        crew = rand ? crewTimeFromNormal(scen.zCrew[i * MAX_STOPS + stint], p) : p.crew_shift_s + Math.exp(p.crew_mu);
        pit = pitLoss(st, crew, p); t += pit; stint += 1; w = 0; age = 0;
      }
      total += t;
      if (detail) laps.push({ lap: l, status: st, compound: c, fuel, age: ageBefore, wear: wBefore,
        base: st === GREEN ? p.t0_s : kOf[st] * p.t0_s,
        offset: st === GREEN ? p.offset_s[c] : 0, fuelTime: st === GREEN ? p.gamma_s_per_kg * fuel : 0,
        wearTime: st === GREEN ? wBefore : 0, noise, pit, crew, time: t, cum: total });
    }
    return detail ? { total, laps, stops: laps.filter(x => x.pit > 0).map(x => x.lap) } : total;
  }

  function simulateAll(s, p, scen) {
    const out = new Float64Array(scen.n);
    for (let i = 0; i < scen.n; i++) out[i] = simulateOne(s, p, scen, i, false);
    return out;
  }

  // ------------------------------------------------------- analytic references
  function linearParams(p) { return withParams(p, { eta_per_s: 0, beta_per_kg: 0, phi_vsc: 1, phi_sc: 1 }); }
  function optimalOneStopLap(c1, c2, p) {
    const k1 = p.k_s_per_lap[c1], k2 = p.k_s_per_lap[c2], d1 = p.offset_s[c1], d2 = p.offset_s[c2];
    return (k2 * p.n_laps + (d2 - d1) + (k1 - k2) / 2) / (k1 + k2);
  }
  function greenTotalLinear(s, p) {
    const N = p.n_laps, edges = [0].concat(s.pit_laps, [N]);
    let tot = N * p.t0_s;
    for (let l = 1; l <= N; l++) tot += p.gamma_s_per_kg * (p.m0_kg - p.burn_kg_per_lap * (l - 1));
    s.compounds.forEach((c, j) => { const S = edges[j + 1] - edges[j]; tot += S * p.offset_s[c] + p.k_s_per_lap[c] * S * (S - 1) / 2; });
    return tot;
  }
  function exactExpectedTotal(s, p) {
    const N = p.n_laps, probs = statusProbabilities(p), mc = meanCrew(p), edges = [0].concat(s.pit_laps, [N]);
    let total = 0;
    s.compounds.forEach((c, j) => {
      for (let l = edges[j] + 1; l <= edges[j + 1]; l++) {
        const age = l - edges[j] - 1;
        const green = p.t0_s + p.offset_s[c] + p.k_s_per_lap[c] * age + p.gamma_s_per_kg * (p.m0_kg - p.burn_kg_per_lap * (l - 1));
        const pr = probs[l - 1];
        total += pr[0] * green + pr[1] * p.k_vsc * p.t0_s + pr[2] * p.k_sc * p.t0_s;
      }
    });
    for (const L of s.pit_laps) {
      const pr = probs[L - 1];
      total += mc + p.dT_green_s * (pr[0] + pr[1] * (1 - p.alpha_vsc) + pr[2] * (1 - p.alpha_sc));
    }
    return total;
  }

  // ------------------------------------------------------------------ statistics
  function Welford() { this.n = 0; this.mean = 0; this.m2 = 0; }
  Welford.prototype.push = function (x) { this.n++; const d = x - this.mean; this.mean += d / this.n; this.m2 += d * (x - this.mean); };
  Welford.prototype.sd = function () { return this.n > 1 ? Math.sqrt(this.m2 / (this.n - 1)) : 0; };
  Welford.prototype.ci = function (z) { z = z || 1.959964; const h = this.n > 1 ? z * this.sd() / Math.sqrt(this.n) : Infinity; return [this.mean - h, this.mean + h]; };

  function normInv(q) {               // Acklam's rational approximation (|error| < 1.2e-9)
    const a = [-39.69683028665376, 220.9460984245205, -275.9285104469687, 138.357751867269, -30.66479806614716, 2.506628277459239];
    const b = [-54.47609879822406, 161.5858368580409, -155.6989798598866, 66.80131188771972, -13.28068155288572];
    const c = [-0.007784894002430293, -0.3223964580411365, -2.400758277161838, -2.549732539343734, 4.374664141464968, 2.938163982698783];
    const d = [0.007784695709041462, 0.3224671290700398, 2.445134137142996, 3.754408661907416];
    const pl = 0.02425;
    if (q < pl) { const r = Math.sqrt(-2 * Math.log(q)); return (((((c[0] * r + c[1]) * r + c[2]) * r + c[3]) * r + c[4]) * r + c[5]) / ((((d[0] * r + d[1]) * r + d[2]) * r + d[3]) * r + 1); }
    if (q > 1 - pl) return -normInv(1 - q);
    const r = q - 0.5, t = r * r;
    return (((((a[0] * t + a[1]) * t + a[2]) * t + a[3]) * t + a[4]) * t + a[5]) * r / (((((b[0] * t + b[1]) * t + b[2]) * t + b[3]) * t + b[4]) * t + 1);
  }
  function bonferroniZ(k, level) { level = level || 0.95; return normInv(1 - (1 - level) / (2 * k)); }

  const F1 = {
    GREEN, VSC, SC, COMPOUNDS, MAX_STOPS,
    defaultParams, deriveAlphas, withParams,
    wearRhs, rk4Step, solve, wearClosedForm,
    makeRng, crewTimeFromNormal, meanCrew,
    expandedMatrix, lap1Row, scMeanDuration, renewalFractions, statusProbabilities,
    pitLoss, strategy, validateStrategy,
    drawScenarios, scenariosFromArrays, firstStopLap, simulateOne, simulateAll,
    linearParams, optimalOneStopLap, greenTotalLinear, exactExpectedTotal,
    Welford, normInv, bonferroniZ,
  };
  if (typeof module !== "undefined" && module.exports) module.exports = F1;
  root.F1 = F1;
})(typeof self !== "undefined" ? self : this);
