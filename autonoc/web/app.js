/* =====================================================================
   AutoNOC v3 frontend — renders, never computes (I6).
   Every name / colour / threshold / gauge band arrives from /api/config.

   MOTION SYSTEM (docs/DESIGN_VISION.md):
     • one master requestAnimationFrame clock; polls only move TARGETS
     • every rendered quantity is a delta-time spring scalar (the same
       integrator Framer Motion uses) => no snapping between polls
     • sparklines / area charts are time-parameterised sliding windows:
       samples carry birth-times, the line scrolls every frame
     • FM feed reorders with FLIP (measure once, animate transforms)
     • hot paths write transforms / attributes / text only
   ===================================================================== */
'use strict';

/* ------------------------------------------------------------ globals */
let CFG = null, map = null, mapOk = false, canvas = null, svgRen = null;
let selected = null, lastTick = 0, failures = 0, paused = false;
let simSpeed = 1, pollTimer = null, cutCycle = 0;

const nodeState = new Map();          // id -> latest node payload
const dots = new Map(), halos = new Map(), pads = new Map();
const rips = new Map();               // id -> radar/sonar DOM marker
const vehs = new Map(), ringLines = new Map(), particles = [];
const districtRows = new Map();       // agg id -> row DOM refs

/* ------------------------------------------------------------ motion */
function Spring(v, k = 120, c = 17) { return { v, t: v, vel: 0, k, c }; }
function stepSpring(s, dt) {
  s.vel += (-s.k * (s.v - s.t) - s.c * s.vel) * dt;
  s.v += s.vel * dt;
}
/* sliding window: samples keep their birth time so the polyline scrolls
   continuously; the live head is a spring so new polls never snap */
function Series(seed, span = 16) {
  const s = { buf: [], head: Spring(seed), span };
  for (let i = 40; i > 0; i--)
    s.buf.push({ t: -i * 0.9, v: seed });
  return s;
}
function pushSample(s, now) {
  s.buf.push({ t: now, v: s.head.v });
  if (s.buf.length > 260) s.buf.shift();
}
function sparkPath(s, now, w, h, lo, hi) {
  const pts = [];
  for (const p of s.buf) {
    const x = w - ((now - p.t) / s.span) * w;
    if (x < -4) continue;
    const y = h - 3 - ((p.v - lo) / (hi - lo)) * (h - 6);
    pts.push(x.toFixed(2) + ' ' + y.toFixed(2));
  }
  pts.push(w.toFixed(2) + ' ' +
    (h - 3 - ((s.head.v - lo) / (hi - lo)) * (h - 6)).toFixed(2));
  return 'M' + pts.join(' L');
}

/* rendered state — targets come from the API, values from the springs */
const st = {
  avail: Spring(98), prec: Spring(0), alarms: Spring(0), pre: Spring(0),
  pwr: Spring(0), sites: Spring(0), risk: Spring(0),
  thrA: Series(0, 20), thrB: Series(0, 20),
  sAvail: Series(98), sPrec: Series(0), sAlarms: Series(0),
  sPre: Series(0), sPwr: Series(0), sSites: Series(0),
  mix: [Spring(300), Spring(0), Spring(0), Spring(0)],
  stats: { ats: 0, theft: 0, alt: 0, warn: 0, crit: 0 },
};

const $ = id => document.getElementById(id);
const setTxt = (id, txt) => {
  const e = $(id);
  if (e && e.__v !== txt) { e.__v = txt; e.textContent = txt; }
};
function onScreenError(msg) {
  const b = $('booterr');
  b.classList.remove('hidden');
  b.textContent = '⚠ ' + msg;
}

/* ------------------------------------------------------------ polling */
/* client tracks the sim speed: faster sim => faster polls AND a shorter
   vehicle-glide transition, so motion stays smooth at every cadence */
function pollInterval() { return Math.max(300, Math.min(2000, 1000 / simSpeed)); }
function schedulePoll() { pollTimer = setTimeout(async () => { await poll(); schedulePoll(); }, pollInterval()); }
function applySpeed(v) {
  simSpeed = v;
  document.documentElement.style.setProperty('--veh-glide', pollInterval() + 'ms');
}

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
  const el = $('conn');
  el.className = 'conn ' + (up ? 'live' : 'down');
  el.querySelector('span').textContent = up ? 'LIVE' : 'RECONNECT';
}

function applyFull(d) {
  d.nodes.forEach(n => { nodeState.set(n.id, n); upsertNode(n); });
  drawRings(d.rings);
  d.teams.forEach(upsertTeam);
  $('feed').innerHTML = '';
  d.logs.slice(-14).forEach(l => feedItem(l, true));
  absorb(d);
  renderInspector();
  if (d.ai) renderAI(d.ai);
}
function applyDelta(d) {
  d.nodes.forEach(n => { nodeState.set(n.id, n); upsertNode(n); });
  d.teams.forEach(upsertTeam);
  drawRings(d.rings);
  d.logs.forEach(l => feedItem(l, false));
  absorb(d);
  if (d.ai) renderAI(d.ai);
  if (selected && d.nodes.some(n => n.id === selected)) renderInspector();
}

