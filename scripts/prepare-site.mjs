// Builds the static NOBAD website into public/ (served by Cloudflare Workers static assets).
//
// Source of truth: plain HTML in site-pages/ (edit those files directly). Release details are filled in at build
// time from releases/vpn/releases.json, so the download desk works without JavaScript and can never drift from
// the manifest. The build fails on an unknown {{PLACEHOLDER}}.
import { cp, mkdir, readdir, readFile, rm, writeFile } from "node:fs/promises";
import { extname, join, resolve, sep } from "node:path";

const root = process.cwd();
const output = resolve(root, "public");
const pages = resolve(root, "site-pages");

const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);

function releaseValues(manifest) {
  const releases = Array.isArray(manifest.releases) ? manifest.releases : [];
  const cur = releases.find((r) => r.version === manifest.latest) || releases[0];
  if (!cur) throw new Error("releases.json has no release");
  for (const k of ["version", "releaseDate", "downloadUrl", "notesUrl", "sha256", "size"]) {
    if (!cur[k]) throw new Error(`releases.json: latest release is missing "${k}"`);
  }
  if (!/^https:\/\/github\.com\/AryanGupta-234\/Nobad\/releases\/download\//.test(cur.downloadUrl)) {
    throw new Error("releases.json: downloadUrl must be a GitHub Release asset of this repository");
  }
  if (!/^[0-9a-f]{64}$/.test(cur.sha256)) throw new Error("releases.json: sha256 must be 64 lowercase hex digits");
  const file = cur.downloadUrl.split("/").pop();
  const history = releases.map((r) =>
    `<div class="release-item"><span class="version">${esc(r.version)}</span><span>${esc(r.releaseDate)} · ${esc(r.summary)}</span><span class="muted">${esc(r.channel)}</span></div>`
  ).join("");
  return {
    VPN_VERSION: esc(cur.version),
    VPN_DATE: esc(cur.releaseDate),
    VPN_URL: esc(cur.downloadUrl),
    VPN_NOTES: esc(cur.notesUrl),
    VPN_SHA256: esc(cur.sha256),
    VPN_SIZE: esc(cur.size),
    VPN_FILE: esc(file),
    VPN_SBOM: esc(cur.downloadUrl.replace(/\.exe$/, ".sbom.json")),
    VPN_SUMMARY: esc(cur.summary || "A published release is available. Review its notes and integrity details before installing."),
    VPN_PLATFORM: esc(cur.platform || "Windows"),
    VPN_ARCH: esc(cur.architecture || "x64"),
    VPN_HISTORY: history,
  };
}

async function* walk(dir) {
  for (const entry of await readdir(dir, { withFileTypes: true })) {
    const p = join(dir, entry.name);
    if (entry.isDirectory()) yield* walk(p);
    else yield p;
  }
}

await rm(output, { recursive: true, force: true });
await mkdir(output, { recursive: true });

// 1. Pages, policy pages, _headers, robots.txt, sitemap.xml, 404.html, favicon.ico, legal.css
await cp(pages, output, { recursive: true });

// 2. Only the public image assets (not READMEs or internal docs)
await mkdir(resolve(output, "assets"), { recursive: true });
for (const name of await readdir(resolve(root, "assets"))) {
  if ([".png", ".svg", ".ico", ".webp"].includes(extname(name).toLowerCase())) {
    await cp(resolve(root, "assets", name), resolve(output, "assets", name));
  }
}

// 3. Release manifest, read by the download desk script as well
const manifestText = await readFile(resolve(root, "releases/vpn/releases.json"), "utf8");
const values = releaseValues(JSON.parse(manifestText));
await mkdir(resolve(output, "releases/vpn"), { recursive: true });
await writeFile(resolve(output, "releases/vpn/releases.json"), manifestText);

// 4. Fill release placeholders in every HTML page
for await (const file of walk(output)) {
  if (extname(file) !== ".html") continue;
  if (!resolve(file).startsWith(output + sep)) throw new Error("Output path escaped public directory");
  let html = await readFile(file, "utf8");
  html = html.replace(/\{\{([A-Z0-9_]+)\}\}/g, (m, key) => {
    if (!(key in values)) throw new Error(`${file}: unknown placeholder ${m}`);
    return values[key];
  });
  await writeFile(file, html);
  console.log(`Built ${file.slice(output.length + 1).replaceAll("\\", "/")} (${Buffer.byteLength(html).toLocaleString()} bytes)`);
}

console.log(`NOBAD static site build complete (NOBAD VPN ${values.VPN_VERSION}).`);
