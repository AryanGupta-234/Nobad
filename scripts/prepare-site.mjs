import { mkdir, readFile, rm, writeFile, cp } from "node:fs/promises";
import { brotliDecompressSync } from "node:zlib";
import { dirname, resolve, sep } from "node:path";

const root = process.cwd();
const output = resolve(root, "public");
const source = resolve(root, "site-source");

async function writeBrotli(parts, relativeTarget) {
  const encoded = (await Promise.all(
    parts.map((part) => readFile(resolve(source, part), "utf8"))
  )).join("").replace(/\s+/g, "");

  if (!encoded || !/^[A-Za-z0-9+/=]+$/.test(encoded)) {
    throw new Error(`Invalid Base64 source for ${relativeTarget}`);
  }

  const bytes = brotliDecompressSync(Buffer.from(encoded, "base64"));
  const html = bytes.toString("utf8");

  if (!/^<!doctype html>/i.test(html.trimStart())) {
    throw new Error(`Decoded file is not an HTML document: ${relativeTarget}`);
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

const downloads = resolve(root, "downloads");
try {
  await cp(downloads, resolve(output, "downloads"), { recursive: true });
} catch (error) {
  if (error.code !== "ENOENT") throw error;
}

console.log("NOBAD static site build complete.");