/* polls move TARGETS only — the master loop renders them */
function absorb(d) {
  const k = d.kpis, ai = d.ai || {};
  const alarms = (k.congestion || 0) + (k.overheat || 0) + (k.rf || 0)
               + (k.power || 0) + (k.backhaul || 0);
  st.avail.t = k.availability;
  st.sites.t = k.healthy;
  st.alarms.t = alarms;
  st.pre.t = ai.pre_empted || 0;
  st.pwr.t = (k.ats_failures || 0) + (k.fuel_thefts || 0);
  st.prec.t = ai.precision != null ? ai.precision : st.prec.t;
  st.stats.ats = k.ats_failures || 0;
  st.stats.theft = k.fuel_thefts || 0;

  /* display-only aggregates over the node map (rendering, not logic) */
  let warn = 0, alt = 0, thrOk = 0, thrBad = 0, crit = 0;
  nodeState.forEach(n => {
    if (n.warn && n.status === 0) warn++;
    if (n.power && n.power !== 'Grid') alt++;
    if (n.status === 4 || n.status === 5) crit++;   // X.733 CRITICAL kinds
    if (n.status === 0) thrOk += n.throughput || 0;
    else thrBad += n.throughput || 0;
  });
  st.stats.warn = warn; st.stats.alt = alt; st.stats.crit = crit;
  st.thrA.head.t = thrOk / 1000;
  st.thrB.head.t = thrBad / 1000;
  st.mix[0].t = Math.max(0, k.healthy - warn);
  st.mix[1].t = warn;
  st.mix[2].t = alarms - (k.backhaul || 0);
  st.mix[3].t = k.backhaul || 0;
  st.risk.t = Math.min(100, st.stats.ats * 18 + st.stats.theft * 12
                        + alt * 1.1 + (k.power || 0) * 6);

  setTxt('clock', k.sim_time);
  setTxt('d-avail', 'SLA 98.0%');
  setTxt('d-prec', 'break-even p* ' + (CFG.break_even_precision || 0.4375));
  setTxt('d-alarms', 'critical ' + st.stats.crit);
  setTxt('d-pwr', 'ATS ' + st.stats.ats + ' · theft ' + st.stats.theft);
  setTxt('d-sites', (k.healthy / (CFG.num_nodes || 300) * 100).toFixed(1) + '%');
  setTxt('d-pre', 'PdM rApp lead ≈ 45 min');

  /* districts */
  (d.agg || []).forEach(a => {
    let row = districtRows.get(a.id);
    if (!row) row = makeDistrictRow(a);
    row.h.t = a.health;
    if (row.pc.__v !== a.health + '%') { row.pc.__v = a.health + '%'; row.pc.textContent = a.health + '%'; }
    const col = a.health >= 98 ? 'var(--green)' : a.health >= 92 ? 'var(--amber)' : 'var(--red)';
    row.bar.style.background = col;
    const wx = a.weather && a.weather !== 'Clear'
      ? a.weather.toUpperCase() + ' ' + a.wind + 'km/h' : 'clear';
    if (row.wx.__v !== wx) { row.wx.__v = wx; row.wx.textContent = wx; }
  });
}

/* ------------------------------------------------------------ FM feed */
const SEV_ICON = { CRITICAL: '✖', MAJOR: '⚠', MINOR: '△', WARNING: '◆', INFO: 'ℹ', CLEARED: '✔' };
function feedItem(l, silent) {
  const feed = $('feed');
  const sev = (l.severity in SEV_ICON) ? l.severity : 'INFO';
  const el = document.createElement('div');
  el.className = 'al ' + sev;
  el.innerHTML =
    `<div class="sic">${SEV_ICON[sev]}</div>` +
    `<div class="tx"><div class="t1">${l.message}</div>` +
    `<div class="t2">tick ${l.tick}</div>` +
    `<span class="sv">${sev}</span></div>` +
    `<div class="rt mono">${l.time}</div>`;
  /* FLIP: measure siblings once, then animate the displacement */
  const before = silent ? [] : [...feed.children].map(c => c.getBoundingClientRect().top);
  feed.prepend(el);
  if (!silent) {
    el.animate([{ opacity: 0, transform: 'translateY(-12px) scale(.97)' },
                { opacity: 1, transform: 'none' }],
               { duration: 460, easing: 'cubic-bezier(.2,1.2,.3,1)' });
    [...feed.children].slice(1).forEach((c, i) => {
      const dy = (before[i] || 0) - c.getBoundingClientRect().top;
      if (dy) c.animate([{ transform: `translateY(${dy}px)` }, { transform: 'none' }],
                        { duration: 440, easing: 'cubic-bezier(.2,1.1,.3,1)' });
    });
  }
  while (feed.children.length > 26) feed.lastChild.remove();
  setTxt('feed-count', feed.children.length + ' events');
}

