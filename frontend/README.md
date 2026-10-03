# AutoNOC React command center

React 18, TypeScript, Vite, Tailwind CSS 4 (with the explicit JS config/plugin),
Framer Motion, Lucide, and React Leaflet. No generated or mock telemetry is used
by the application. Fonts are bundled locally.

## Run

From the repository root, with Python dependencies installed:

```sh
npm ci --prefix frontend
npm run build --prefix frontend
python -m uvicorn autonoc.api.main:app --host 0.0.0.0 --port 8000
```

Open `http://localhost:8000`. Vite writes **`autonoc/web/dist`**, which FastAPI
serves at `/` with hashed assets under `/assets`. Dist and node_modules are
ignored; rebuild after a fresh checkout. If no build exists, the old dashboard
remains a fallback. The Dockerfile builds the frontend automatically in a Node
stage, then copies only the built files into the Python runtime.

For hot reload, run the API on 8000 and `npm run dev --prefix frontend` in a
second terminal. Open Vite's 5173 URL. All browser API URLs are relative;
Vite proxies `/api` to the backend. Arena's `*.e2b.app` hosts are allowed.
Use the Python process environment to select the seed or enable AI at boot.

## Interactions

- Header: pause/resume, paused single-step, 0.25–10× speed, double fiber cut,
  supported node faults, AI enable/disable.
- Map: zoom/reset/expand, district focus, independent site/fiber/crew/district
  layers, tower click for the inspector. The map's geometry and semantics come
  from `/api/config` and server snapshots. Cut markers use actual cut coordinates.
- Search: Cmd/Ctrl+K or the header search button; site-ID and district matching.
- Incidents: active, server-correlated alarms with severity filtering; retained
  log history is a separate dialog, so cleared events are not presented as active.
- A1 cards: optimistic approve/veto, rollback and notification on rejection.
- Analytics: traffic/PRB view, quality history, server-ranked site load, highest
  current forecast, power mix, and maintenance fleet details.
- Settings: explicit opt-in demo auto-approval. The worker's existing inference-
  cycle timing still applies; this is not a redesigned decision system.
- Keyboard: native focus-trapped dialogs, Escape to close, labeled controls,
  visible focus, skip link. Reduced motion disables decorative animation and
  settles interpolation. The narrow layout scrolls instead of clipping panels.

## Contract and invariants

`api/presentation.py` adds **read-only** server projections for aggregate traffic,
mean synthetic site drop rate, active incidents, power mix, fleet state, ranked
cells, and highest-risk forecast. `History.record` runs only alongside the API
clock under the engine lock. GET requests never advance time or append samples.

`/api/config` adds `presentation` metadata: semantic palette, severity and power
colors, names, supported fault classes, forecast horizon, speed limits, and the
existing schematic road corridors. The frontend performs number formatting,
search, filtering, and chart/marker geometry only—not operational analytics.

The existing `/api/delta?since=<tick>` endpoint now returns a **complete bounded
snapshot** and sets `resync: true`. At 300 nodes this is a deliberate correctness
tradeoff: regular physics changes did not update the old node dirty tick, warning
state was consumed globally, and same-tick paused controls were lost. Every
client now receives current nodes, teams and the latest 60 logs independently.
A process `run_id` distinguishes server restarts. Gzip reduces the payload size.
The frontend replaces each frame instead of appending duplicate logs. Future
larger networks should use a true state revision/event cursor rather than a
simulation tick as a delivery cursor.

Engine time, RNG, simulation dynamics, models, Commander policies and feature
order are unchanged. The only engine-config changes are display status colors.
Do **not** mistake this redesign for a fix to the independent physics/ML concerns
in `docs/PROJECT_STUDY_2026-10-03.md`.

## Honest presentation limits

- Fuel is shown as **tank %**, not invented liters (no tank capacity exists).
- Oracle forecasts show the configured **60-minute window**, not a fabricated
  time-to-failure or leaked scheduled onset.
- AI toggle enables/disables the existing predictor. Model availability selects
  ML/rules fallback; there is no backend endpoint for a user-selected Rules mode.
- Dust, generator failures, weather, ATS, and theft are not invented injectors.
  The dialog lists exactly the fault kinds the engine endpoint accepts.
- Power-event KPI counts cumulative ATS/theft events; active ATS latches are
  separately labeled. Drop rate is the mean synthetic site counter, not a
  measured bearer-weighted production KPI. Traffic is the aggregate simulated
  throughput, whose physical modeling limitations remain in the engine.
- Street cartography uses **OpenFreeMap/OpenMapTiles vector data**, rendered
  by MapLibre underneath Leaflet's live network overlays. The navy style, WebGL
  worker, and Noto Latin/Arabic fonts are bundled locally; **street geometry
  still requires internet access to `tiles.openfreemap.org`**. No API key.
  Street names come from mapped `name:en`, `name:latin`, or `name` fields, never
  invented labels; unnamed streets remain unnamed. Building footprints and
  selected place labels appear as you zoom in. Attribution stays visible.
- Map layers includes **streets** and **street names** toggles. The status reads
  "Street map · OpenStreetMap" only after visible road geometry is decoded and
  rendered. A source error, missing WebGL, or a 20-second initial-load timeout
  produces "Streets unavailable · schematic" with a retry button. That fallback
  is explicitly NOT full street mapping. Former raster tile services are gone;
  provider error-message PNGs cannot be presented as cartographic tiles.
- Browser map tests use **test-only PBF fixtures** to verify real WebGL rendering,
  local font requests, label controls, and failure handling. They do not prove
  live-provider availability. The sandbox's external TLS restriction prevents a
  live tile check here; actual provider access is reported in the preview itself.
- Shared unauthenticated simulation controls remain demo-only. This implementation
  does not add operator authentication or claim standards certification.

## Animation implementation

NumberTween writes its own text in RAF using cubic ease-out; retargeting starts
from the displayed value. Fleet positions use one RAF loop with linear, subpixel travel across the observed
server-update cadence plus a small jitter cushion. The old alpha-.12 chase
settled too early and Leaflet's integer-pixel rounding caused visible stepping.
Interpolation is bounded by confirmed coordinates, introduces a small visual
lag, ignores duplicate endpoints, resets on a new server run, and settles within
200ms of a pause/single-step. Reduced motion and hidden tabs settle immediately. React is not
rerendered at animation frequency. SVG paths/radial meters and list FLIP use
Framer Motion. No browser clock generates telemetry. Pausing stops new server
samples and decorative flow while in-flight values may finish settling.

## Verification

```sh
npm test --prefix frontend
npm run build --prefix frontend
python -m pytest tests/ -q
# Start an isolated API before browser tests; tests deliberately inject faults.
cd frontend
npx playwright install --with-deps chromium
npm run test:e2e
```

`AUTONOC_TEST_URL` can select an isolated test server. `CHROMIUM_PATH` optionally
selects an installed Chromium. Browser tests cover paused stepping, site search,
injection, cuts, map layers, fleet/history, mobile overflow, approval rollback,
veto, reconnect, and reduced motion. Python tests cover snapshot completeness,
multiple readers, same-tick controls, read-only history and derived metrics.

The committed CI builds and tests both sides before deploying; deployment is
restricted to main-branch push events. No deployment was performed during the
redesign. A production Docker build must still be validated where Docker and
the PyTorch CPU wheel host are available.
