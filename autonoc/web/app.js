/* AutoNOC frontend.
 *
 * Three v1 failures are fixed structurally here:
 *
 *  1. CLICK TARGETS. v1 used 4 px markers = 64 px^2, nine times below the
 *     WCAG 24x24 minimum. Here each node has a 6 px visible dot plus an
 *     invisible 14 px interactive pad = 784 px^2, twelve times larger, with
 *     no visual change.
 *
 *  2. NEON GLOW. v1 put everything on L.canvas(), which draws pixels rather
 *     than DOM, so CSS drop-shadow could never apply. The glow was not
 *     missing, it was architecturally impossible. Here healthy nodes stay on
 *     canvas (fast, ~270 of them) while faulty nodes are promoted to DOM
 *     markers that can carry the glow.
 *
 *  3. MARKER CHURN. v1 destroyed and recreated markers on every status
 *     change, which also killed open popups and hover state. Here markers
 *     are created once and mutated with setStyle().
 *
 * The frontend renders. It never computes. Colours, thresholds and region
 * metadata all come from GET /api/config.
 */
'use strict';

let CFG = null;
let map, canvas;
let lastTick = 0, failures = 0, selected = null;
let mapOk = false;              // false if the map library failed to load

/* On-screen error logger: any JavaScript error is appended to the Event Log
 * panel so it is VISIBLE on the page and can be pasted back for debugging.
 * Without this, a silent JS crash looks exactly like "nothing is changing". */
function onScreenError(msg) {
  try {
    const box = document.getElementById('log');
    if (box) {
      const div = document.createElement('div');
      div.className = 'ln CRITICAL';
      div.innerHTML = `<span class="t">JS!</span><span class="m">${String(msg).slice(0, 250)}</span>`;
      box.appendChild(div);
      while (box.children.length > 120) box.removeChild(box.firstChild);
    }
  } catch (_) { /* never let the logger itself crash */ }
  console.error('AutoNOC JS:', msg);
}
window.addEventListener('error', e => onScreenError(e.message || 'unknown JS error'));
window.addEventListener('unhandledrejection', e => onScreenError('async: ' + (e.reason || 'unknown')));

const dots = new Map();     // id -> visible canvas marker
const pads = new Map();     // id -> invisible click target
const doms = new Map();     // id -> DOM marker (faulty only)
const vehs = new Map();     // team id -> marker
const ringLines = new Map();
const cutMarks = new Map();
const collapseLines = [];
let knownCuts = new Set();
const nodeState = new Map();  // id -> last payload

/* ------------------------------------------------------------ boot */
async function boot() {
  try {
    CFG = await (await fetch('/api/config')).json();
  } catch (e) { onScreenError('cannot fetch /api/config — is the server running? ' + e); return; }
  try { initMap(); } catch (e) { onScreenError('map init failed: ' + e); }
  try { buildLegend(); } catch (e) { onScreenError('legend failed: ' + e); }
  try {
    const first = await (await fetch('/api/data')).json();
    applyFull(first);
    lastTick = first.tick;
  } catch (e) { onScreenError('cannot fetch /api/data — ' + e); }
  setInterval(poll, 2000);
  try { wireControls(); } catch (e) { onScreenError('controls failed: ' + e); }
}

function initMap() {
  if (typeof L === 'undefined') {
    // Leaflet could not load (CDN blocked / no internet). The dashboard
    // still works without the map: panels and metrics keep updating.
    mapOk = false;
    onScreenError('MAP LIBRARY MISSING — map disabled, panels still update');
    return;
  }
  map = L.map('map', {
    center: CFG.map_center, zoom: CFG.map_zoom,
    zoomControl: true, preferCanvas: false, attributionControl: false
  });
  try {
    L.tileLayer(
      'https://stadiamaps.com{z}/{x}/{y}{r}.png',
      { 
        maxZoom: 20,
        attribution: '&copy; Stadia Maps, &copy; OpenMapTiles, &copy; OpenStreetMap contributors'
      }
    ).addTo(map);
  } catch (e) { onScreenError('basemap tiles failed (need internet): ' + e); }
  canvas = L.canvas({ padding: 0.5 });
  mapOk = true;


  // EPC cores and depot
  const p = CFG.epc_primary, b = CFG.epc_backup, d = CFG.depot;
  markIcon(p.lat, p.lon, '★', 'epc', `${p.name} — Primary EPC (${p.backhaul})`);
  markIcon(b.lat, b.lon, '◆', 'epc', `${b.name} — Backup EPC (${b.backhaul})`);
  markIcon(d.lat, d.lon, '🔧', 'depot', 'Maintenance Depot');

  CFG.agg_sites.forEach(s => {
    L.circle([s.lat, s.lon], {
      radius: 900, color: s.color, fillColor: s.color,
      fillOpacity: 0.045, weight: 1, opacity: 0.35, interactive: false,
      renderer: canvas
    }).addTo(map);
  });

  map.on('click', () => { selected = null; renderInspector(); });
}

