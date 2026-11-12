# NOBAD

NOBAD is an independent software platform for privacy tools, utilities and practical software.

## Local development

Requirements: Python 3 and Node.js 20+.

Preview the generated static site:

```bash
npm run build
python -m http.server 8000 --directory public
```

Open `http://127.0.0.1:8000/` and `http://127.0.0.1:8000/products/vpn/`.

## Cloudflare Workers deployment

This repository uses **Workers Static Assets** (not Pages).

Configure the Cloudflare Workers Builds project:

- Root directory: repository root
- Build command: `npm run build`
- Deploy command: `npx wrangler deploy`

The build command generates `public/`. Wrangler reads `wrangler.jsonc` and publishes only that directory as static assets. Pushes to `main` trigger the connected deployment.

## Project layout

- `site-source/`: Brotli-compressed HTML source, stored as Base64 text chunks.
- `scripts/prepare-site.mjs`: deterministic build that generates `public/`.
- `public/`: generated deployment output; do not edit by hand.
- `products/vpn/`: VPN product source page.
- `releases/vpn/releases.json`: public VPN release manifest.
- `downloads/vpn/<version>/`: immutable versioned installer artifacts.
- `scripts/publish_vpn_release.py`: local release publisher and SHA-256 generator.
- `docs/RELEASE-PROCESS.md`: release checklist.

## VPN release status

No VPN installer is currently published. The manifest intentionally has an empty release list. Do not advertise or upload a binary until it has been built from the real application, tested, reviewed, and signed where applicable.

See `docs/RELEASE-PROCESS.md` before publishing a release.

## License
Released under the [MIT License](LICENSE). Third-party components bundled with NOBAD VPN are listed in
[VPN_dev/THIRD-PARTY-NOTICES.md](VPN_dev/THIRD-PARTY-NOTICES.md). The MIT License covers the code, not the NOBAD name
or logo.