/* ------------------------------------------------------------ districts */
function makeDistrictRow(a) {
  const el = document.createElement('div');
  el.className = 'drow';
  el.innerHTML =
    `<span class="nm">${a.name}</span>` +
    `<span class="pwr ${a.pwr || 'A'}" title="${(CFG.power_configs || {})[a.pwr] || ''}">${a.pwr || 'A'}</span>` +
    `<span class="wx"></span>` +
    `<span class="bar"><i></i></span><span class="pc">—</span>`;
  $('districts').appendChild(el);
  const row = { h: Spring(a.health), bar: el.querySelector('.bar i'),
                pc: el.querySelector('.pc'), wx: el.querySelector('.wx') };
  districtRows.set(a.id, row);
  return row;
}

/* ------------------------------------------------------------ map */
function initMap() {
  try {
    map = L.map('map', { zoomControl: false, preferCanvas: true })
          .setView([35.5613, 45.4309], 12.6);
    canvas = L.canvas({ padding: .4 });
    svgRen = L.svg({ padding: .4 });
    /* CartoDB Dark Matter: charcoal basemap so the neon layer reads */
    L.tileLayer('https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png', {
      maxZoom: 19, subdomains: 'abcd',
      attribution: '&copy; <a href="https://openstreetmap.org">OpenStreetMap</a> &copy; <a href="https://carto.com/attributions">CARTO</a>'
    }).on('load', () => { $('mapfade').style.opacity = 0; }).addTo(map);
    setTimeout(() => { $('mapfade').style.opacity = 0; }, 2600);
    map.on('click', () => closeDrawer());
    mapOk = true;
  } catch (e) { onScreenError('map init failed: ' + e); }
}

function upsertNode(n) {
  if (!mapOk) return;
  const colour = CFG.status_colors[n.status];
  const healthy = n.status === 0;

  let dot = dots.get(n.id);
  if (!dot) {
    halos.set(n.id, L.circleMarker([n.lat, n.lon], {
      renderer: canvas, radius: 11, fillColor: colour, color: null,
      weight: 0, fillOpacity: .13, interactive: false }).addTo(map));
    dot = L.circleMarker([n.lat, n.lon], {
      renderer: canvas, radius: 5.5, fillColor: colour, color: '#fff',
      weight: 1.2, opacity: .8, fillOpacity: .95, interactive: false }).addTo(map);
    dots.set(n.id, dot);
    const pad = L.circleMarker([n.lat, n.lon], {
      renderer: canvas, radius: 14, opacity: 0, fillOpacity: 0,
      interactive: true, bubblingMouseEvents: false }).addTo(map);
    pad.on('click', ev => {
      L.DomEvent.stopPropagation(ev);
      selected = pickNearest(ev.latlng);
      openDrawer('ins');
      renderInspector();
    });
    pad.bindTooltip(() => tipFor(n.id), { direction: 'top', offset: [0, -8] });
    pads.set(n.id, pad);
    dot._st = -1; dot._warn = null;
  }

  if (dot._st !== n.status) {
    dot.setStyle({ fillColor: colour, radius: healthy ? 5.5 : 8 });
    const halo = halos.get(n.id);
    if (halo) halo.setStyle({ fillColor: colour });
    dot._st = n.status;
  }

  /* radar ripple (fault) / sonar ping (PdM warn) — DOM markers, few at a time */
  const key = !healthy ? 'fault' : (n.warn ? 'warn' : null);
  if (dot._warn !== key) {
    const old = rips.get(n.id);
    if (old) { map.removeLayer(old); rips.delete(n.id); }
    if (key) {
      rips.set(n.id, L.marker([n.lat, n.lon], {
        icon: L.divIcon({ className: '', iconSize: [12, 12], iconAnchor: [6, 6],
          html: `<div class="tw ${key}" style="--c:${colour}"><i></i></div>` }),
        interactive: false, zIndexOffset: key === 'fault' ? 400 : 350 }).addTo(map));
    }
    dot._warn = key;
  } else if (key) {
    const el = rips.get(n.id) && rips.get(n.id).getElement();
    if (el) el.firstChild.style.setProperty('--c', colour);
  }
}

function tipFor(id) {
  const n = nodeState.get(id);
  if (!n) return id;
  return `<b>${n.id}</b><br>${CFG.status_names[n.status]}<br>`
       + `RSRP ${n.rsrp} dBm · VSWR ${n.vswr} · PRB ${n.prb}% · ${n.temp}°C`;
}
function pickNearest(latlng) {
  let best = null, bd = 1e9;
  nodeState.forEach(n => {
    const d = (n.lat - latlng.lat) ** 2 + (n.lon - latlng.lng) ** 2;
    if (d < bd) { bd = d; best = n.id; }
  });
  return best;
}