function markIcon(lat, lon, glyph, cls, title) {
  L.marker([lat, lon], {
    icon: L.divIcon({ className: '', html: `<div class="${cls}">${glyph}</div>`,
                      iconSize: [22, 22], iconAnchor: [11, 11] }),
    title, interactive: false
  }).addTo(map);
}

function buildLegend() {
  document.getElementById('legend').innerHTML =
    Object.entries(CFG.status_names).map(([k, name]) =>
      `<div class="lg"><i style="background:${CFG.status_colors[k]}"></i>${name}</div>`
    ).join('');
}

/* ------------------------------------------------------------ polling */
async function poll() {
  try {
    const r = await fetch(`/api/delta?since=${lastTick}`, { cache: 'no-store' });
    if (!r.ok) throw new Error(r.status);
    const d = await r.json();
    d.resync ? applyFull(d) : applyDelta(d);
    lastTick = d.tick;
    failures = 0;
    setConn(true);
  } catch (e) {
    if (++failures >= 2) setConn(false);
  }
}

function setConn(up) {
  const el = document.getElementById('conn');
  el.className = 'conn ' + (up ? 'live' : 'down');
  el.querySelector('span').textContent = up ? 'LIVE' : 'RECONNECTING';
}

function applyFull(d) {
  d.nodes.forEach(n => { nodeState.set(n.id, n); upsertNode(n); });
  drawRings(d.rings);
  renderIncidents(d.rings, d.nodes);
  d.teams.forEach(upsertTeam);
  renderKPIs(d.kpis);
  renderAggs(d.agg);
  renderTeams(d.teams);
  document.getElementById('log').innerHTML = '';
  appendLogs(d.logs);
  renderInspector();
  if (d.ai) renderAI(d.ai);
}

function applyDelta(d) {
  d.nodes.forEach(n => { nodeState.set(n.id, n); upsertNode(n); });
  d.teams.forEach(upsertTeam);
  drawRings(d.rings);
  renderIncidents(d.rings, d.nodes);
  renderKPIs(d.kpis);
  renderAggs(d.agg);
  renderTeams(d.teams);
  appendLogs(d.logs);
  if (d.ai) renderAI(d.ai);
  if (selected && d.nodes.some(n => n.id === selected)) renderInspector();
}

/* ------------------------------------------------------------ nodes */
function upsertNode(n) {
  const colour = CFG.status_colors[n.status];
  const healthy = n.status === 0;
  if (!mapOk) return;      // no map: skip markers, panels still update

  let dot = dots.get(n.id);
  if (!dot) {
    // visible marker: small, on canvas, non-interactive so clicks fall
    // through to the pad underneath
    dot = L.circleMarker([n.lat, n.lon], {
      renderer: canvas, radius: 6, fillColor: colour, color: '#fff',
      weight: 1.4, opacity: .85, fillOpacity: .95, interactive: false
    }).addTo(map);
    dots.set(n.id, dot);

    // invisible 14 px hit pad -> 28x28 px = 784 px^2 click target
    const pad = L.circleMarker([n.lat, n.lon], {
      renderer: canvas, radius: 14, opacity: 0, fillOpacity: 0,
      interactive: true, bubblingMouseEvents: false
    }).addTo(map);
    pad.on('click', ev => {
      L.DomEvent.stopPropagation(ev);
      selected = pickNearest(ev.latlng);   // nearest centre, not topmost
      renderInspector();
    });
    pad.bindTooltip(() => tipFor(n.id), { direction: 'top', offset: [0, -8] });
    pads.set(n.id, pad);
    dot._st = -1;
  }

  if (dot._st !== n.status) {
    dot.setStyle({ fillColor: colour, radius: healthy ? 6 : 9 });
    dot._st = n.status;
    // promote faulty nodes to DOM so they can glow; demote when healed
    const existing = doms.get(n.id);
    if (!healthy && !existing) {
      const crit = (n.status === 3 || n.status === 4);
      const m = L.marker([n.lat, n.lon], {
        icon: L.divIcon({
          className: '',
          html: `<div class="fault-dot ${crit ? 'crit-dot' : ''}" style="--c:${colour}"></div>`,
          iconSize: [15, 15], iconAnchor: [7.5, 7.5]
        }),
        interactive: false, zIndexOffset: 400
      }).addTo(map);
      doms.set(n.id, m);
    } else if (healthy && existing) {
      map.removeLayer(existing);
      doms.delete(n.id);
    } else if (!healthy && existing) {
      const crit = (n.status === 3 || n.status === 4);
      existing.getElement().querySelector('.fault-dot')
        .setAttribute('style', `--c:${colour}`);
      existing.getElement().querySelector('.fault-dot')
        .className = `fault-dot ${crit ? 'crit-dot' : ''}`;
    }
  }
}

