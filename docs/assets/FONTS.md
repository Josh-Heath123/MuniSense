# Fonts used in the assets

| Font | Where | Licence | Source |
| --- | --- | --- | --- |
| Bodoni Moda, variable font (instanced at optical size 96, weight 500) | The "MuniSense" wordmark in `hero-light.svg`, `hero-dark.svg` and `social-preview.png`, as outlined paths | SIL Open Font License 1.1. Copyright 2020 The Bodoni Moda Project Authors (https://github.com/indestructible-type/Bodoni) | Google Fonts repository, `ofl/bodonimoda/BodoniModa[opsz,wght].ttf` (SHA-256 `550f5e34ee0a828d7941b1fe9bc58b34e5260d3f33a61532e6d0a0114e79a5cf`, last changed 2024-02-21), downloaded 2026-11-18 |

The wordmark is stored as vector outlines, not as the font, so it renders the same everywhere. The font file itself is not redistributed. The OFL FAQ treats artwork made with a font as outside the licence's distribution conditions. That reading is recorded here; it has not been checked by a lawyer. The licence text is at https://openfontlicense.org/.

The outlines were made once with fontTools 4.68.0 (MIT), run through `uv run --no-project --with fonttools==4.68.0`. Neither fontTools nor the font is a project dependency (E44). All other text in the assets is set in the reader's system sans and system monospace, so no other font is shipped.