/* fiber rings: SVG light-tubes + particles riding the drawn path */
function drawRings(rings) {
  if (!rings || !mapOk) return;
  rings.forEach(r => {
    let line = ringLines.get(r.id);
    const cut = !!r.cut;
    if (!line) {
      line = L.polyline(r.path, { renderer: svgRen, className: 'fiber-line',
                                  interactive: false }).addTo(map);
      ringLines.set(r.id, line);
      line._cut = false; line._parts = false;
    }
    if (line._cut !== cut) {
      const el = line.getElement();
      if (el) el.setAttribute('class', cut ? 'fiber-cut' : 'fiber-line');
      line._cut = cut;
    }
    if (!line._parts) {
      const path = line.getElement();
      if (path && path.ownerSVGElement) {
        line._parts = true;
        for (let k = 0; k < 5; k++) {
          const c = document.createElementNS('http://www.w3.org/2000/svg', 'circle');
          c.setAttribute('r', 2); c.setAttribute('class', 'particle');
          path.ownerSVGElement.appendChild(c);
          particles.push({ ring: r.id, el: c, t: k / 5, sp: .00042 + (k % 3) * .00006 });
        }
      }
    }
    /* cut markers */
    if (cut && !line._mk) {
      const mid = r.path[Math.floor(r.path.length / 2)];
      line._mk = L.marker(mid, { interactive: false, zIndexOffset: 600,
        icon: L.divIcon({ className: '', iconSize: [12, 12], iconAnchor: [6, 6],
                          html: '<div class="cutm"></div>' }) }).addTo(map);
    } else if (!cut && line._mk) { map.removeLayer(line._mk); line._mk = null; }
  });
}

/* crews: Leaflet translates the wrapper; CSS transition glides it */
function upsertTeam(t) {
  if (!mapOk) return;
  let m = vehs.get(t.id);
  const stt = t.state || 'IDLE';
  const cls = stt === 'REPAIRING' ? 'veh repairing'
            : stt === 'STANDBY' ? 'veh standby' : 'veh';
  if (!m) {
    m = L.marker([t.lat, t.lon], {
      icon: L.divIcon({ className: 'veh-wrap',
                        html: `<div class="${cls}"><i></i><i></i></div>`,
                        iconSize: [20, 12], iconAnchor: [10, 8] }),
      zIndexOffset: 900, interactive: false }).addTo(map);
    vehs.set(t.id, m);
    m._cls = cls;
  }
  m.setLatLng([t.lat, t.lon]);
  if (m._cls !== cls) {
    const el = m.getElement();
    if (el) el.firstChild.className = cls;
    m._cls = cls;
  }
}

/* ------------------------------------------------------------ drawer */
function openDrawer(tab) {
  $('drawer').classList.add('on');
  $('scrim').classList.add('on');
  switchTab(tab || 'ins');
}
function closeDrawer() {
  $('drawer').classList.remove('on');
  $('scrim').classList.remove('on');
}
function switchTab(tab) {
  document.querySelectorAll('.dtab[data-tab]').forEach(b =>
    b.classList.toggle('on', b.dataset.tab === tab));
  $('d-ins').classList.toggle('hidden', tab !== 'ins');
  $('d-ai').classList.toggle('hidden', tab !== 'ai');
}

/* gauge rows: specs + labels served by /api/config (I5) */
function gaugeCls(g, v) {
  if (g.lower_bad) return v < g.bad ? 'bad' : v < g.warn ? 'warn' : 'ok';
  return v > g.bad ? 'bad' : v > g.warn ? 'warn' : 'ok';
}
const mrow = (k, v, c = '') =>
  `<div class="mrow"><span class="k">${k}</span><span class="v ${c}">${v}</span></div>`;
function grow(key, v, vText) {
  const lab = (CFG.metric_labels || {})[key] || key.toUpperCase();
  const g = (CFG.gauges || {})[key];
  if (!g) return mrow(lab, vText, '');
  const cls = gaugeCls(g, v);
  const pct = Math.max(2, Math.min(100, (v - g.lo) / (g.hi - g.lo) * 100));
  return `<div class="mrow"><span class="k">${lab}</span>`
       + `<span class="gauge"><i class="${cls}" style="width:${pct.toFixed(0)}%"></i></span>`
       + `<span class="v ${cls}">${vText}</span></div>`;
}

