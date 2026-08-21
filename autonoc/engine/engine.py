"""
NOCEngine — the simulation core.

INVARIANTS enforced here (all tested in tests/test_invariants.py):

  I1  the engine owns time; nothing external advances it but step()
  I2  pure: stdlib only, no framework, no pandas, no wall clock
  I3  deterministic: same seed => identical state at tick N
  I4  step() < 5 ms for 300 nodes
  I9  five independent RNG streams
  I10 the event schedule is exogenous and immutable
"""
from __future__ import annotations

import random
from collections import deque

from . import config as C
from . import dispatch as D
from . import faults as F
from . import physics as P
from .geo import haversine_km, interpolate
from .noise import NoisePool
from .models import FiberCut, Incident
from .network import build_network


class NOCEngine:

    def __init__(self, seed: int = 42, ai_enabled: bool = False,
                 horizon: int = C.TICKS_PER_DAY * 8) -> None:
        self.seed = seed
        self.ai_enabled = ai_enabled
        self.horizon = horizon
        self.tick = 0
        self.paused = False

        # I9 — five independent streams. Sharing one would let AI actions
        # perturb the fault sequence itself, so the counterfactual arms would
        # inhabit different worlds rather than testing two policies.
        self.rng_faults = random.Random(seed * 7919 + 1)
        self.rng_weather = random.Random(seed * 7919 + 2)
        self.rng_physics = random.Random(seed * 7919 + 3)
        # profiled hot path: ~10 gauss() draws per node per tick dominated the
        # tick. Pre-drawn pool, filled once from the seeded stream.
        self.noise = NoisePool(random.Random(seed * 7919 + 33))
        self.rng_traffic = random.Random(seed * 7919 + 4)
        self.rng_ops = random.Random(seed * 7919 + 5)

        self.net = build_network(seed)

        # I10 — everything stochastic is decided before the run starts.
        self.weather_timeline = F.generate_weather_timeline(
            seed, horizon, len(C.AGG_SITES))
        self.schedule = F.generate_schedule(
            seed, horizon, self.net.nodes, self.weather_timeline)
        self.fiber_schedule = F.generate_fiber_schedule(
            seed, horizon, self.net.rings, self.weather_timeline)

        self._sched_by_tick: dict[int, list] = {}
        for ev in self.schedule:
            self._sched_by_tick.setdefault(ev.tick, []).append(ev)
        self._fiber_by_tick: dict[int, list] = {}
        for ev in self.fiber_schedule:
            self._fiber_by_tick.setdefault(ev.tick, []).append(ev)

        self.pending: list = []          # gradual faults mid-degradation
        self.logs: deque = deque(maxlen=C.MAX_LOG_ENTRIES)

        # per-event ledger: the recall denominator must be identical across
        # arms, so masked events are recorded rather than silently dropped
        self.ledger: dict[int, dict] = {}
        self.mttr_samples: list[float] = []
        self.stats = {"injected": 0, "masked": 0, "repairs": 0,
                      "remote_resets": 0, "self_healed": 0,
                      # M6 — Commander accounting
                      "pre_empted": 0, "acted_upon": 0, "false_dispatch": 0}

        # M6 — Commander state.
        #   ai_mode      "off" | "ml" | "rules"  (set by the inference layer)
        #   ai_policy    "auto" (tier-1 + tier-2) | "advisory" (tier-2 only,
        #                approvals by a human/driver) — used by the M7 study
        #   ai_verdicts  {node_id: {"p_fail", "cls", "action", "tier"}}
        #                 populated by ai/serve.py on the worker thread, or
        #                 directly by tests. With ai_enabled=False it is
        #                 never consulted, so I3 determinism is untouched.
        #   pending_actions  tier-2 actions awaiting approve / veto
        self.ai_mode: str = "off"
        self.ai_policy: str = "auto"
        self.ai_verdicts: dict[str, dict] = {}
        self.pending_actions: list[dict] = []
        self._next_action_id: int = 1
        self._tier2_cooldown: dict[str, int] = {}

    # ------------------------------------------------------------ helpers
    @property
    def nodes(self):
        return self.net.nodes

    @property
    def teams(self):
        return self.net.teams

    @property
    def sim_time(self) -> str:
        tod = self.tick % C.TICKS_PER_DAY
        day = self.tick // C.TICKS_PER_DAY + 1
        return f"D{day} {tod * 5 // 60:02d}:{tod * 5 % 60:02d}"

    def log(self, msg: str, severity: str = "INFO", node_id: str | None = None):
        self.logs.append({"tick": self.tick, "time": self.sim_time,
                          "severity": severity, "message": msg,
                          "node_id": node_id})

    # ------------------------------------------------------------ main loop
    def step(self) -> None:
        self.tick += 1
        weather = self.weather_timeline[min(self.tick, self.horizon - 1)]

        # M6 — Commander acts BEFORE scheduled faults fire, so a pre-emption
        # this tick stops an activation this tick. No-ops when ai_enabled is
        # False (no verdicts, no pending actions), preserving I3.
        if self.ai_enabled:
            self._commander_hook()

        self._decay_mitigations()

        self._start_scheduled_faults()
        self._start_scheduled_cuts()
        self._advance_pending()

        for node in self.net.nodes:
            w = weather[node.agg_id]
            site = self.net.agg_sites[node.agg_id]
            penalty = 3.0 if w["type"] == "Storm" else 1.5 if w["type"] == "Wind" else 0.0
            # M6 — Commander mitigations modulate offered traffic. Both terms
            # are 0.0 unless an action is live, so ai_enabled=False is
            # bit-identical to the pre-M6 path.
            base_load = P.traffic_load(self.tick, node.agg_id, self.noise)
            node.traffic_load = min(
                1.0, max(0.05, base_load * (1.0 - node.throttle_pct)
                         + node.traffic_boost))
            P.update_cpu(node, self.noise)
            P.update_dust(node, w["type"], w["rain"])
            P.update_thermal(node, self.tick, w["temp_delta"], self.noise)
            P.update_radio(node, site.clutter_c, penalty, w["wind"], self.noise)
            P.update_power(node, self.tick, self.noise)
            self._check_power_failure(node)
            self._tick_self_heal(node)
            node.snapshot(self.tick)

        self._ripple()
        self._dispatch()
        self._advance_teams()
        self._watchdog()

    # ------------------------------------------------------------ faults
    def _start_scheduled_faults(self) -> None:
        for ev in self._sched_by_tick.get(self.tick, ()):
            node = self.net.by_id[ev.node_id]
            # pre-empted: the Commander stopped this episode before it could
            # activate (M6). The schedule event still exists (I10); the ledger
            # already holds the pre_empted transition, so we just do nothing.
            if node.pre_empted_episode == ev.episode_id:
                if ev.episode_id not in self.ledger:
                    self.ledger[ev.episode_id] = {"state": "pre_empted",
                                                  "tick": self.tick,
                                                  "node": ev.node_id,
                                                  "kind": ev.kind}
                continue
            # masked: the schedule fired at a node that is already broken OR
            # already mid-degradation from another episode. Recorded, not
            # dropped, so every arm keeps the identical episode set — the
            # node's single episode_id cannot be clobbered by a second event,
            # which would corrupt pre-emption and standby bookkeeping (M7).
            if node.is_faulty or node.under_repair \
                    or (node.is_gradual and node.episode_id >= 0):
                self.ledger[ev.episode_id] = {"state": "masked", "tick": self.tick}
                self.stats["masked"] += 1
                continue
            self.ledger[ev.episode_id] = {"state": "injected", "tick": self.tick,
                                          "node": ev.node_id, "kind": ev.kind}
            self.stats["injected"] += 1
            if ev.is_gradual and ev.onset_offset > 0:
                node.episode_id = ev.episode_id
                node.pre_empted_episode = -1   # a fresh episode, not the old one
                node.is_gradual = True
                node.onset_tick = self.tick + ev.onset_offset
                node.fault_progress = 0.0
                node.fault_severity = ev.severity
                self.pending.append((ev, node, self.tick))
            else:
                self._activate(ev, node)

    def _advance_pending(self) -> None:
        """Degrade nodes that are partway through a gradual fault."""
        still = []
        for ev, node, start in self.pending:
            if node.under_repair or node.is_faulty:
                continue                       # pre-empted or overtaken
            if node.pre_empted_episode == ev.episode_id:
                continue                       # Commander stopped it — drop
            elapsed = self.tick - start
            p = elapsed / max(ev.onset_offset, 1)
            frac = F.curve_progress(ev.curve, p)
            node.fault_progress = p
            F.apply_degradation(node, ev.kind, frac * 0.85, ev.severity,
                                self.rng_physics)
            if elapsed >= ev.onset_offset:
                self._activate(ev, node)
            else:
                still.append((ev, node, start))
        self.pending = still

    def _activate(self, ev, node) -> None:
        node.status = ev.kind
        node.status_timer = 0
        node.episode_id = ev.episode_id
        node.fault_severity = ev.severity
        node.fault_started_tick = self.tick
        node.last_changed_tick = self.tick
        F.apply_degradation(node, ev.kind, 1.0, ev.severity, self.rng_physics)
        sev = "CRITICAL" if ev.kind in (C.STATUS_RF, C.STATUS_POWER) else "HIGH"
        self.log(f"{node.node_id} — {C.STATUS_NAMES[ev.kind]}"
                 f"{' (marginal)' if ev.severity < 1.0 else ''}", sev, node.node_id)

    def _start_scheduled_cuts(self) -> None:
        for ev in self._fiber_by_tick.get(self.tick, ()):
            ring = self.net.rings[ev.ring_id]
            if not ring.segments:
                continue
            seg = ring.segments[ev.segment_idx % len(ring.segments)]
            lat, lon = interpolate(seg.from_lat, seg.from_lon,
                                   seg.to_lat, seg.to_lon, ev.position)
            cut = FiberCut(segment=seg, position=ev.position, lat=lat, lon=lon,
                           cause=ev.cause, started_tick=self.tick)
            ring.cuts.append(cut)
            self.ledger[ev.episode_id] = {"state": "injected", "tick": self.tick,
                                          "ring": ev.ring_id, "kind": C.STATUS_BACKHAUL}
            # Protected ring semantics:
            #   1 cut  -> traffic reroutes the long way. Service survives, but
            #             latency rises and the ring is now UNPROTECTED, so a
            #             crew is dispatched immediately.
            #   2 cuts -> the span between them is isolated and goes dark.
            #
            # An earlier build raised no incident for a single cut, so nothing
            # was ever repaired: cuts accumulated silently until a ring
            # randomly reached two and 33 nodes went dark at once.
            if ring.is_isolated:
                for nid in ring.node_ids:
                    n = self.net.by_id[nid]
                    if n.is_faulty:
                        continue
                    n.status = C.STATUS_BACKHAUL
                    n.fault_started_tick = self.tick
                    n.last_changed_tick = self.tick
                    F.apply_degradation(n, C.STATUS_BACKHAUL, 1.0, 1.0,
                                        self.rng_physics)
                self.log(f"FIBER CUT {seg.seg_id} ({ev.cause}) — ring "
                         f"{ev.ring_id} ISOLATED, {len(ring.node_ids)} nodes "
                         f"dark", "CRITICAL")
            else:
                # rerouted: measurable degradation, service intact
                for nid in ring.node_ids:
                    n = self.net.by_id[nid]
                    n.latency = min(C.MAX_LATENCY_MS, n.latency * 1.6)
                    n.last_changed_tick = self.tick
                self.log(f"Fiber cut {seg.seg_id} ({ev.cause}) — ring "
                         f"{ev.ring_id} rerouting, UNPROTECTED. "
                         f"{len(ring.node_ids)} nodes at risk", "HIGH")

    def _check_power_failure(self, node) -> None:
        dead = (not node.grid_available and node.battery_pct <= 0.5
                and node.generator_fuel_pct <= 0.0)
        if dead and node.status == C.STATUS_HEALTHY:
            node.status = C.STATUS_POWER
            node.fault_started_tick = self.tick
            node.last_changed_tick = self.tick
            self.log(f"{node.node_id} OFFLINE — total power loss",
                     "CRITICAL", node.node_id)

    def _tick_self_heal(self, node) -> None:
        if not node.is_faulty or node.under_repair:
            return
        node.status_timer += 1
        limit = C.SELF_HEAL_TICKS.get(node.status)
        if limit and node.status_timer >= limit:
            self._heal(node, "auto-resolved")
            self.stats["self_healed"] += 1

    def _heal(self, node, reason: str) -> None:
        if node.episode_id in self.ledger:
            self.ledger[node.episode_id]["state"] = "resolved"
            self.ledger[node.episode_id]["resolved_at"] = self.tick
        node.status = C.STATUS_HEALTHY
        node.status_timer = 0
        node.fault_progress = 0.0
        node.fault_severity = 1.0
        node.is_gradual = False
        node.onset_tick = -1
        node.episode_id = -1
        node.tech_dispatched = False
        node.under_repair = False
        node.assigned_team = None
        node.fault_started_tick = -1
        node.last_changed_tick = self.tick
        node.s11 += (-22.0 - node.s11) * 0.8
        node.packet_loss *= 0.2
        node.latency = min(node.latency, 40.0)
        self.log(f"{node.node_id} restored — {reason}", "SUCCESS", node.node_id)

    def _ripple(self) -> None:
        for node in self.net.nodes:
            if node.status != C.STATUS_RF:
                continue
            for nid in self.net.neighbours[node.node_id]:
                n = self.net.by_id[nid]
                if n.is_faulty:
                    continue
                n.packet_loss = min(
                    100.0, n.packet_loss + self.rng_physics.uniform(*C.RIPPLE_PACKET_LOSS))
                n.cpu_load = min(
                    99.0, n.cpu_load + self.rng_physics.uniform(*C.RIPPLE_CPU_LOAD))

    # ------------------------------------------------------------ dispatch
    def _dispatch(self) -> None:
        # remote reset first — free repairs on modernised hardware
        for node in self.net.nodes:
            if node.can_remote_reset and not node.under_repair:
                p = C.GEN_REMOTE_RESET[node.generation]
                if self.rng_ops.random() < p:
                    self._heal(node, "remote reset")
                    self.stats["remote_resets"] += 1

        free = [t for t in self.net.teams if t.available]
        if not free:
            return
        incidents = D.correlate_alarms(self.net, self.tick)
        if not incidents:
            return
        for inc in incidents:
            inc.priority = D.priority_score(inc, self.net, self.tick)
        incidents.sort(key=lambda i: i.priority, reverse=True)
        for inc in incidents:
            if not free:
                break
            team = D.best_team(inc, free, self.tick)
            free.remove(team)
            team.dispatch_to(inc.target_id, inc.target_lat, inc.target_lon, self.tick)
            if inc.kind == "FIBER_CUT":
                for ring in self.net.rings:
                    for cut in ring.cuts:
                        if cut.segment.seg_id == inc.target_id:
                            cut.dispatched = True
            for nid in inc.affected:
                n = self.net.by_id.get(nid)
                if n is not None:
                    n.tech_dispatched = True
                    n.assigned_team = team.team_id
                    n.last_changed_tick = self.tick
            km = haversine_km(C.DEPOT_LAT, C.DEPOT_LON, inc.target_lat, inc.target_lon)
            self.log(f"{team.name} dispatched to {inc.target_id} "
                     f"({km:.1f} km, ETA {team.eta_ticks()}t). "
                     f"Root cause: {inc.root_cause}", "INFO")
            team.incident = inc

    def _advance_teams(self) -> None:
        for team in self.net.teams:
            if team.state == "EN_ROUTE":
                if team.advance(self.tick):
                    inc = team.incident
                    if inc is None:
                        team.send_home(self.tick)
                        continue
                    # M7 — a pre-dispatched crew arrives before any fault
                    # materialises. It HOLDS on site (STANDBY) for the rest of
                    # the prediction window: the fault may still land while
                    # they wait, which is the entire point of pre-positioning.
                    # Only if nothing happens by expiry is it a false dispatch.
                    if (inc.kind == "PRE_DISPATCH"
                            and not self.net.by_id[inc.target_id].is_faulty):
                        team.state = "STANDBY"
                        team.standby_ticks_left = self._standby_horizon(
                            self.net.by_id[inc.target_id])
                        team.last_changed_tick = self.tick
                        self.log(f"{team.name} on site at {inc.target_id} — "
                                 f"standing by {team.standby_ticks_left}t "
                                 f"(pre-positioned)", "INFO", inc.target_id)
                        continue
                    team.state = "REPAIRING"
                    mult = team.skill_mult(inc.required_skill)
                    team.repair_ticks_left = max(1, round(inc.repair_ticks * mult))
                    for nid in inc.affected:
                        n = self.net.by_id.get(nid)
                        if n is not None:
                            n.under_repair = True
                            n.last_changed_tick = self.tick
                    self.log(f"{team.name} on site at {inc.target_id} — repair started")
            elif team.state == "REPAIRING":
                team.repair_ticks_left -= 1
                team.last_changed_tick = self.tick
                if team.repair_ticks_left <= 0:
                    self._complete_repair(team)
            elif team.state == "STANDBY":
                # M7 — holding at a pre-dispatched node. If the fault lands,
                # repair starts immediately (downtime ~1 tick, not ~1 hour).
                # If the window expires with no fault, it was a false dispatch.
                team.standby_ticks_left -= 1
                team.last_changed_tick = self.tick
                inc = team.incident
                node = self.net.by_id.get(inc.target_id) if inc else None
                if node is not None and node.is_faulty:
                    team.state = "REPAIRING"
                    mult = team.skill_mult(inc.required_skill)
                    team.repair_ticks_left = max(1, round(inc.repair_ticks * mult))
                    for nid in inc.affected:
                        n = self.net.by_id.get(nid)
                        if n is not None:
                            n.under_repair = True
                            n.last_changed_tick = self.tick
                    self.log(f"{team.name} — fault materialised on site at "
                             f"{inc.target_id}, repair started", "INFO",
                             inc.target_id)
                elif team.standby_ticks_left <= 0:
                    self.stats["false_dispatch"] += 1
                    self.log(f"{team.name} released from {inc.target_id} — "
                             f"no fault within the prediction window "
                             f"(FALSE DISPATCH)", "HIGH", inc.target_id)
                    if node is not None:
                        node.tech_dispatched = False
                        node.assigned_team = None
                        node.last_changed_tick = self.tick
                    team.incident = None
                    team.dispatch_count += 1
                    team.send_home(self.tick)
            elif team.state == "RETURNING":
                if team.advance(self.tick):
                    team.go_idle(self.tick)

    def _complete_repair(self, team) -> None:
        """Every mission must reset ALL state or teams leak (v1 bug)."""
        inc = team.incident
        if inc is not None:
            if inc.kind == "FIBER_CUT":
                for ring in self.net.rings:
                    hit = any(c.segment.seg_id == inc.target_id
                              for c in ring.cuts)
                    for cut in ring.cuts:
                        if cut.segment.seg_id == inc.target_id:
                            cut.repaired = True
                    ring.cuts = [c for c in ring.cuts if not c.repaired]
                    # a ring back below two cuts is no longer isolated
                    if hit and not ring.is_isolated:
                        for nid in ring.node_ids:
                            n = self.net.by_id[nid]
                            if n.status == C.STATUS_BACKHAUL:
                                self._heal(n, "backhaul restored")
            for nid in inc.affected:
                n = self.net.by_id.get(nid)
                if n is not None and n.is_faulty:
                    if n.status == C.STATUS_POWER:
                        n.grid_available = True
                        n.generator_fuel_pct = 100.0
                        n.battery_pct = max(n.battery_pct, 50.0)
                    n.dust_accum = 0.0        # service cleans filters
                    self._heal(n, f"repaired by {team.name}")
            mttr = (self.tick - team.mission_start_tick) * C.TICK_MINUTES
            self.mttr_samples.append(mttr)
            self.stats["repairs"] += 1
            team.incident = None
        team.dispatch_count += 1
        team.send_home(self.tick)

    def _release_cut(self, seg_id: str) -> None:
        for ring in self.net.rings:
            for cut in ring.cuts:
                if cut.segment.seg_id == seg_id:
                    cut.dispatched = False

    def _watchdog(self) -> None:
        """Nothing may stay broken and unattended forever."""
        for node in self.net.nodes:
            if (node.needs_technician and not node.under_repair
                    and node.fault_started_tick >= 0
                    and self.tick - node.fault_started_tick > C.STUCK_WATCHDOG_TICKS
                    and node.tech_dispatched):
                node.tech_dispatched = False
                node.assigned_team = None
                self.log(f"WATCHDOG: {node.node_id} unrepaired for "
                         f"{self.tick - node.fault_started_tick} ticks — re-queued",
                         "HIGH", node.node_id)

    # ------------------------------------------------------------ commander (M6)
    def _commander_hook(self) -> None:
        """Turn AI verdicts into actions. Runs every tick while AI is on.

        The verdicts are produced off the sim thread by ai/serve.py (or set
        directly by tests). This hook is the ONLY place verdicts become
        actions, and it is a pure function of (engine state, verdicts) — no
        wall clock, no I/O — so it preserves I3 when ai_enabled is on.
        """
        from . import commander as CM

        for node_id, verdict in list(self.ai_verdicts.items()):
            node = self.net.by_id.get(node_id)
            if node is None or node.is_faulty or node.under_repair:
                continue
            p = float(verdict.get("p_fail", 0.0))
            cls = int(verdict.get("cls", C.STATUS_RF))
            action = verdict.get("action")
            if action is None:
                action = CM.default_action_for(cls, node.is_critical, p)
            if not CM.decision(p):
                continue
            if CM.tier_for(action) == CM.TIER_AUTO:
                if self.ai_policy == "advisory":
                    continue          # advisory: surface suggestions only
                # A cheap tier-1 mitigation can only pre-empt a SOFT fault.
                # If the Doctor misclassified a crew-worthy pending fault
                # (RF / power) as congestion, throttling must NOT cancel it —
                # the antenna is still broken, it will activate and need a
                # real crew. Pre-emption is gated on the ACTUAL fault kind
                # from the ledger, never on the classifier's guess.
                entry = self.ledger.get(node.episode_id, {})
                actual = entry.get("kind")
                if actual not in (C.STATUS_CONGESTION, C.STATUS_OVERHEAT):
                    continue
                did = CM.apply_tier1(self, node, action)
                if did and node.episode_id >= 0 and node.is_gradual:
                    if CM.mark_preempted(self, node):
                        CM.reset_preempted_node(self, node)
            else:
                # tier 2 — needs an operator; dedupe per node + cooldown so a
                # persistent verdict cannot spam the approval queue
                if node_id in self._tier2_cooldown \
                        and self.tick < self._tier2_cooldown[node_id]:
                    continue
                if not any(a["node_id"] == node_id
                           and a["state"] == "pending"
                           for a in self.pending_actions):
                    self._queue_action(node_id, cls, p, action)

    def _queue_action(self, node_id: str, cls: int, p: float,
                      action: str) -> None:
        aid = self._next_action_id
        self._next_action_id += 1
        self.pending_actions.append({
            "action_id": aid, "node_id": node_id, "node": node_id,
            "cls": int(cls),
            "probability": round(float(p), 4), "action": action,
            "tier": 2, "label": C.STATUS_NAMES.get(int(cls), "Fault"),
            "created_tick": self.tick, "state": "pending",
        })
        self.log(f"AI: pre-dispatch {node_id} proposed "
                 f"({C.STATUS_NAMES.get(int(cls), 'fault')}, P={p:.2f}) — "
                 f"awaiting approval", "HIGH", node_id)

    def approve_action(self, action_id: int) -> dict:
        """Operator approves a tier-2 action. Sends the crew immediately."""
        for i, a in enumerate(self.pending_actions):
            if a["action_id"] == action_id:
                self.pending_actions.pop(i)
                res = self._execute_approved(a)
                # cooldown only when the action actually dispatched or the
                # fault landed meanwhile — a busy fleet must be able to retry
                if res.get("ok") or res.get("late"):
                    self._tier2_cooldown[a["node_id"]] = \
                        self.tick + C.TIER2_REQUEUE_COOLDOWN_TICKS
                return res
        return {"ok": False, "reason": f"no pending action {action_id}"}

    def veto_action(self, action_id: int) -> dict:
        """Operator vetoes a tier-2 action. Nothing is dispatched."""
        for i, a in enumerate(self.pending_actions):
            if a["action_id"] == action_id:
                self.pending_actions.pop(i)
                self._tier2_cooldown[a["node_id"]] = \
                    self.tick + C.TIER2_REQUEUE_COOLDOWN_TICKS
                self.log(f"VETOED action {action_id} ({a['node_id']})",
                         "INFO", a["node_id"])
                return {"ok": True, "vetoed": action_id}
        return {"ok": False, "reason": f"no pending action {action_id}"}

    def _execute_approved(self, a: dict) -> dict:
        self.stats["acted_upon"] += 1
        node = self.net.by_id.get(a["node_id"])
        if node is None:
            return {"ok": False, "reason": "unknown node"}
        if node.is_faulty or node.under_repair:
            # the fault landed while waiting for approval; the regular
            # state-driven dispatcher is already covering it
            self.log(f"Approval {a['action_id']} late — {node.node_id} "
                     f"already faulty; regular dispatch covers it", "INFO",
                     node.node_id)
            return {"ok": True, "late": True}
        return self._pre_dispatch(node, a["cls"], a["probability"])

    def _pre_dispatch(self, node, cls: int, p_fail: float) -> dict:
        """Send the best crew to a node predicted to fail (tier 2)."""
        from . import dispatch as D
        from .models import Incident

        free = [t for t in self.net.teams if t.available]
        if not free:
            self.log(f"PRE-DISPATCH {node.node_id} deferred — fleet busy",
                     "HIGH", node.node_id)
            return {"ok": False, "reason": "no crew available"}
        skill = C.REPAIR_SKILL.get(cls, "GENERAL")
        repair = C.REPAIR_TICKS.get(cls, 12)
        inc = Incident(
            kind="PRE_DISPATCH", target_id=node.node_id,
            target_lat=node.lat, target_lon=node.lon,
            affected=[node.node_id], status=cls,
            required_skill=skill, repair_ticks=repair,
            root_cause=f"predicted {C.STATUS_NAMES.get(cls, 'fault')} "
                       f"(P={p_fail:.2f})",
        )
        team = D.best_team(inc, free, self.tick)
        team.dispatch_to(node.node_id, node.lat, node.lon, self.tick)
        team.incident = inc
        node.tech_dispatched = True
        node.assigned_team = team.team_id
        node.last_changed_tick = self.tick
        self.log(f"{team.name} PRE-DISPATCHED to {node.node_id} "
                 f"(predicted {C.STATUS_NAMES.get(cls, 'fault')}, "
                 f"P={p_fail:.2f})", "INFO", node.node_id)
        return {"ok": True, "team": team.name, "node": node.node_id}

    def _standby_horizon(self, node) -> int:
        """How long a pre-positioned crew holds, in ticks.

        If the node is mid-degradation (a pending gradual fault), hold until
        its predicted activation — the fault can still land at any moment.
        Otherwise hold the full Oracle horizon (60 min): if nothing happens
        by then, the prediction was false.
        """
        if node.is_gradual and node.onset_tick > self.tick:
            return max(1, node.onset_tick - self.tick)
        return C.STANDBY_HORIZON_TICKS

    def _decay_mitigations(self) -> None:
        """Throttles and load boosts expire on a fixed, deterministic schedule."""
        step = 1.0 / max(C.THROTTLE_TICKS, 1)
        for node in self.net.nodes:
            if node.throttle_pct > 0.0:
                node.throttle_pct = max(0.0, node.throttle_pct - step)
            if node.traffic_boost > 0.0:
                node.traffic_boost = max(0.0, node.traffic_boost - step)

    def ai_payload(self) -> dict:
        """Live AI-performance panel numbers (M6 §8.4), computed from state."""
        from . import commander as CM
        return CM.ai_panel(self)

    # ------------------------------------------------------------ manual
    def cut_fiber(self, ring_id: int, isolate: bool = True,
                  cause: str = "construction") -> dict:
        """Manually cut a ring. Used by the demo and by tests.

        A double cut on one protected ring happens roughly twice per simulated
        year — genuinely rare, and correct physics. Rather than inflate the
        rate 300x and call it realistic, the demo triggers it on command.
        """
        from .models import FiberCut
        from .geo import interpolate

        ring = self.net.rings[ring_id % len(self.net.rings)]
        if not ring.segments:
            return {"ok": False, "reason": "ring has no segments"}

        made = []
        want = 2 if isolate else 1
        for k in range(want):
            if len(ring.cuts) >= 2:
                break
            seg = ring.segments[(k * 3 + 1) % len(ring.segments)]
            pos = 0.35 + 0.3 * k
            lat, lon = interpolate(seg.from_lat, seg.from_lon,
                                   seg.to_lat, seg.to_lon, pos)
            ring.cuts.append(FiberCut(segment=seg, position=pos, lat=lat,
                                      lon=lon, cause=cause,
                                      started_tick=self.tick))
            made.append(seg.seg_id)

        if ring.is_isolated:
            dark = 0
            for nid in ring.node_ids:
                n = self.net.by_id[nid]
                if n.is_faulty:
                    continue
                n.status = C.STATUS_BACKHAUL
                n.fault_started_tick = self.tick
                n.last_changed_tick = self.tick
                F.apply_degradation(n, C.STATUS_BACKHAUL, 1.0, 1.0,
                                    self.rng_physics)
                dark += 1
            self.log(f"FIBER CUT {' + '.join(made)} ({cause}) — ring "
                     f"{ring.ring_id} ISOLATED, {dark} nodes dark",
                     "CRITICAL")
            return {"ok": True, "ring": ring.ring_id, "segments": made,
                    "isolated": True, "nodes_dark": dark}

        self.log(f"Fiber cut {made[0]} ({cause}) — ring {ring.ring_id} "
                 f"rerouting, UNPROTECTED", "HIGH")
        return {"ok": True, "ring": ring.ring_id, "segments": made,
                "isolated": False, "nodes_dark": 0}

    # ------------------------------------------------------------ readouts
    def kpis(self) -> dict:
        n = len(self.net.nodes)
        counts = {s: 0 for s in C.STATUS_NAMES}
        for node in self.net.nodes:
            counts[node.status] += 1
        m = self.mttr_samples
        return {
            "tick": self.tick, "sim_time": self.sim_time,
            "availability": round(counts[C.STATUS_HEALTHY] / n * 100.0, 2),
            "healthy": counts[C.STATUS_HEALTHY],
            "congestion": counts[C.STATUS_CONGESTION],
            "overheat": counts[C.STATUS_OVERHEAT],
            "rf": counts[C.STATUS_RF],
            "power": counts[C.STATUS_POWER],
            "backhaul": counts[C.STATUS_BACKHAUL],
            "active_teams": sum(1 for t in self.net.teams if not t.available),
            "grid_failures": sum(1 for x in self.net.nodes if not x.grid_available),
            "mttr_min": round(sum(m) / len(m), 1) if m else 0.0,
            "injected": self.stats["injected"],
            "masked": self.stats["masked"],
            "repairs": self.stats["repairs"],
        }
