/* worker.js — runs Monte Carlo jobs off the main thread and streams results back. */
importScripts("model.js", "mc.js", "checks.js");
const jobs = {};
self.onmessage = function (e) {
  const msg = e.data;
  if (msg.cmd === "cancel") { if (jobs[msg.id]) jobs[msg.id](); delete jobs[msg.id]; return; }
  if (msg.cmd === "checks") {
    const list = self.makeChecks(self.F1, msg.nb);
    self.postMessage({ id: msg.id, state: { titles: list.map(c => c[0]) } });
    list.forEach((c, i) => { let ok, m; try { [ok, m] = c[1](); } catch (err) { ok = false; m = String(err); } self.postMessage({ id: msg.id, state: { i, ok, msg: m, finished: i === list.length - 1 } }); });
    return;
  }
  if (msg.cmd === "run") {
    jobs[msg.id] = self.runMC(msg.job, function (state) {
      self.postMessage({ id: msg.id, state });
      if (state.finished) delete jobs[msg.id];
    }, function (fn) { setTimeout(fn, 0); });
  }
};