function renderInspector() {
  const box = $('d-ins');
  if (!selected || !nodeState.has(selected)) {
    box.innerHTML = '<div class="empty">Select a node on the map</div>';
    return;
  }
  const n = nodeState.get(selected);
  const c = CFG.status_colors[n.status];
  const gen = ['Legacy', 'Standard', 'Modernised'][n.gen];
  const agg = CFG.agg_sites[n.agg];
  const pwrName = (CFG.power_configs || {})[n.pwr] || '';
  box.innerHTML = `
    <div class="ins-hd">
      <span class="ins-id">${n.id}</span>
      <span class="ins-badge" style="background:${c}22;color:${c}">
        ${CFG.status_names[n.status].toUpperCase()}</span>
    </div>
    <div class="ins-tags">
      <span class="tag">${agg ? agg.name : n.agg}</span>
      <span class="tag">${gen}</span>
      <span class="tag">Ring ${n.ring}</span>
      <span class="tag pwr" title="${pwrName}">PWR TYPE ${n.pwr}</span>
      ${n.critical ? '<span class="tag crit">⚠ CRITICAL SITE</span>' : ''}
      ${n.warn ? '<span class="tag warn">◉ PdM rApp WARNING</span>' : ''}
      ${n.ats ? '<span class="tag ats">⚡ ATS FAIL TO CRANK</span>' : ''}
      ${n.dispatched ? '<span class="tag">CREW EN ROUTE</span>' : ''}
      ${n.repairing ? '<span class="tag">UNDER REPAIR</span>' : ''}
    </div>
    <div class="ins-sec"><h4>RADIO — 3GPP PM COUNTERS</h4><div class="ins-grid">
      ${grow('rsrp', n.rsrp, n.rsrp + ' dBm')}
      ${grow('sinr', n.sinr, n.sinr + ' dB')}
      ${grow('cqi', n.cqi, n.cqi + ' / 15')}
      ${grow('vswr', n.vswr, n.vswr.toFixed(2) + ' : 1')}
      ${grow('prb', n.prb, n.prb.toFixed(0) + ' %')}
      ${grow('throughput', n.throughput, n.throughput + ' Mb')}
      ${grow('loss', n.loss, n.loss + ' %')}
      ${grow('latency', n.latency, n.latency + ' ms')}
    </div></div>
    <div class="ins-sec"><h4>HARDWARE</h4><div class="ins-grid">
      ${grow('temp', n.temp, n.temp + ' °C')}
      ${grow('cpu', n.cpu, n.cpu + ' %')}
      ${grow('dust', n.dust, (n.dust * 100).toFixed(0) + ' %')}
      ${grow('jitter', n.jitter, n.jitter + ' ms')}
      ${grow('s11', n.s11, n.s11 + ' dB')}
    </div></div>
    <div class="ins-sec"><h4>SITE POWER — TYPE ${n.pwr} · ${pwrName.toUpperCase()}</h4><div class="ins-grid">
      ${mrow('Power Source', n.power, n.power === 'Grid' ? 'ok' : 'warn')}
      ${grow('voltage', n.voltage, n.voltage + ' V')}
      ${grow('battery', n.battery, n.battery + ' %')}
      ${grow('fuel', n.fuel, n.fuel + ' %')}
      ${n.ats ? mrow('ATS', 'FAILED TO CRANK', 'bad') : ''}
    </div></div>
    ${n.status === 0 ? `
    <div class="ins-sec"><h4>INJECT FAULT (demo)</h4><div class="inject-btns">
      <button class="inj" data-kind="1">${CFG.status_names[1]}</button>
      <button class="inj" data-kind="2">${CFG.status_names[2]}</button>
      <button class="inj" data-kind="3">${CFG.status_names[3]}</button>
      <button class="inj" data-kind="4">${CFG.status_names[4]}</button>
    </div></div>` : ''}`;
  box.querySelectorAll('.inj').forEach(b => {
    b.onclick = async () => {
      await fetch(`/api/control/inject?node_id=${n.id}&kind=${b.dataset.kind}`,
                  { method: 'POST' });
    };
  });
}

