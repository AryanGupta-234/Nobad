import { mkdir, readFile, rm, writeFile, cp } from "node:fs/promises";
import { brotliDecompressSync } from "node:zlib";
import { dirname, resolve, sep } from "node:path";

const root = process.cwd();
const output = resolve(root, "public");
const source = resolve(root, "site-source");

function patchVpnPage(html) {
  const oldBrand = '<a class="brand" href="../../">NOBAD.</a>';
  const newBrand = '<a class="brand" href="../../" aria-label="NOBAD home"><img class="brand-logo" src="/assets/nobad-logo-light.png" alt="nobad." width="1086" height="362"></a>';

  if (!html.includes(oldBrand)) {
    throw new Error("VPN brand markup changed; refusing to silently skip the logo replacement.");
  }

  html = html.replace(oldBrand, newBrand);

  const navFix = `
/* VPN header follows the main NOBAD floating navigation system. */
.nav {
  top: 18px;
  color: var(--w);
}
.nav .brand {
  display: inline-flex;
  align-items: center;
  justify-self: start;
  width: fit-content;
  max-width: 100%;
  padding: 0;
  background: transparent;
  color: var(--w);
  border-radius: 0;
}
.nav .brand-logo {
  display: block;
  flex: 0 0 128px;
  width: 128px;
  height: auto;
  max-height: 43px;
  object-fit: contain;
}

/* Curved black centre capsule, matching the homepage nav-pill. */
.pill {
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 6px;
  background: var(--k);
  color: var(--w);
  border: 1px solid rgba(255,255,255,.24);
  border-radius: 999px;
  box-shadow: 0 8px 24px rgba(0,0,0,.18);
}
.pill a {
  border-radius: 999px;
  padding: 11px 17px;
  color: var(--w);
  background: transparent;
  font: 400 11px var(--mono);
  text-transform: uppercase;
  transition: background .2s, color .2s, transform .2s;
}
.pill a:hover,
.pill a[aria-current="location"] {
  color: var(--k);
  background: var(--w);
  transform: translateY(-1px);
}

/* Keep the VPN-specific Main Site action as a rounded outline control. */
.back {
  justify-self: end;
  display: inline-flex;
  align-items: center;
  padding: 10px 15px;
  color: var(--w);
  background: transparent;
  border: 1px solid rgba(255,255,255,.65);
  border-radius: 999px;
  font: 400 11px var(--mono);
  text-transform: uppercase;
  transition: background .2s, color .2s, border-color .2s;
}
.back:hover {
  color: var(--k);
  background: var(--w);
  border-color: var(--w);
}
`;

  if (!html.includes("</style>")) {
    throw new Error("VPN page stylesheet closing tag was not found.");
  }

  return html.replace("</style>", `${navFix}</style>`);
}

async function writeBrotli(parts, relativeTarget) {
  const encoded = (await Promise.all(
    parts.map((part) => readFile(resolve(source, part), "utf8"))
  )).join("").replace(/\s+/g, "");

  if (!encoded || !/^[A-Za-z0-9+/=]+$/.test(encoded)) {
    throw new Error(`Invalid Base64 source for ${relativeTarget}`);
  }

  let bytes = brotliDecompressSync(Buffer.from(encoded, "base64"));
  let html = bytes.toString("utf8");

  if (!/^<!doctype html>/i.test(html.trimStart())) {
    throw new Error(`Decoded file is not an HTML document: ${relativeTarget}`);
  }

  if (relativeTarget === "index.html") {
    const oldHomeBrand = '<a class="brand" href="#top" aria-label="nobad home"><span class="brand-mark">n</span><span>nobad<span style="opacity:.45">.</span></span></a>';
    const newHomeBrand = '<a class="brand" href="#top" aria-label="nobad home"><img class="brand-logo" src="/assets/nobad-logo.png" alt="nobad." width="1086" height="362"></a>';

    if (!html.includes(oldHomeBrand)) {
      throw new Error("Main-site brand markup changed; refusing to silently skip the logo replacement.");
    }

    html = html.replace(oldHomeBrand, newHomeBrand);
    if (!html.includes("</style>")) {
      throw new Error("Main-site stylesheet closing tag was not found.");
    }
    html = html.replace("</style>", `
/* Shared NOBAD raster wordmark — original 1086 × 362 transparent PNG source */
.brand { gap: 0; }
.brand-logo { display: block; width: 128px; height: auto; object-fit: contain; }
</style>`);
    bytes = Buffer.from(html, "utf8");
  }

  if (relativeTarget === "products/vpn/index.html") {
    html = patchVpnPage(html);
    bytes = Buffer.from(html, "utf8");
  }

  const target = resolve(output, relativeTarget);
  if (!target.startsWith(output + sep)) {
    throw new Error("Output path escaped public directory");
  }

  await mkdir(dirname(target), { recursive: true });
  await writeFile(target, bytes);
  console.log(`Built ${relativeTarget} (${bytes.length.toLocaleString()} bytes)`);
}

await rm(output, { recursive: true, force: true });
await mkdir(output, { recursive: true });

await writeBrotli(
  ["index-01.br.b64", "index-02.br.b64", "index-03.br.b64", "index-04.br.b64"],
  "index.html"
);

await writeBrotli(
  ["vpn-page-01.br.b64", "vpn-page-02.br.b64"],
  "products/vpn/index.html"
);

await mkdir(resolve(output, "releases/vpn"), { recursive: true });
await cp(
  resolve(root, "releases/vpn/releases.json"),
  resolve(output, "releases/vpn/releases.json")
);

await cp(resolve(root, "docs"), resolve(output, "docs"), { recursive: true });
await cp(resolve(root, "assets"), resolve(output, "assets"), { recursive: true });

// Plain HTML pages (code signing policy, privacy policy), copied as they are.
try {
  await cp(resolve(root, "site-pages"), output, { recursive: true });
} catch (error) {
  if (error.code !== "ENOENT") throw error;
}

const downloads = resolve(root, "downloads");
try {
  await cp(downloads, resolve(output, "downloads"), { recursive: true });
} catch (error) {
  if (error.code !== "ENOENT") throw error;
}

console.log("NOBAD static site build complete.");
