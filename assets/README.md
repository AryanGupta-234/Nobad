# NOBAD brand asset

Upload the supplied original logo image to this directory with this exact path and filename:

`assets/nobad-logo.png`

Expected source image: **2048 × 682 px**, RGBA PNG.

The image is intentionally used as supplied. Do not crop, resize, recolor, trace, or recompress it. Its checkerboard background is baked into the uploaded pixels (the alpha channel is fully opaque), so that checkerboard will remain visible in the site header.

The build script copies this directory to `public/assets/`. Both the main-site header and the VPN product-page header reference `/assets/nobad-logo.png`. Until the PNG is uploaded, they fall back to the existing SVG wordmark.