/* Hit pads are 28 px wide but nodes average 25 px apart at zoom 12, so pads
 * overlap in dense districts. Leaflet resolves overlap by z-order, which
 * feels arbitrary; pick the nearest centre instead. */
function pickNearest(latlng) {
  let best = null, bestD = Infinity;
  for (const [id, n] of nodeState) {
    const d = (n.lat - latlng.lat) ** 2 + (n.lon - latlng.lng) ** 2;
    if (d < bestD) { bestD = d; best = id; }
  }
  return best;
}

function tipFor(id) {
  const n = nodeState.get(id);
  if (!n) return id;
  return `<b>${n.id}</b><br>${CFG.status_names[n.status]}<br>`
       + `RSRP ${n.rsrp} dBm · ${n.temp}°C`;
}

/* ------------------------------------------------------------ rings */
function drawRings(rings) {
  if (!rings || !mapOk) return;
  rings.forEach(r => {
    let line = ringLines.get(r.id);
    const cut = !!r.cut;
    if (!line) {
      line = L.polyline(r.path, {
        renderer: canvas, color: '#2A3550', weight: 1.2,
        opacity: .5, dashArray: '3 6', interactive: false
      }).addTo(map);
      ringLines.set(r.id, line);
      line._cut = false;
    }
    if (line._cut !== cut) {
      line.setStyle(cut
        ? { color: CFG.status_colors[5], weight: 2.4, opacity: .95, dashArray: null }
        : { color: '#2A3550', weight: 1.2, opacity: .5, dashArray: '3 6' });
      line._cut = cut;
    }
    const existing = cutMarks.get(r.id);
    if (cut && !existing) {
      const m = L.marker([r.cut.lat, r.cut.lon], {
        icon: L.divIcon({ className: '',
          html: `<div class="cut-marker"></div>`,
          iconSize: [20, 20], iconAnchor: [10, 10] }),
        interactive: false, zIndexOffset: 1000
      }).addTo(map);
      m.bindTooltip(`FIBER CUT · ${r.cut.seg} · ${r.cut.cause}`,
                    { direction: 'top' });
      cutMarks.set(r.id, m);
      // Animate the alarms collapsing onto their shared cause.
      // Without this beat the viewer sees 34 red dots and reads it as 34
      // separate failures — precisely the naive interpretation the whole
      // correlation claim exists to disprove.
      if (!knownCuts.has(r.id)) {
        knownCuts.add(r.id);
        animateCollapse(r);
      }
    } else if (!cut && existing) {
      map.removeLayer(existing);
      cutMarks.delete(r.id);
      knownCuts.delete(r.id);
    }
  });
}

