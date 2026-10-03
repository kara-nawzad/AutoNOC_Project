# Locally served map fonts

Noto Sans Regular and Noto Sans Arabic Regular are distributed under the SIL
Open Font License 1.1; see `OFL.txt` in this directory. Fonts were retrieved
from the Noto project's `notofonts/noto-fonts` repository:

- `hinted/ttf/NotoSans/NotoSans-Regular.ttf`
- `hinted/ttf/NotoSansArabic/NotoSansArabic-Regular.ttf`

MapLibre's native font-face rendering uses these local TTFs, including proper
Arabic/Kurdish shaping. No remote glyph server is necessary. Latin/English
names are preferred when the map data provides them; local names are retained
as the fallback, not machine-translated or invented.