function renderAI(ai) {
  if (!ai) return;
  const box = $('d-ai');
  const be = CFG.break_even_precision || 0.4375;
  const modeCls = ai.ai_mode === 'rules' ? 'rules' : ai.ai_enabled ? '' : 'off';
  const modeTxt = ai.ai_mode === 'rules' ? 'RULES MODE'
                : ai.ai_enabled ? 'AI ON' : 'AI OFF';
  const roles = CFG.rapp_roles || {};
  const roleLines = ['doctor', 'oracle', 'commander'].filter(k => roles[k])
    .map(k => `<span>▸ ${roles[k]}</span>`).join('');
  const html = `
    <div class="ins-hd">
      <span style="font-size:9px;letter-spacing:.16em;color:var(--faint);font-weight:800">
        rApp PERFORMANCE</span>
      <span class="ai-mode ${modeCls}">${modeTxt}</span>
    </div>
    ${roleLines ? `<div class="rapp-roles">${roleLines}</div>` : ''}
    <div class="pending-cta">
      <button class="pbtn approve" id="ai-toggle">
        ${ai.ai_enabled ? 'DISABLE AI' : 'ENABLE AI'}</button>
      <button class="pbtn" id="ai-auto">AUTO-APPROVE 10s</button>
    </div>
    <div class="ai-grid">
      <span class="cell">PRE-EMPTED<b class="cyan">${ai.pre_empted}</b></span>
      <span class="cell">FALSE DISPATCH<b class="red">${ai.false_dispatches}</b></span>
      <span class="cell">PRECISION<b class="green">
        ${ai.precision == null ? '—' : (ai.precision * 100).toFixed(1) + '%'}</b></span>
      <span class="cell">BREAK-EVEN<b class="blue">${be}</b></span>
      <span class="cell">CREW-H SAVED<b class="green">${(ai.crew_hours_saved || 0).toFixed(1)}</b></span>
      <span class="cell">UNPREDICTABLE<b>${(ai.unpredictable_pct || 0).toFixed(0)}%</b></span>
    </div>
    <div class="ins-sec"><h4>PENDING TIER-2 ACTIONS</h4>
      ${(ai.pending || []).map(p => `
        <div class="pend">
          <div class="pt">${p.node_id} — ${p.label || 'pre-dispatch crew'}</div>
          <div class="ps">p=${(p.probability || 0).toFixed(2)} · tier ${p.tier} · `
            + `ETA ${p.eta != null ? p.eta + 't' : '—'}</div>
          <div class="row">
            <button class="pbtn approve" data-ap="${p.action_id}">APPROVE</button>
            <button class="pbtn" data-ve="${p.action_id}">VETO</button>
          </div>
        </div>`).join('') ||
        '<div class="empty" style="padding-top:8px">queue empty</div>'}
    </div>`;
  /* polls arrive ~1/s: only touch the DOM when the panel actually changed,
     so hover/press states never flicker */
  if (box.__h !== html) { box.__h = html; box.innerHTML = html; }
  $('ai-toggle').onclick = async () => {
    await fetch(`/api/control/ai?enabled=${ai.ai_enabled ? 'false' : 'true'}`,
                { method: 'POST' });
  };
  $('ai-auto').onclick = async () => {
    await fetch('/api/control/ai?enabled=true&auto_approve_seconds=10',
                { method: 'POST' });
  };
  box.querySelectorAll('[data-ap]').forEach(b => b.onclick = async () => {
    await fetch(`/api/control/approve/${b.dataset.ap}`, { method: 'POST' });
  });
  box.querySelectorAll('[data-ve]').forEach(b => b.onclick = async () => {
    await fetch(`/api/control/veto/${b.dataset.ve}`, { method: 'POST' });
  });
  const btn = $('btn-ai');
  btn.classList.toggle('armed', !!ai.ai_enabled);
}

/* ------------------------------------------------------------ controls */
function wireControls() {
  $('btn-pause').onclick = async () => {
    paused = !paused;
    await fetch(`/api/control/${paused ? 'pause' : 'resume'}`, { method: 'POST' });
    $('btn-pause').textContent = paused ? '▶' : '❚❚';
  };
  document.querySelectorAll('.spd').forEach(b => {
    b.onclick = async () => {
      document.querySelectorAll('.spd').forEach(x => x.classList.remove('on'));
      b.classList.add('on');
      await fetch(`/api/control/speed?value=${b.dataset.speed}`, { method: 'POST' });
      applySpeed(parseFloat(b.dataset.speed));
    };
  });
  $('btn-cut').onclick = () => doCut();
  $('btn-ai').onclick = async () => {
    const on = $('btn-ai').classList.contains('armed');
    await fetch(`/api/control/ai?enabled=${on ? 'false' : 'true'}`, { method: 'POST' });
  };
  $('bell').onclick = () => { $('feed').scrollTop = 0; };
  document.querySelectorAll('.dtab[data-tab]').forEach(b =>
    b.onclick = () => switchTab(b.dataset.tab));
  $('dclose').onclick = closeDrawer;
  $('scrim').onclick = closeDrawer;
  document.querySelectorAll('#side .nav').forEach(n => n.onclick = () => navCmd(n));
  wirePalette();
}

function doCut() {
  const ring = selected && nodeState.has(selected)
    ? nodeState.get(selected).ring : (cutCycle % 10);
  cutCycle++;
  fetch(`/api/control/cut-fiber?ring_id=${ring}&isolate=true`, { method: 'POST' });
}

function navCmd(n) {
  document.querySelectorAll('#side .nav').forEach(x => x.classList.remove('on'));
  n.classList.add('on');
  const cmd = n.dataset.cmd;
  if (cmd === 'ai') openDrawer('ai');
  else if (cmd === 'feed') $('alertcard').scrollIntoView({ behavior: 'smooth' });
  else if (cmd === 'map' && mapOk) map.flyTo([35.5613, 45.4309], 12.6, { duration: 1.4 });
  else if (cmd === 'power' || cmd === 'crews' || cmd === 'counter' || cmd === 'policy')
    feedItem({ tick: lastTick, time: 'now', severity: 'INFO',
      message: `“${n.textContent.trim()}” opens in the phase-2 React build` }, false);
}