function animateCollapse(ring) {
  if (!mapOk) return;
  const dark = ring.nodes
    .map(id => nodeState.get(id))
    .filter(n => n && n.status === 5);
  if (!dark.length) return;
  map.flyTo([ring.cut.lat, ring.cut.lon], 13, { duration: 1.1 });
  dark.forEach((n, i) => {
    setTimeout(() => {
      const line = L.polyline(
        [[n.lat, n.lon], [ring.cut.lat, ring.cut.lon]],
        { color: CFG.status_colors[3], weight: 1.3, opacity: 0.5,
          dashArray: '4 6', interactive: false }
      ).addTo(map);
      collapseLines.push(line);
      setTimeout(() => {
        map.removeLayer(line);
        const k = collapseLines.indexOf(line);
        if (k >= 0) collapseLines.splice(k, 1);
      }, 2200);
    }, i * 28);
  });
}

function renderIncidents(rings, nodes) {
  const panel = document.getElementById('incident-panel');
  const box = document.getElementById('incidents');
  const cuts = (rings || []).filter(r => r.cut);
  if (!cuts.length) { panel.style.display = 'none'; return; }
  panel.style.display = '';
  box.innerHTML = cuts.map(r => {
    const dark = r.nodes.filter(id => {
      const n = nodeState.get(id);
      return n && n.status === 5;
    }).length;
    const collapsed = dark > 1
      ? `${dark} alarms &rarr; 1 incident &middot; ${dark - 1} crews saved`
      : 'ring unprotected &middot; rerouting';
    return `<div class="inc" data-lat="${r.cut.lat}" data-lon="${r.cut.lon}">
      <div class="inc-hd">
        <span class="inc-kind">FIBER CUT</span>
        <span class="inc-count">${dark} nodes</span>
      </div>
      <div class="inc-why">${r.cut.seg} &middot; ${r.cut.cause} &middot; ring ${r.id}</div>
      <div class="inc-collapse">${collapsed}</div>
    </div>`;
  }).join('');
  box.querySelectorAll('.inc').forEach(el => {
    el.onclick = () => {
      if (!mapOk) return;
      map.flyTo(
        [parseFloat(el.dataset.lat), parseFloat(el.dataset.lon)], 14,
        { duration: 0.8 });
    };
  });
}

/* ------------------------------------------------------------ teams */
function upsertTeam(t) {
  if (!mapOk) return;
  let m = vehs.get(t.id);
  const st = t.state || 'IDLE';
  const cls = st === 'REPAIRING' ? 'veh repairing'
            : st === 'STANDBY' ? 'veh standby'
            : 'veh';
  if (!m) {
    m = L.marker([t.lat, t.lon], {
      // className on the WRAPPER is what Leaflet actually moves — the CSS
      // transition on .veh-wrap is what makes cars glide instead of jump
      icon: L.divIcon({ className: 'veh-wrap',
                        html: `<div class="${cls}"><i></i><i></i></div>`,
                        iconSize: [22, 14], iconAnchor: [11, 10] }),
      zIndexOffset: 900, interactive: false
    }).addTo(map);
    vehs.set(t.id, m);
    m._cls = cls;
  }
  m.setLatLng([t.lat, t.lon]);          // .veh-wrap transition glides it
  if (m._cls !== cls) {
    const el = m.getElement();
    if (el) {
      const inner = el.querySelector('.veh');
      if (inner) { inner.className = cls; m._cls = cls; }
    }
  }
  const el = m.getElement();
  if (el) el.style.opacity = t.available ? '0.35' : '1';
}

/* ------------------------------------------------------------ panels */
function renderKPIs(k) {
  setTxt('m-time', k.sim_time);
  setTxt('m-avail', k.availability.toFixed(1) + '%');
  setTxt('m-healthy', `${k.healthy}/${CFG.num_nodes}`);
  setTxt('m-faults', k.congestion + k.overheat + k.rf + k.power + k.backhaul);
  setTxt('m-teams', `${k.active_teams}/${CFG.num_teams}`);
  setTxt('m-mttr', k.mttr_min ? k.mttr_min.toFixed(0) + 'm' : '—');
  const av = document.getElementById('m-avail');
  av.style.color = k.availability >= 98 ? 'var(--green)'
                 : k.availability >= 95 ? 'var(--amber)' : 'var(--red)';
  const rows = [[0, k.healthy], [1, k.congestion], [2, k.overheat],
                [3, k.rf], [4, k.power], [5, k.backhaul]];
  document.getElementById('status-bars').innerHTML = rows.map(([s, c]) =>
    `<div class="sbar">
       <div class="dot" style="background:${CFG.status_colors[s]}"></div>
       <div class="nm">${CFG.status_names[s]}</div>
       <div class="ct" style="color:${c ? CFG.status_colors[s] : 'var(--faint)'}">${c}</div>
     </div>`).join('');
}

