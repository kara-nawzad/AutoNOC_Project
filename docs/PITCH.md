# The 90-Second Executive Pitch

*AutoNOC — a Non-RT RIC that pays for itself.*
Spoken script; stage directions in italics. Rehearsed runtime: 85–95 s.

---

## 0:00 — HOOK  (~15 s)

> "Every hour a tower is dark, your network loses revenue, your NOC burns
> diesel, and your customer churns to a competitor whose tower still works.
> In Sulaymaniyah that downtime is driven by three things my dashboard is
> about to show you: mountain storms, grid brown-outs, and — the one nobody
> budgets for — **fuel thieves**. AutoNOC is an O-RAN Non-RT RIC that turns
> all three from phone calls into policy."

*Point at the header strip while saying the numbers:*

## 0:15 — THE PROOF, IN NUMBERS  (~20 s)

> "Thirty seeds, ten simulated days each, identical fault schedules per arm.
> Against a pure rule-engine NOC, AutoNOC cuts **5,664 tower-minutes of
> downtime** and **18.6% of OPEX** — and it reaches **61.7% of a
> clairvoyant dispatcher**: two thirds of what a crystal ball would get you,
> with zero false alarms at the site. The advisory arm — AI that waits for a
> human to click approve — scores exactly zero benefit. Latency eats it.
> That is the argument for autonomous, tiered policy."

## 0:35 — LIVE DEMO  (~35 s)

*Run: `Start-Demo.bat` (or uvicorn), seed 131, 'Storm over Goizha'.*

> "Watch the mountain ridge — Goizha, off-grid **Type C** solar sites.
> The PdM rApp raises an amber sonar warning **45 minutes before** the first
> tower fails — inside the crew's travel window, so the truck is already
> rolling when the alarm turns red. *Click a node*: VSWR 1.52 against a
> 1.5 field alarm threshold, PRB utilisation, CQI collapse — this is the
> 3GPP PM language your RAN engineers already read; nothing to relearn.
>
> Now I cut a fiber core. *One splice, and the ring reroutes:* **34 alarms
> collapse into one ticket** — ITU-T X.733 severities, one crew, one splice.
>
> And in Bakrajo, where the grid is bad: the dashboard flags an **ATS
> failure to crank** and a **20% fuel drop with the generator off** — fuel
> theft — as CRITICAL alarms before the sites die. In this city, that alarm
> pays for the whole system."

## 1:10 — CLOSE / ROI  (~20 s)

> "So the ask is small and the arithmetic is public: every number you saw
> is reproduced by a deterministic simulation with 87 passing tests and a
> four-arm counterfactual you can rerun yourself — no vendor black box.
> 5,664 tower-minutes back on air, 18.6% off site OPEX, and 30 alarms
> instead of 30 phone calls. I'd like two pilots: Goizha for predictive
> dispatch, Bakrajo for power and fuel integrity. Shall we pick the seeds?"

---

## Demo checklist (pre-flight)

| # | Check | Why |
|---|---|---|
| 1 | `data/` present, models committed, `AUTONOC_SEED=131` | Act 1 pre-warning lands at tick 45 (~45 min of sim time) |
| 2 | Speed 4×, AI enabled, auto-approve armed | Crew motion + sonar + odometer all visible in 90 s |
| 3 | Click a Goizha node before cutting fiber | Shows VSWR/PRB/CQI gauges + PdM warn tag |
| 4 | Cut ring 0 (Goizha) with isolation | 34-alarm correlation → one MINOR/CRITICAL pair in the FM log |
| 5 | Have the Bakrajo PWR chip + an ATS/fuel CRITICAL log on screen | The theft angle is the local differentiator |

**Fallback if live demo misbehaves:** the committed
`reports/counterfactual_summary.json` has the same numbers — quote 0:15 and
show the file.
