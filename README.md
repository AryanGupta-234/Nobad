# NOBAD

NOBAD is an independent software platform for privacy tools, utilities and practical developer software.

## Site structure

- `/` — public brand homepage
- `/products/vpn/` — dedicated NOBAD VPN product page
- `/releases/vpn/releases.json` — public release manifest
- `/docs/` — product and release documentation
- `/.github/workflows/pages.yml` — static deployment workflow

## Local preview

Python 3:

```bash
python -m http.server 8000
```

Open `http://127.0.0.1:8000/`.

## Deploy to Cloudflare Pages

Connect this repository to Cloudflare Pages. Use the repository root as the build output directory, with no build command. The `pages.dev` deployment serves the root `index.html` and clean `/products/vpn/` route.

## Releases

Do not publish placeholder installers. Follow `docs/RELEASE-PROCESS.md` when a real, tested build is ready. The website currently reports that no stable build is published.

## Project principles

- Be accurate about product capabilities and privacy behavior.
- Publish only real, tested artifacts.
- Keep release assets versioned and checksummed.
- Never commit signing keys, tokens or private credentials.