function renderAggs(aggs) {
  if (!aggs) return;
  document.getElementById('agg-list').innerHTML = aggs.map(a => {
    const col = a.health >= 98 ? 'var(--green)'
              : a.health >= 92 ? 'var(--amber)' : 'var(--red)';
    const wx = a.weather === 'Clear' ? '' :
      `<span class="agg-w">${a.weather.toUpperCase()} ${a.wind}km/h</span>`;
    return `<div class="agg">
      <div class="agg-top">
        <span class="agg-nm" style="color:${a.color}">${a.name}</span>
        ${wx}<span class="ct" style="color:${col}">${a.health}%</span>
      </div>
      <div class="agg-track">
        <div class="agg-fill" style="width:${a.health}%;background:${col}"></div>
      </div></div>`;
  }).join('');
}

function renderTeams(teams) {
  if (!teams) return;
  const col = { IDLE: 'var(--faint)', EN_ROUTE: 'var(--cyan)',
                STANDBY: 'var(--amber)', REPAIRING: 'var(--orange)',
                RETURNING: 'var(--dim)' };
  const lbl = { IDLE: 'READY', EN_ROUTE: 'EN ROUTE', STANDBY: 'HOLDING',
                REPAIRING: 'REPAIRING', RETURNING: 'RETURNING' };
  document.getElementById('team-list').innerHTML = teams.map(t =>
    `<div class="team">
       <div class="tdot" style="background:${col[t.state]}"></div>
       <div class="tnm">${t.name}</div>
       <div class="tsk">${t.skill}</div>
       <div class="tst" style="color:${col[t.state]}">
         ${lbl[t.state] || t.state.replace('_', ' ')}
         ${t.eta ? ' ' + t.eta + 't' : ''}
       </div>
     </div>`).join('');
}

function renderInspector() {
  const box = document.getElementById('inspector');
  if (!selected || !nodeState.has(selected)) {
    box.className = 'empty';
    box.innerHTML = 'Select a node on the map';
    return;
  }
  const n = nodeState.get(selected);
  const c = CFG.status_colors[n.status];
  const th = CFG.thresholds;
  const gen = ['Legacy', 'Standard', 'Modernised'][n.gen];
  const agg = CFG.agg_sites[n.agg];
  const cls = (v, bad, warn, lower) => {
    const b = lower ? v < bad : v > bad;
    const w = lower ? v < warn : v > warn;
    return b ? 'bad' : w ? 'warn' : 'ok';
  };
  box.className = '';
  box.innerHTML = `
    <div class="ins-hd">
      <span class="ins-id">${n.id}</span>
      <span class="ins-badge" style="background:${c}22;color:${c}">
        ${CFG.status_names[n.status].toUpperCase()}</span>
    </div>
    <div class="ins-tags">
      <span class="tag">${agg.name}</span>
      <span class="tag">${gen}</span>
      <span class="tag">Ring ${n.ring}</span>
      ${n.critical ? '<span class="tag crit">⚠ CRITICAL SITE</span>' : ''}
      ${n.dispatched ? '<span class="tag">CREW EN ROUTE</span>' : ''}
      ${n.repairing ? '<span class="tag">UNDER REPAIR</span>' : ''}
    </div>
    <div class="ins-sec"><h4>RADIO</h4><div class="ins-grid">
      ${mrow('RSRP', n.rsrp + ' dBm', cls(n.rsrp, th.rsrp, th.rsrp + 8, true))}
      ${mrow('SINR', n.sinr + ' dB', cls(n.sinr, 5, 10, true))}
      ${mrow('S11', n.s11 + ' dB', cls(n.s11, th.s11, th.s11 - 4, false))}
      ${mrow('Throughput', n.throughput + ' Mb', cls(n.throughput, 20, 60, true))}
      ${mrow('Latency', n.latency + ' ms', cls(n.latency, 90, 50, false))}
      ${mrow('Loss', n.loss + ' %', cls(n.loss, th.packet_loss, 5, false))}
    </div></div>
    <div class="ins-sec"><h4>HARDWARE</h4><div class="ins-grid">
      ${mrow('Temp', n.temp + ' °C', cls(n.temp, th.temp, th.temp - 10, false))}
      ${mrow('CPU', n.cpu + ' %', cls(n.cpu, th.cpu, 75, false))}
      ${mrow('Dust', (n.dust * 100).toFixed(0) + ' %', cls(n.dust, .6, .3, false))}
      ${mrow('Jitter', n.jitter + ' ms', cls(n.jitter, 7, 4, false))}
    </div></div>
    <div class="ins-sec"><h4>POWER</h4><div class="ins-grid">
      ${mrow('Source', n.power, n.power === 'Grid' ? 'ok' : 'warn')}
      ${mrow('Voltage', n.voltage + ' V', cls(n.voltage, 11.2, 11.8, true))}
      ${mrow('Battery', n.battery + ' %', cls(n.battery, 20, 50, true))}
    </div></div>
    ${n.status === 0 ? `
    <div class="ins-sec"><h4>INJECT FAULT (demo)</h4><div class="inject-btns">
      <button class="inj" data-kind="1">Congestion</button>
      <button class="inj" data-kind="2">Overheat</button>
      <button class="inj" data-kind="3">RF</button>
      <button class="inj" data-kind="4">Power</button>
    </div></div>` : ''}`;
  box.querySelectorAll('.inj').forEach(b => {
    b.onclick = async () => {
      await fetch(`/api/control/inject?node_id=${n.id}&kind=${b.dataset.kind}`,
                  { method: 'POST' });
    };
  });
}

