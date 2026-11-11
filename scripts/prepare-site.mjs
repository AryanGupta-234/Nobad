import { mkdir, readFile, rm, writeFile, cp } from "node:fs/promises";
import { brotliDecompressSync } from "node:zlib";
import { dirname, resolve, sep } from "node:path";
import { createHash } from "node:crypto";

const root = process.cwd();
const output = resolve(root, "public");
const source = resolve(root, "site-source");

function patchVpnPage(html) {
  const oldBrand = '<a class="brand" href="../../">NOBAD.</a>';
  const newBrand = '<a class="brand" href="../../" aria-label="NOBAD home"><img class="brand-logo" src="/assets/nobad-logo.png" alt="nobad." width="1086" height="362"></a>';

  if (!html.includes(oldBrand)) {
    throw new Error("VPN brand markup changed; refusing to silently skip the logo replacement.");
  }

  html = html.replace(oldBrand, newBrand);

  const navFix = `
/* Shared NOBAD wordmark and intrinsic navbar sizing */
.nav .brand {
  display: inline-flex;
  align-items: center;
  justify-self: start;
  width: max-content;
  max-width: 100%;
}
.nav .brand {
  padding: 6px 12px;
}
.nav .brand-logo {
  display: block;
  flex: 0 0 128px;
  width: 128px;
  height: auto;
  max-height: 43px;
  object-fit: contain;
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

// Reassemble and integrity-check the original transparent NOBAD logo.
const logoChunks = [
  "brand-logo-01.b64",
  "brand-logo-02.b64",
  "brand-logo-03.b64",
  "brand-logo-04a.b64",
  "brand-logo-04b.b64",
  "brand-logo-04c1.b64",
  "brand-logo-04c2.b64"
];
const logoBase64 = (await Promise.all(
  logoChunks.map((part) => readFile(resolve(source, part), "utf8"))
)).join("").replace(/\\s+/g, "");

if (!/^[A-Za-z0-9+/]+={0,2}$/.test(logoBase64)) {
  throw new Error("Transparent NOBAD logo source is not valid Base64.");
}

const logoBytes = Buffer.from(logoBase64, "base64");
const logoSha256 = createHash("sha256").update(logoBytes).digest("hex");
const expectedLogoSha256 = "d8ee6c6d80630723767c2981958dbd1c0cf6fb1deb193d19aeceea4baa7a9653";

if (logoSha256 !== expectedLogoSha256) {
  throw new Error(`NOBAD logo integrity check failed: ${logoSha256}`);
}

if (
  logoBytes.subarray(0, 8).toString("hex") !== "89504e470d0a1a0a" ||
  logoBytes.readUInt32BE(16) !== 1086 ||
  logoBytes.readUInt32BE(20) !== 362
) {
  throw new Error("NOBAD logo is not the expected 1086 × 362 PNG.");
}

await mkdir(resolve(output, "assets"), { recursive: true });
await writeFile(resolve(output, "assets/nobad-logo.png"), logoBytes);
console.log("Built transparent NOBAD logo (1086 × 362 px, SHA-256 verified).");

const downloads = resolve(root, "downloads");
try {
  await cp(downloads, resolve(output, "downloads"), { recursive: true });
} catch (error) {
  if (error.code !== "ENOENT") throw error;
}

console.log("NOBAD static site build complete.");