/* ------------------------------------------------------------ palette */
const COMMANDS = [
  { ic: '✂', t: 'Cut fiber ring (Act 3 demo)', f: doCut },
  { ic: '✦', t: 'Toggle AI (Commander / A1 policy)', f: () => $('btn-ai').click() },
  { ic: '⏱', t: 'Arm auto-approve for 10 s', f: () =>
      fetch('/api/control/ai?enabled=true&auto_approve_seconds=10', { method: 'POST' }) },
  { ic: '❚❚', t: 'Pause / resume simulation', f: () => $('btn-pause').click() },
  { ic: '◉', t: 'Fly to weakest district', f: () => {
      let worst = null;
      districtRows.forEach((r, id) => {
        if (!worst || r.h.v < worst.h.v) worst = id;
      });
      if (worst == null || !mapOk) return;
      let lat = 0, lon = 0, n = 0;
      nodeState.forEach(nd => { if (nd.agg === worst) { lat += nd.lat; lon += nd.lon; n++; } });
      if (n) map.flyTo([lat / n, lon / n], 13.4, { duration: 1.6 });
    } },
  { ic: '⚡', t: 'Speed 4× (demo cadence)', f: () =>
      document.querySelector('.spd[data-speed="4"]').click() },
];
let palSel = 0;
function wirePalette() {
  const scr = $('palscr'), rows = $('palrows'), q = $('palq');
  const open = () => { scr.classList.add('open'); q.value = ''; drawPal(''); q.focus(); };
  const close = () => scr.classList.remove('open');
  function drawPal(filter) {
    const list = COMMANDS.filter(c =>
      c.t.toLowerCase().includes(filter.toLowerCase()));
    palSel = Math.min(palSel, Math.max(0, list.length - 1));
    rows.innerHTML = list.map((c, i) =>
      `<div class="prow ${i === palSel ? 'sel' : ''}" data-i="${i}">
         <span class="ic">${c.ic}</span>${c.t}</div>`).join('') ||
      '<div class="prow">no matching command</div>';
    rows.querySelectorAll('.prow').forEach(r => r.onclick = () => {
      const c = list[+r.dataset.i]; close(); c && c.f();
    });
    rows._list = list;
  }
  $('search').onclick = open;
  q.oninput = () => drawPal(q.value);
  q.onkeydown = e => {
    const list = rows._list || [];
    if (e.key === 'ArrowDown') { palSel = Math.min(list.length - 1, palSel + 1); drawPal(q.value); }
    if (e.key === 'ArrowUp') { palSel = Math.max(0, palSel - 1); drawPal(q.value); }
    if (e.key === 'Enter') { const c = list[palSel]; close(); c && c.f(); }
  };
  addEventListener('keydown', e => {
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') { e.preventDefault(); open(); }
    if (e.key === 'Escape') { close(); }
  });
  scr.onclick = e => { if (e.target === scr) close(); };
}