const mrow = (k, v, c = '') =>
  `<div class="mrow"><span class="k">${k}</span><span class="v ${c}">${v}</span></div>`;

/* Set a header/panel text node only when the value actually changed.
 * Called by renderKPIs; without this the dashboard died on first paint
 * with "setTxt is not defined" and every panel stayed empty. */
function setTxt(id, v) {
  const el = document.getElementById(id);
  if (el && el.textContent !== String(v)) el.textContent = v;
}

function appendLogs(logs) {
  if (!logs || !logs.length) return;
  const box = document.getElementById('log');
  const seen = box._last || 0;
  logs.filter(l => l.tick > seen).forEach(l => {
    const div = document.createElement('div');
    div.className = 'ln ' + l.severity;
    div.innerHTML = `<span class="t">${l.time}</span><span class="m">${l.message}</span>`;
    box.appendChild(div);
  });
  box._last = logs[logs.length - 1].tick;
  while (box.children.length > 120) box.removeChild(box.firstChild);
  box.scrollTop = box.scrollHeight;
}

/* ------------------------------------------------------------ Commander (M6) */
function renderAI(ai) {
  if (!ai) return;
  const box = document.getElementById('ai-panel');
  if (!box) return;
  const be = CFG.break_even_precision || 0.4375;
  const prec = ai.false_dispatches + ai.pre_empted > 0
    ? ai.pre_empted / (ai.pre_empted + ai.false_dispatches) * 100 : null;
  const modeCls = ai.ai_mode === 'rules' ? 'rules'
                : ai.ai_enabled ? '' : 'off';
  const modeTxt = ai.ai_mode === 'rules' ? 'RULES MODE'
                : ai.ai_enabled ? 'AI ON' : 'AI OFF';
  box.innerHTML = `
    <div class="ins-hd">
      <span style="font-size:9.5px;letter-spacing:1.3px;color:var(--dim);font-weight:700">
        AI PERFORMANCE</span>
      <span class="ai-mode ${modeCls}">${modeTxt}</span>
    </div>
    <div class="pending-cta" style="margin-bottom:8px">
      <button class="pbtn approve" id="ai-toggle">
        ${ai.ai_enabled ? 'DISABLE AI' : 'ENABLE AI'}</button>
      <button class="pbtn" id="ai-auto">AUTO-APPROVE 10s</button>
    </div>
    <div class="ai-grid">
      <span class="ai-k">PRE-EMPTED (24h)</span><span class="ai-v cyan">${ai.pre_empted}</span>
      <span class="ai-k">FALSE DISPATCHES</span>
      <span class="ai-v ${ai.false_dispatches ? 'bad' : 'ok'}">${ai.false_dispatches}</span>
      <span class="ai-k">PRECISION</span>
      <span class="ai-v ${prec === null ? '' : prec >= be * 100 ? 'ok' : 'bad'}">
        ${prec === null ? '—' : prec.toFixed(1) + '%'}</span>
      <span class="ai-k">BREAK-EVEN</span><span class="ai-v warn">${(be * 100).toFixed(1)}%</span>
      <span class="ai-k">CREW-HOURS SAVED</span><span class="ai-v">${ai.crew_hours_saved.toFixed(1)}</span>
      <span class="ai-k">UNPREDICTABLE</span><span class="ai-v warn">${ai.unpredictable_pct}%</span>
    </div>
    <div id="pending-list" style="margin-top:8px"></div>`;
  const t = document.getElementById('ai-toggle');
  if (t) t.onclick = async () => {
    await fetch(`/api/control/ai?enabled=${ai.ai_enabled ? 'false' : 'true'}`,
                { method: 'POST' });
  };
  const a = document.getElementById('ai-auto');
  if (a) a.onclick = async () => {
    await fetch('/api/control/ai?enabled=true&auto_approve_seconds=10',
                { method: 'POST' });
    a.textContent = 'AUTO-APPROVE: 10s ON';
    a.classList.add('approve');
  };
  renderPending(ai.pending);
}

