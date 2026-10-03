# Design Vision — the AutoNOC command center (v3 UI)

*Living document. Status: phase 1 shipped (2026-10); phase 2 planned.*

## The goal

A dashboard that reads as a **product**, not a simulation harness: the
density of a real NOC wall with the motion quality of a modern SaaS app
(Linear/Vercel-grade), in the operator's own language (3GPP PM counters,
ITU-T X.733, O-RAN rApps).

Reference direction agreed with the owner: the "NEXUS-style" operations
layout — grouped sidebar, KPI card row with sparklines, map + live alarm
feed, analytics bottom row — rebuilt around AutoNOC's *real* assets (real
city map, real fiber topology, real X.733 feed) instead of stock decoration.

## Layout contract

```
┌ sidebar ─┬ header (title · sim clock · ⌘K · bell · controls) ─────────┐
│ MONITOR  ├ KPI cards ×6, each with a LIVE sliding sparkline           │
│ ANALYZE  ├ ┌ city map (dark tiles, light-tubes, sonars) ─┐ ┌ FM feed ┐ │
│ MANAGE   │ │                                             │ │ FLIP    │ │
│ sys card │ └─────────────────────────────────────────────┘ │ list    │ │
│          ├ throughput chart │ district bars │ power gauge │ donut    │
└──────────┴────────────────────────────────────────────────────────────┘
   + right slide-over drawer: Inspector (gauges/tags/inject) · rApp panel
```

## The motion system ("the smoothest") — non-negotiable rules

1. **One master `requestAnimationFrame` clock.** Polls only move *targets*;
   every rendered quantity is a spring scalar integrated with delta-time
   (same math as Framer Motion: `vel += (-k(x-target) - c·vel)·dt`), so the
   UI is frame-rate independent and never snaps between polls.
2. **Time-parameterised sliding windows.** Sparklines/area charts store
   samples with birth-times; the line scrolls *continuously* every frame
   instead of redrawing per sample. New samples join seamlessly.
3. **FLIP for lists.** The FM feed inserts/reorders by measuring once and
   animating transforms (Web Animations API); removals collapse height.
4. **Transform/opacity/dash only** in hot paths (bars use `scaleX`, never
   `width`); `tabular-nums` so rolling numbers never reflow.
5. **No `innerHTML` in hot paths.** Panels are built once; frames write
   attributes/text only.
6. **Delta-time clamped** (`dt ≤ 50 ms`) and the loop idles while the tab is
   hidden — no jump-cut on return.
7. Decoration (ripples, glow, dash-flow) may use CSS keyframes; *data*
   motion must come from the engine above.

## Visual language

- Dark Matter basemap; panels `#0a0f18` on `#04070d`, 1 px `#16202e` borders,
  14 px radii, hover lift `translateY(-2px)` + border glow.
- Neon semantics from `/api/config` (I5): status colours, gauge bands,
  labels, X.733 severity names — the frontend renders, never computes.
- Fiber rings: SVG light-tubes (`stroke-dashoffset` flow + particle dots
  riding the path); cut ⇒ red, frozen, rippling marker.
- PdM `warn` verdicts: amber sonar pings before failures (server-derived).

## Phases

- **Phase 1 (shipped):** vanilla-JS implementation of this layout + motion
  engine in `autonoc/web` — zero build step, fly.io deploy unchanged, all
  features preserved (inspector drawer, rApp panel, inject, controls, ⌘K).
  Design reference mockups live outside the repo (`design-preview/`,
  cinematic v1 + motion-engine v2) — fake data, used to agree the direction.
- **Phase 2 (planned, owner-gated):** React + Vite + TypeScript + Framer
  Motion + deck.gl componentisation of the same contract (views as routes,
  3D district extrusions, shared-element transitions). Requires adding a
  Node build stage to the Dockerfile and CI; backend/API untouched either
  way — the delta cursor protocol already suits any frontend.

## Why phase 1 is vanilla (decision record)

Smoothness comes from the *engine*, not the framework: the spring integrator,
sliding windows and FLIP are ~150 lines of dependency-free JS. Shipping them
in vanilla kept the repo build-free and the deploy risk-free while delivering
the agreed motion quality; React remains the right phase-2 choice for
componentisation and ecosystem, not for smoothness.
