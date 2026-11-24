// Build: render TeX with KaTeX at build time, minify JS/CSS, write the deployable site to dist/.
// Writes the Cloudflare Pages site to ../docs.
// Usage: node tools/build.js   (needs `npm i katex@0.16.11 esbuild@0.24.0` somewhere on NODE_PATH)
const fs = require("fs"), path = require("path");
const katex = require("katex"), esbuild = require("esbuild");
const ROOT = path.join(__dirname, ".."), SITE = path.join(ROOT, "site"), DIST = path.join(ROOT, "..", "docs");
fs.rmSync(DIST, { recursive: true, force: true });
fs.mkdirSync(path.join(DIST, "js"), { recursive: true }); fs.mkdirSync(path.join(DIST, "css"), { recursive: true }); fs.mkdirSync(path.join(DIST, "data"), { recursive: true });
let html = fs.readFileSync(path.join(ROOT, "src", "index.html"), "utf8");
html = html.replace(/\$\$([\s\S]+?)\$\$/g, (_, t) => katex.renderToString(t, { displayMode: true, throwOnError: true, output: "html" }));
html = html.replace(/\$([^$\n]+?)\$/g, (_, t) => katex.renderToString(t, { displayMode: false, throwOnError: true, output: "html" }));
fs.writeFileSync(path.join(DIST, "index.html"), html.replace(/\n\s*\n/g, "\n"));
for (const f of ["model.js", "mc.js", "checks.js", "charts.js", "app.js", "worker.js"]) {
  const out = esbuild.transformSync(fs.readFileSync(path.join(SITE, "js", f), "utf8"), { minify: true, target: "es2019" });
  fs.writeFileSync(path.join(DIST, "js", f), out.code);
}
fs.writeFileSync(path.join(DIST, "css", "style.css"), esbuild.transformSync(fs.readFileSync(path.join(SITE, "css", "style.css"), "utf8"), { loader: "css", minify: true }).code);
const nb = JSON.parse(fs.readFileSync(path.join(SITE, "data", "notebook_results.json"), "utf8"));
fs.writeFileSync(path.join(DIST, "data", "notebook_results.js"), "window.NB_RESULTS=" + JSON.stringify(nb) + ";");
fs.copyFileSync(path.join(SITE, "data", "notebook_results.json"), path.join(DIST, "data", "notebook_results.json"));
// KaTeX stylesheet + only the woff2 fonts
const kd = path.dirname(require.resolve("katex/dist/katex.min.css"));
fs.mkdirSync(path.join(DIST, "vendor", "katex", "fonts"), { recursive: true });
fs.writeFileSync(path.join(DIST, "vendor", "katex", "katex.min.css"),
  fs.readFileSync(path.join(kd, "katex.min.css"), "utf8").replace(/src:url\((fonts\/[^)]+\.woff2)\) format\("woff2"\)[^;}]*/g, 'src:url($1) format("woff2")'));
for (const f of fs.readdirSync(path.join(kd, "fonts"))) if (f.endsWith(".woff2")) fs.copyFileSync(path.join(kd, "fonts", f), path.join(DIST, "vendor", "katex", "fonts", f));
fs.writeFileSync(path.join(DIST, ".nojekyll"), "");   // serve files as-is (no Jekyll processing)
let total = 0; (function walk(d) { for (const f of fs.readdirSync(d)) { const p = path.join(d, f); fs.statSync(p).isDirectory() ? walk(p) : (total += fs.statSync(p).size); } })(DIST);
console.log("dist built:", (total / 1024).toFixed(0), "KB");