function renderPending(pending) {
  const box = document.getElementById('pending-list');
  if (!box) return;
  if (!pending || !pending.length) { box.innerHTML = ''; return; }
  box.innerHTML = pending.map(a => `
    <div class="pending" data-id="${a.action_id}">
      <div class="inc-hd">
        <span class="inc-kind">${a.tier === 2 ? 'CREW PRE-DISPATCH' : 'AUTO'}</span>
        <span class="inc-count">${(a.probability * 100).toFixed(0)}%</span>
      </div>
      <div class="inc-why">${a.node} · ${a.label} · ${a.eta}s left</div>
      ${a.tier === 2 ? `
      <div class="pending-cta">
        <button class="pbtn approve">APPROVE</button>
        <button class="pbtn veto">VETO</button>
      </div>` : ''}
    </div>`).join('');
  box.querySelectorAll('.pbtn.approve').forEach(b => {
    b.onclick = async () => {
      const id = b.closest('.pending').dataset.id;
      await fetch(`/api/control/approve/${id}`, { method: 'POST' });
      b.closest('.pending').remove();
    };
  });
  box.querySelectorAll('.pbtn.veto').forEach(b => {
    b.onclick = async () => {
      const id = b.closest('.pending').dataset.id;
      await fetch(`/api/control/veto/${id}`, { method: 'POST' });
      b.closest('.pending').remove();
    };
  });
}

/* ------------------------------------------------------------ controls */
function wireControls() {
  const pb = document.getElementById('btn-pause');
  let paused = false;
  pb.onclick = async () => {
    paused = !paused;
    await fetch(`/api/control/${paused ? 'pause' : 'resume'}`, { method: 'POST' });
    pb.textContent = paused ? '▶' : '❚❚';
    pb.classList.toggle('on', paused);
  };

  document.querySelectorAll('.spd').forEach(b => {
    b.onclick = async () => {
      document.querySelectorAll('.spd').forEach(x => x.classList.remove('on'));
      b.classList.add('on');
      await fetch(`/api/control/speed?value=${b.dataset.speed}`, { method: 'POST' });
    };
  });
  document.querySelector('.spd').classList.add('on');

  const cb = document.getElementById('btn-cut');
  let ringIdx = 5;
  cb.onclick = async () => {
    cb.disabled = true;
    cb.textContent = '✂ CUTTING...';
    try {
      const r = await fetch(
        `/api/control/cut-fiber?ring_id=${ringIdx}&isolate=true`,
        { method: 'POST' });
      const j = await r.json();
      ringIdx = (ringIdx + 3) % 10;
      cb.textContent = j.isolated
        ? `✂ ${j.nodes_dark} DARK` : '✂ REROUTED';
    } catch (e) {
      cb.textContent = '✂ FAILED';
    }
    setTimeout(() => { cb.disabled = false; cb.textContent = '✂ CUT FIBER'; },
               3500);
  };

  document.addEventListener('keydown', e => {
    if (e.code === 'Space') { e.preventDefault(); pb.click(); }
    if (e.code === 'Escape') { selected = null; renderInspector(); }
  });
}

boot();