/* ------------------------------------------------------------ master loop */
let LAST = performance.now(), T = 0, sampleAt = 0;
function loop(nowMs) {
  const dt = Math.min(.05, Math.max(.001, (nowMs - LAST) / 1000));
  LAST = nowMs;
  if (!document.hidden && CFG) {
    T += dt;
    /* springs */
    [st.avail, st.prec, st.alarms, st.pre, st.pwr, st.sites, st.risk,
     st.thrA.head, st.thrB.head, ...st.mix].forEach(s => stepSpring(s, dt));

    /* sample cadence follows the poll cadence; lines scroll every frame */
    if (T >= sampleAt) {
      sampleAt = T + pollInterval() / 1000;
      st.sAvail.head.t = st.avail.v; st.sPrec.head.t = st.prec.v;
      st.sAlarms.head.t = st.alarms.v; st.sPre.head.t = st.pre.v;
      st.sPwr.head.t = st.pwr.v; st.sSites.head.t = st.sites.v;
      [st.sAvail, st.sPrec, st.sAlarms, st.sPre, st.sPwr, st.sSites,
       st.thrA, st.thrB].forEach(s => pushSample(s, T));
    }
    [st.sAvail, st.sPrec, st.sAlarms, st.sPre, st.sPwr, st.sSites]
      .forEach(s => stepSpring(s.head, dt));

    /* KPI numbers (tabular-nums: no reflow wobble) */
    $('n-avail').innerHTML = st.avail.v.toFixed(2) + '<small>%</small>';
    setTxt('n-prec', st.prec.v > 0.01 ? st.prec.v.toFixed(3) : '—');
    setTxt('n-alarms', String(Math.max(0, Math.round(st.alarms.v))));
    setTxt('n-pre', String(Math.max(0, Math.round(st.pre.v))));
    setTxt('n-pwr', String(Math.max(0, Math.round(st.pwr.v))));
    $('n-sites').innerHTML = Math.max(0, Math.round(st.sites.v)) +
      `<small>/${CFG.num_nodes || 300}</small>`;
    setTxt('belldot', String(Math.max(0, Math.round(st.alarms.v))));
    setTxt('navbdg', String(Math.max(0, Math.round(st.alarms.v))));

    /* sparklines */
    $('s-avail').setAttribute('d', sparkPath(st.sAvail, T, 100, 30, 95, 100));
    $('s-prec').setAttribute('d', sparkPath(st.sPrec, T, 100, 30, .85, 1.001));
    $('s-alarms').setAttribute('d', sparkPath(st.sAlarms, T, 100, 30, -1,
      Math.max(12, st.alarms.v * 1.4)));
    $('s-pre').setAttribute('d', sparkPath(st.sPre, T, 100, 30,
      Math.min(0, st.pre.v - 8), Math.max(20, st.pre.v * 1.25)));
    $('s-pwr').setAttribute('d', sparkPath(st.sPwr, T, 100, 30, -.5,
      Math.max(4, st.pwr.v * 1.5)));
    $('s-sites').setAttribute('d', sparkPath(st.sSites, T, 100, 30,
      (CFG.num_nodes || 300) * .92, (CFG.num_nodes || 300) + 2));

    /* throughput area chart (two sliding windows) */
    const hiA = Math.max(4, ...st.thrA.buf.map(p => p.v), st.thrA.head.v) * 1.25;
    const hiB = Math.max(1.5, ...st.thrB.buf.map(p => p.v), st.thrB.head.v) * 1.3;
    const ln = (s, hi) => sparkPath(s, T, 100, 40, 0, hi);
    const ar = (s, hi) => ln(s, hi) + ' L100 40 L0 40 Z';
    $('t-lineA').setAttribute('d', ln(st.thrA, hiA));
    $('t-areaA').setAttribute('d', ar(st.thrA, hiA));
    $('t-lineB').setAttribute('d', ln(st.thrB, hiB));
    $('t-areaB').setAttribute('d', ar(st.thrB, hiB));
    setTxt('t-now', st.thrA.head.v.toFixed(1) + ' Gb/s in service');

    /* district bars: scaleX only (never width) */
    districtRows.forEach(r => {
      stepSpring(r.h, dt);
      r.bar.style.transform = 'scaleX(' + (r.h.v / 100).toFixed(4) + ')';
    });

    /* power-risk arc */
    const risk = Math.max(0, Math.min(100, st.risk.v));
    $('garc').setAttribute('stroke-dashoffset', (226.2 * (1 - risk / 100)).toFixed(1));
    const col = risk < 40 ? 'var(--green)' : risk < 70 ? 'var(--amber)' : 'var(--red)';
    $('garc').style.stroke = col;
    const gv = $('g-val'); gv.textContent = Math.round(risk); gv.style.color = col;
    setTxt('g-ats', String(st.stats.ats));
    setTxt('g-theft', String(st.stats.theft));
    setTxt('g-alt', String(st.stats.alt));

    /* status donut */
    const tot = st.mix.reduce((a, s) => a + s.v, 0) || 1;
    let off = 0;
    st.mix.forEach((s, i) => {
      const frac = Math.max(0, s.v) / tot * 100;
      const el = $('dn' + i);
      el.setAttribute('stroke-dasharray', frac.toFixed(2) + ' ' + (100 - frac).toFixed(2));
      el.setAttribute('stroke-dashoffset', (-off).toFixed(2));
      off += frac;
      setTxt('dl' + i, String(Math.max(0, Math.round(s.v))));
    });
    setTxt('dn-c', String(Math.max(0, Math.round(st.mix[0].v + st.mix[1].v))));

    /* fiber particles ride the drawn SVG paths */
    particles.forEach(p => {
      const line = ringLines.get(p.ring);
      const path = line && line.getElement();
      if (!path || !path.getTotalLength) return;
      if (!line._cut) p.t = (p.t + p.sp * dt * 1000) % 1;
      p.el.classList.toggle('halt', line._cut);
      const pt = path.getPointAtLength(p.t * path.getTotalLength());
      p.el.setAttribute('cx', pt.x);
      p.el.setAttribute('cy', pt.y);
    });
  }
  requestAnimationFrame(loop);
}

/* ------------------------------------------------------------ boot */
async function boot() {
  try {
    CFG = await (await fetch('/api/config')).json();
  } catch (e) { onScreenError('cannot reach /api/config — is the server up?'); return; }
  initMap();
  document.querySelectorAll('.enter').forEach((el, i) =>
    setTimeout(() => el.classList.add('in'), 100 + i * 45));
  try {
    const first = await (await fetch('/api/data')).json();
    applyFull(first);
    lastTick = first.tick;
  } catch (e) { onScreenError('cannot fetch /api/data — ' + e); }
  applySpeed(1);
  wireControls();
  requestAnimationFrame(loop);
  schedulePoll();
}
boot();
