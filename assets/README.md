# NOBAD brand asset

The website uses the transparent NOBAD logo at:

`/assets/nobad-logo.png`

The logo is generated during `npm run build` from the Base64 source chunks in `site-source/brand-logo-*.b64`.

Source artwork: **1086 × 362 px transparent PNG**.

The logo retains the black tilted tile, orange lowercase mark, black wordmark, and orange dot. It has a transparent background and works on both light and dark website sections.

The build script verifies the reconstructed PNG with a SHA-256 integrity check and checks its dimensions before publishing it to `public/assets/nobad-logo.png`.

Both the main-site header and VPN product-page header reference the same asset.
