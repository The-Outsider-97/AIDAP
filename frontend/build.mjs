// Bundles src/main.tsx into dist/ with content-hashed assets and writes dist/index.html.
import { build, context } from "esbuild";
import { cpSync, existsSync, mkdirSync, readFileSync, readdirSync, rmSync, writeFileSync } from "node:fs";
import { createHash } from "node:crypto";
import { join } from "node:path";

const watch = process.argv.includes("--watch");
const out = "dist";

function finish(meta) {
  const files = Object.keys(meta.outputs).map((f) => f.replace(/^dist\//, ""));
  const js = files.find((f) => f.endsWith(".js"));
  const css = files.find((f) => f.endsWith(".css"));
  let html = readFileSync("index.html", "utf8");
  html = html.replace("<!--CSS-->", css ? `<link rel="stylesheet" href="/${css}">` : "")
             .replace("<!--JS-->", `<script type="module" src="/${js}"></script>`);
  writeFileSync(join(out, "index.html"), html);
  // static files (logos, favicon, robots) are copied as-is; the large source logos are not shipped to browsers
  for (const f of readdirSync("public")) {
    if (/^(aidap-|favicon|robots|manifest|theme-init)/.test(f)) cpSync(join("public", f), join(out, f));
  }
  const size = files.map((f) => `${f} ${(readFileSync(join(out, f)).length / 1024).toFixed(1)} KB`);
  console.log("built:", size.join(" | "));
}

const options = {
  entryPoints: { app: "src/main.tsx" },
  bundle: true, minify: !watch, sourcemap: watch ? "inline" : false, target: "es2022", format: "esm",
  outdir: join(out, "assets"), entryNames: "[name].[hash]", jsx: "automatic", metafile: true, legalComments: "none",
  loader: { ".svg": "text" }, logLevel: "info",
  define: { "process.env.NODE_ENV": JSON.stringify(watch ? "development" : "production") },
};

if (existsSync(out)) rmSync(out, { recursive: true });
mkdirSync(out, { recursive: true });
if (watch) {
  const ctx = await context({ ...options, plugins: [{ name: "html", setup(b) { b.onEnd((r) => r.metafile && finish(r.metafile)); } }] });
  await ctx.watch();
  console.log("watching…");
} else {
  const r = await build(options);
  finish(r.metafile);
}
