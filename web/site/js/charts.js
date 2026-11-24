/*
 * charts.js — a small canvas plotting helper (no dependencies).
 * plot(canvas, spec) draws axes, grid and layers; it re-draws on resize.
 */
(function (root) {
  "use strict";
  const css = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  // colours may be CSS custom-property tokens like "--ink" so charts follow the light/dark theme
  const rc = (c) => (typeof c === "string" && c.slice(0, 2) === "--") ? css(c) : c;

  function niceTicks(lo, hi, count) {
    if (!(hi > lo)) { hi = lo + 1; }
    const span = hi - lo, step0 = span / Math.max(1, count);
    const mag = Math.pow(10, Math.floor(Math.log10(step0)));
    const norm = step0 / mag;
    const step = (norm < 1.5 ? 1 : norm < 3 ? 2 : norm < 7 ? 5 : 10) * mag;
    const out = [];
    for (let v = Math.ceil(lo / step - 1e-9) * step; v <= hi + step * 1e-9; v += step) out.push(+v.toFixed(12));
    return out;
  }
  function logTicks(lo, hi) {
    const out = [];
    for (let e = Math.floor(Math.log10(lo)); e <= Math.ceil(Math.log10(hi)); e++) {
      const v = Math.pow(10, e); if (v >= lo * 0.999 && v <= hi * 1.001) out.push(v);
    }
    return out;
  }
  function fmt(v) {
    const a = Math.abs(v);
    if (a !== 0 && (a < 1e-3 || a >= 1e5)) return v.toExponential(0).replace("e+", "e");
    if (a >= 100) return v.toFixed(0);
    return String(+v.toPrecision(3));
  }

  function extent(layers, axis) {
    let lo = Infinity, hi = -Infinity;
    const push = (v) => { if (isFinite(v)) { if (v < lo) lo = v; if (v > hi) hi = v; } };
    for (const L of layers) {
      if (L.noExtent) continue;
      if (axis === "x") {
        if (Array.isArray(L.x)) L.x.forEach(push);
        if (L.type === "vline") push(L.x);
        if (L.type === "rects" || L.type === "hbars") L.items.forEach(r => { push(r.x0); push(r.x1); });
      } else {
        if (Array.isArray(L.y)) L.y.forEach(push);
        if (L.lo) L.lo.forEach(push);
        if (L.hi) L.hi.forEach(push);
        if (L.type === "hline") push(L.y);
        if (L.type === "rects") L.items.forEach(r => { push(r.y0); push(r.y1); });
        if (L.type === "bars") push(L.base || 0);
      }
    }
    return [lo, hi];
  }

  function plot(canvas, spec) {
    canvas._spec = spec;
    if (!canvas._ro && typeof ResizeObserver !== "undefined") {
      canvas._ro = new ResizeObserver(() => { if (canvas._spec) draw(canvas, canvas._spec); });
      canvas._ro.observe(canvas.parentElement);
    }
    draw(canvas, spec);
  }

  function draw(canvas, spec) {
    const dpr = window.devicePixelRatio || 1;
    const W = canvas.parentElement.clientWidth || 300;
    const H = spec.height || +canvas.getAttribute("data-h") || 260;
    if (canvas.width !== Math.round(W * dpr) || canvas.height !== Math.round(H * dpr)) {
      canvas.width = Math.round(W * dpr); canvas.height = Math.round(H * dpr);
      canvas.style.width = "100%"; canvas.style.height = H + "px";
    }
    const ctx = canvas.getContext("2d");
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, W, H);
    const fg = css("--ink"), mut = css("--muted"), grid = css("--grid");
    const font = "12px " + css("--font-ui");
    const layers = spec.layers || [];
    const pad = Object.assign({ l: 54, r: 22, t: spec.legend ? 26 : 12, b: spec.xLabel ? 42 : 26 }, spec.pad || {});
    const xs = spec.x || {}, ys = spec.y || {};
    let [x0, x1] = extent(layers, "x"), [y0, y1] = extent(layers, "y");
    if (xs.min != null) x0 = xs.min; if (xs.max != null) x1 = xs.max;
    if (ys.min != null) y0 = ys.min; if (ys.max != null) y1 = ys.max;
    if (!isFinite(x0)) { x0 = 0; x1 = 1; } if (!isFinite(y0)) { y0 = 0; y1 = 1; }
    if (x1 === x0) x1 = x0 + 1;
    if (y1 === y0) { y0 -= 1; y1 += 1; }
    if (ys.min == null && !ys.log) { const m = (y1 - y0) * 0.06; y0 -= ys.zero ? 0 : m; y1 += m; }
    if (ys.includeZero) { y0 = Math.min(y0, 0); y1 = Math.max(y1, 0); }
    if (xs.includeZero) { x0 = Math.min(x0, 0); x1 = Math.max(x1, 0); const m = (x1 - x0) * 0.06; if (xs.min == null) x0 -= m; if (xs.max == null) x1 += m; }
    const pw = W - pad.l - pad.r, ph = H - pad.t - pad.b;
    const lx = xs.log, ly = ys.log;
    const tx = (v) => pad.l + (lx ? (Math.log(v) - Math.log(x0)) / (Math.log(x1) - Math.log(x0)) : (v - x0) / (x1 - x0)) * pw;
    const ty = (v) => pad.t + ph - (ly ? (Math.log(v) - Math.log(y0)) / (Math.log(y1) - Math.log(y0)) : (v - y0) / (y1 - y0)) * ph;
    canvas._scale = { tx, ty, x0, x1, y0, y1, pad, pw, ph, W, H,
      ix: (px) => x0 + (px - pad.l) / pw * (x1 - x0) };

    // grid and ticks
    ctx.font = font; ctx.lineWidth = 1;
    const xt = xs.ticks || (lx ? logTicks(x0, x1) : niceTicks(x0, x1, Math.max(3, Math.floor(pw / 80))));
    const yt = ys.ticks || (ly ? logTicks(y0, y1) : niceTicks(y0, y1, Math.max(3, Math.floor(ph / 45))));
    ctx.strokeStyle = grid; ctx.fillStyle = mut;
    ctx.textAlign = "center"; ctx.textBaseline = "top";
    for (const v of xt) { const X = tx(v); if (X < pad.l - 1 || X > pad.l + pw + 1) continue;
      ctx.beginPath(); ctx.moveTo(X, pad.t); ctx.lineTo(X, pad.t + ph); ctx.stroke();
      ctx.fillText((xs.fmt || fmt)(v), X, pad.t + ph + 6); }
    ctx.textAlign = "right"; ctx.textBaseline = "middle";
    for (const v of yt) { const Y = ty(v); if (Y < pad.t - 1 || Y > pad.t + ph + 1) continue;
      ctx.beginPath(); ctx.moveTo(pad.l, Y); ctx.lineTo(pad.l + pw, Y); ctx.stroke();
      ctx.fillText((ys.fmt || fmt)(v), pad.l - 6, Y); }
    ctx.fillStyle = mut; ctx.textAlign = "center"; ctx.textBaseline = "alphabetic";
    if (spec.xLabel) ctx.fillText(spec.xLabel, pad.l + pw / 2, H - 6);
    if (spec.yLabel) { ctx.save(); ctx.translate(13, pad.t + ph / 2); ctx.rotate(-Math.PI / 2); ctx.fillText(spec.yLabel, 0, 0); ctx.restore(); }

    ctx.save(); ctx.beginPath(); ctx.rect(pad.l, pad.t, pw, ph); ctx.clip();
    for (const L of layers) {
      const col = rc(L.color) || fg;
      ctx.globalAlpha = L.alpha == null ? 1 : L.alpha;
      if (L.type === "rects") {
        for (const r of L.items) { ctx.fillStyle = rc(r.color) || col; const X0 = tx(r.x0), X1 = tx(r.x1), Y0 = ty(r.y0), Y1 = ty(r.y1);
          ctx.fillRect(Math.min(X0, X1), Math.min(Y0, Y1), Math.abs(X1 - X0), Math.abs(Y1 - Y0)); }
      } else if (L.type === "band") {
        ctx.fillStyle = col; ctx.beginPath();
        L.x.forEach((v, i) => { const X = tx(v), Y = ty(L.hi[i]); i ? ctx.lineTo(X, Y) : ctx.moveTo(X, Y); });
        for (let i = L.x.length - 1; i >= 0; i--) ctx.lineTo(tx(L.x[i]), ty(L.lo[i]));
        ctx.closePath(); ctx.fill();
      } else if (L.type === "line" || L.type === "step") {
        ctx.strokeStyle = col; ctx.lineWidth = L.width || 2; ctx.setLineDash(L.dash || []);
        ctx.lineJoin = "round"; ctx.beginPath(); let started = false;
        for (let i = 0; i < L.x.length; i++) {
          const yv = L.y[i]; if (yv == null || !isFinite(yv) || (ly && yv <= 0)) { started = false; continue; }
          const X = tx(L.x[i]), Y = ty(yv);
          if (!started) { ctx.moveTo(X, Y); started = true; }
          else if (L.type === "step") { ctx.lineTo(X, ty(L.y[i - 1])); ctx.lineTo(X, Y); }
          else ctx.lineTo(X, Y);
        }
        ctx.stroke(); ctx.setLineDash([]);
      } else if (L.type === "points") {
        ctx.fillStyle = col;
        for (let i = 0; i < L.x.length; i++) { if (!isFinite(L.y[i])) continue; ctx.beginPath(); ctx.arc(tx(L.x[i]), ty(L.y[i]), L.r || 3, 0, 2 * Math.PI); ctx.fill(); }
      } else if (L.type === "bars") {
        const base = L.base || 0;
        for (let i = 0; i < L.x.length; i++) {
          ctx.fillStyle = Array.isArray(L.colors) ? rc(L.colors[i]) : col;
          const X0 = tx(L.x[i] - L.w / 2), X1 = tx(L.x[i] + L.w / 2), Y0 = ty(base), Y1 = ty(L.y[i]);
          ctx.fillRect(X0 + 0.5, Math.min(Y0, Y1), Math.max(1, X1 - X0 - 1), Math.abs(Y1 - Y0));
        }
      } else if (L.type === "hbars") {          // horizontal bars: items {y, x0, x1, color}
        for (const r of L.items) { ctx.fillStyle = rc(r.color) || col; const Y = ty(r.y); const h = L.h || 18;
          ctx.fillRect(tx(Math.min(r.x0, r.x1)), Y - h / 2, Math.max(2, Math.abs(tx(r.x1) - tx(r.x0))), h); }
      } else if (L.type === "vline" || L.type === "hline") {
        ctx.strokeStyle = col; ctx.lineWidth = L.width || 1.2; ctx.setLineDash(L.dash || [4, 4]); ctx.beginPath();
        if (L.type === "vline") { ctx.moveTo(tx(L.x), pad.t); ctx.lineTo(tx(L.x), pad.t + ph); }
        else { ctx.moveTo(pad.l, ty(L.y)); ctx.lineTo(pad.l + pw, ty(L.y)); }
        ctx.stroke(); ctx.setLineDash([]);
        if (L.label) { ctx.fillStyle = col; ctx.font = font; ctx.textAlign = L.type === "vline" ? "left" : "right"; ctx.textBaseline = "top";
          if (L.type === "vline") ctx.fillText(L.label, tx(L.x) + 4, pad.t + 2); else ctx.fillText(L.label, pad.l + pw - 4, ty(L.y) + 3); }
      } else if (L.type === "errbars") {
        ctx.strokeStyle = col; ctx.lineWidth = L.width || 2;
        for (let i = 0; i < L.x.length; i++) { const X = tx(L.x[i]); ctx.beginPath(); ctx.moveTo(X, ty(L.lo[i])); ctx.lineTo(X, ty(L.hi[i]));
          ctx.moveTo(X - 4, ty(L.lo[i])); ctx.lineTo(X + 4, ty(L.lo[i])); ctx.moveTo(X - 4, ty(L.hi[i])); ctx.lineTo(X + 4, ty(L.hi[i])); ctx.stroke(); }
      } else if (L.type === "labels") {
        ctx.fillStyle = col; ctx.font = (L.bold ? "600 " : "") + font; ctx.textAlign = L.align || "left"; ctx.textBaseline = "middle";
        L.items.forEach(t => ctx.fillText(t.text, tx(t.x) + (t.dx || 0), ty(t.y) + (t.dy || 0)));
      }
      ctx.globalAlpha = 1;
    }
    ctx.restore();
    ctx.strokeStyle = mut; ctx.lineWidth = 1; ctx.strokeRect(pad.l + 0.5, pad.t + 0.5, pw, ph);

    if (spec.legend) {
      ctx.font = font; ctx.textBaseline = "middle"; ctx.textAlign = "left";
      let X = pad.l;
      for (const it of spec.legend) {
        const w = ctx.measureText(it.label).width;
        if (X + w + 26 > W) break;
        ctx.fillStyle = rc(it.color); ctx.fillRect(X, 9, 14, it.thin ? 3 : 8);
        ctx.fillStyle = fg; ctx.fillText(it.label, X + 19, 13); X += w + 34;
      }
    }
  }

  root.plot = plot;
  root.redrawAll = function () { document.querySelectorAll("canvas").forEach(cv => { if (cv._spec) draw(cv, cv._spec); }); };
  root.niceTicks = niceTicks;
})(window);
