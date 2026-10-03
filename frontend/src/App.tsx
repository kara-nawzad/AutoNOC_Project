import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type CSSProperties,
} from "react";
import { AnimatePresence, motion, MotionConfig } from "framer-motion";
import {
  Activity,
  ArrowUpRight,
  Bell,
  Boxes,
  ChevronRight,
  CircleHelp,
  Clock3,
  Layers3,
  LayoutDashboard,
  Loader2,
  RadioTower,
  Search,
  Settings2,
  ShieldCheck,
  Sparkles,
  Truck,
  Wifi,
  X,
} from "lucide-react";
import { useTelemetry } from "./hooks/useTelemetry";
import { KpiGrid } from "./components/KpiGrid";
import { NetworkMap } from "./components/NetworkMap";
import { AlertsSidebar, type Execute } from "./components/AlertsSidebar";
import { AnalyticsRow } from "./components/AnalyticsRow";
import { Inspector } from "./components/Inspector";
import { SimControls, ScenarioModal } from "./components/SimControls";
import { Badge, Dot, Modal, tone } from "./components/ui";
import { api } from "./services/api";

type Dialog =
  | "cut"
  | "inject"
  | "activity"
  | "fleet"
  | "search"
  | "settings"
  | "about"
  | null;

export default function App() {
  const { config, data, status, error, refresh } = useTelemetry();
  const [selected, setSelected] = useState<string | null>(null);
  const [dialog, setDialog] = useState<Dialog>(null);
  const [injectNode, setInjectNode] = useState<string>();
  const [query, setQuery] = useState("");
  const [busy, setBusy] = useState(false);
  const busyRef = useRef(false);
  const [toast, setToast] = useState<{ text: string; error: boolean } | null>(
    null,
  );
  const [section, setSection] = useState("overview");
  const selectNode = useCallback((id: string) => {
    setSelected(id);
  }, []);
  const closeDialog = useCallback(() => setDialog(null), []);
  useEffect(() => {
    setSelected(null);
  }, [data?.run_id]);
  useEffect(() => {
    const handler = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        setQuery("");
        setDialog("search");
      }
      if (event.key === "Escape") setSelected(null);
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, []);
  useEffect(() => {
    if (toast) {
      const timer = setTimeout(() => setToast(null), 6000);
      return () => clearTimeout(timer);
    }
  }, [toast]);
  const execute: Execute = useCallback(
    async (command, label) => {
      if (busyRef.current) return false;
      busyRef.current = true;
      setBusy(true);
      try {
        const result = await command();
        setToast({
          text: result.late
            ? "Approval arrived after failure; reactive dispatch is handling the site."
            : label,
          error: false,
        });
        refresh();
        return true;
      } catch (err) {
        setToast({
          text:
            err instanceof Error
              ? err.message
              : "Command failed. Please retry.",
          error: true,
        });
        refresh();
        return false;
      } finally {
        busyRef.current = false;
        setBusy(false);
      }
    },
    [refresh],
  );
  function navigate(id: string) {
    setSection(id);
    if (id === "fleet") setDialog("fleet");
    else
      document
        .getElementById(id === "overview" ? "overview" : id)
        ?.scrollIntoView({
          behavior: window.matchMedia("(prefers-reduced-motion: reduce)")
            .matches
            ? "instant"
            : "smooth",
          block: "start",
        });
  }
  if (!config || !data)
    return (
      <div className="boot-screen">
        <div className="brand-mark">
          A<span>N</span>
        </div>
        <h1>
          AutoNOC<span> / NETWORK COMMAND</span>
        </h1>
        <Loader2 className="spin" size={22} />
        <p>{error ?? "Establishing telemetry uplink…"}</p>
        {error && (
          <button className="button secondary" onClick={refresh}>
            Retry connection
          </button>
        )}
        <small>LIVE SIMULATION · NO SYNTHETIC UI DATA</small>
      </div>
    );
  const p = config.presentation.palette;
  const theme = Object.fromEntries(
    Object.entries(p).map(([key, val]) => [`--${key}`, val]),
  ) as CSSProperties;
  const matched = data.nodes
    .filter((n) =>
      `${n.id} ${config.agg_sites.find((a) => a.id === n.agg)?.name}`
        .toLowerCase()
        .includes(query.toLowerCase()),
    )
    .slice(0, 12);
  return (
    <MotionConfig reducedMotion="user">
      <div
        className={`app-shell ${data.control.paused ? "is-paused" : ""}`}
        style={theme}
      >
        <a className="skip-link" href="#overview">
          Skip to network overview
        </a>
        <nav className="navigation-rail" aria-label="Main navigation">
          <button
            className="brand-mark"
            onClick={() => navigate("overview")}
            aria-label="AutoNOC overview"
          >
            A<span>N</span>
          </button>
          <div className="nav-items">
            {[
              { id: "overview", icon: LayoutDashboard, label: "Overview" },
              { id: "network", icon: Layers3, label: "Network topology" },
              { id: "incidents", icon: Bell, label: "Active incidents" },
              { id: "analytics", icon: Activity, label: "Telemetry analytics" },
              { id: "fleet", icon: Truck, label: "Maintenance fleet" },
              { id: "commander", icon: Sparkles, label: "A1 Commander" },
            ].map(({ id, icon: Icon, label }) => (
              <button
                key={id}
                className={`nav-item ${section === id ? "active" : ""}`}
                title={label}
                aria-label={label}
                aria-current={section === id ? "page" : undefined}
                onClick={() => navigate(id)}
              >
                <Icon size={20} />
                {id === "incidents" && data.dashboard.current.incidents > 0 && (
                  <i className="nav-alert" />
                )}
              </button>
            ))}
          </div>
          <div className="nav-bottom">
            <button
              className="nav-item"
              title="Simulation settings"
              aria-label="Simulation settings"
              onClick={() => setDialog("settings")}
            >
              <Settings2 size={19} />
            </button>
            <button
              className="nav-item"
              title="About this simulation"
              aria-label="About this simulation"
              onClick={() => setDialog("about")}
            >
              <CircleHelp size={19} />
            </button>
            <span className="operator-avatar" title="Local simulation operator">
              OP
            </span>
          </div>
        </nav>
        <div className="main-shell">
          <header className="global-header">
            <div className="wordmark">
              AutoNOC<span>COMMAND CENTER</span>
            </div>
            <span className="header-divider" />
            <div className="network-switch">
              <span className="network-symbol">
                <RadioTower size={17} />
              </span>
              <div>
                <strong>{config.presentation.network_name}</strong>
                <span>LTE network · Digital twin</span>
              </div>
              <ChevronRight size={14} />
            </div>
            <div className="header-spacer" />
            <button
              className="search-trigger"
              onClick={() => {
                setQuery("");
                setDialog("search");
              }}
            >
              <Search size={14} />
              <span>Find a site...</span>
              <kbd>⌘ K</kbd>
            </button>
            <button
              className="header-bell icon-button"
              aria-label="Open network event history"
              onClick={() => setDialog("activity")}
            >
              <Bell size={18} />
              {data.dashboard.current.incidents > 0 && <i />}
            </button>
            <span className="header-divider" />
            <div className="header-system">
              <ShieldCheck size={16} />
              <div>
                LOCAL SIMULATION<span>O-RAN · Non-RT RIC</span>
              </div>
            </div>
          </header>
          <main id="overview">
            <div className="overview-heading">
              <div>
                <div className="breadcrumb">
                  WORKSPACE <ChevronRight size={10} /> NETWORK OPERATIONS
                </div>
                <h1>
                  Network overview
                  <span className="overview-dot" />
                </h1>
                <p>Your network, in focus. Every site. Every signal.</p>
              </div>
              <div className="overview-meta">
                <span className={`connection ${status}`}>
                  <Dot
                    color={status === "live" ? p.healthy : p.warning}
                    pulse={status === "live" && !data.control.paused}
                  />
                  {status === "live"
                    ? data.control.paused
                      ? "PAUSED"
                      : "LIVE TELEMETRY"
                    : "RECONNECTING"}
                </span>
                <div className="sim-clock">
                  <Clock3 size={13} />
                  <span className="mono">{data.kpis.sim_time}</span>
                  <span className="seed">SEED {data.control.seed}</span>
                </div>
              </div>
            </div>
            <div className="command-bar">
              <div className="command-context">
                <span className="live-line" />
                <span>NETWORK COMMAND</span>
                <span className="soft-separator">/</span>
                <span className="command-context-sub">
                  {config.num_nodes} sites · {data.agg.length} districts
                </span>
              </div>
              <SimControls
                data={data}
                config={config}
                busy={busy || status !== "live"}
                execute={execute}
                onCut={() => setDialog("cut")}
                onInject={() => {
                  setInjectNode(undefined);
                  setDialog("inject");
                }}
              />
            </div>
            {status !== "live" && (
              <div className="connection-banner" role="alert">
                <Wifi size={16} />
                <span>
                  Telemetry connection interrupted. Showing the last received
                  state. {error}
                </span>
                <button onClick={refresh}>Reconnect</button>
              </div>
            )}
            <KpiGrid data={data} config={config} />
            <div className="primary-grid">
              <NetworkMap
                config={config}
                data={data}
                selectedId={selected}
                onSelect={selectNode}
              />
              <AlertsSidebar
                config={config}
                data={data}
                onSelect={selectNode}
                onActivity={() => setDialog("activity")}
                execute={execute}
              />
            </div>
            <div className="section-label">
              <span>
                <Activity size={13} /> TELEMETRY & INTELLIGENCE
              </span>
              <span>
                Server-derived metrics <span className="label-dot">·</span> Last{" "}
                {config.presentation.history_ticks} ticks
              </span>
            </div>
            <AnalyticsRow
              data={data}
              config={config}
              onSelect={(id) => {
                selectNode(id);
                navigate("network");
              }}
              onFleet={() => setDialog("fleet")}
            />
            <footer className="app-footer">
              <span>
                <Dot color={status === "live" ? p.healthy : p.warning} /> Engine{" "}
                {status === "live" ? "connected" : "disconnected"}{" "}
                <span>·</span>{" "}
                <span className="mono">TICK {data.tick.toLocaleString()}</span>
              </span>
              <span>
                Deterministic world. Predictive operations.
                <span className="footer-version">AUTONOC / 3.0</span>
              </span>
            </footer>
          </main>
        </div>
        <Inspector
          node={data.nodes.find((n) => n.id === selected)}
          config={config}
          onClose={() => setSelected(null)}
          onInject={(id) => {
            setInjectNode(id);
            setDialog("inject");
          }}
        />
        {(dialog === "cut" || dialog === "inject") && (
          <ScenarioModal
            type={dialog}
            initialNode={injectNode}
            data={data}
            config={config}
            execute={execute}
            onClose={closeDialog}
          />
        )}
        {dialog === "activity" && (
          <Modal title="Network event history" onClose={closeDialog} wide>
            <p className="dialog-intro">
              Latest {data.logs.length} retained events · engine time. Cleared
              alarms remain here for context.
            </p>
            <div className="event-history">
              {[...data.logs].reverse().map((entry, i) => (
                <div
                  className="history-row"
                  key={`${entry.tick}-${i}-${entry.message}`}
                >
                  <span className="mono">{entry.time}</span>
                  <Badge config={config} severity={entry.severity} />
                  <p>{entry.message}</p>
                </div>
              ))}
              {!data.logs.length && (
                <div className="empty-state">
                  <ShieldCheck size={24} />
                  <strong>No events yet</strong>
                  <span>Engine events will appear here.</span>
                </div>
              )}
            </div>
          </Modal>
        )}
        {dialog === "fleet" && (
          <Modal title="Maintenance fleet" onClose={closeDialog} wide>
            <p className="dialog-intro">
              {config.num_teams} crews · {data.dashboard.fleet.IDLE} available.
              Travel and repairs are controlled by the engine.
            </p>
            <div className="fleet-grid">
              {data.teams.map((team) => (
                <article key={team.id} className="fleet-card">
                  <div>
                    <Truck size={18} />
                    <strong>{team.name}</strong>
                    <span className="mono">{team.skill}</span>
                  </div>
                  <span
                    className="fleet-state"
                    style={{ color: team.available ? p.healthy : p.crew }}
                  >
                    {team.state.replaceAll("_", " ")}
                  </span>
                  <p>{team.target ?? "Returning / available at depot"}</p>
                  <div className="fleet-card-foot">
                    <span>ETA {team.eta} ticks</span>
                    <span>{team.missions} missions</span>
                  </div>
                </article>
              ))}
            </div>
          </Modal>
        )}
        {dialog === "search" && (
          <Modal title="Find a network site" onClose={closeDialog}>
            <label className="search-field">
              <Search size={17} />
              <input
                autoFocus
                placeholder="Search site ID or district..."
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                aria-label="Search site ID or district"
              />
            </label>
            <div className="search-results">
              {matched.map((node) => (
                <button
                  key={node.id}
                  onClick={() => {
                    selectNode(node.id);
                    closeDialog();
                    navigate("network");
                  }}
                >
                  <Dot color={config.status_colors[node.status]} />
                  <div>
                    <strong className="mono">{node.id}</strong>
                    <span>
                      {config.agg_sites.find((a) => a.id === node.agg)?.name}
                    </span>
                  </div>
                  <ArrowUpRight size={14} />
                </button>
              ))}
              {!matched.length && (
                <p className="empty-state">No sites match “{query}”.</p>
              )}
            </div>
            <p className="small-muted">
              Showing up to 12 matches · use Tab and Enter to select.
            </p>
          </Modal>
        )}
        {dialog === "settings" && (
          <Modal title="Simulation settings" onClose={closeDialog}>
            <div className="setting-row">
              <div>
                <strong>Demo auto-approval</strong>
                <p>
                  Automatically approve pending crew requests after 10
                  wall-clock seconds. The current worker checks this on
                  inference cycles.
                </p>
              </div>
              <button
                className={`switch ${data.control.auto_approve_seconds > 0 ? "on" : ""}`}
                role="switch"
                aria-label="Demo auto-approval"
                aria-checked={data.control.auto_approve_seconds > 0}
                disabled={busy}
                onClick={() =>
                  void execute(
                    () =>
                      api.ai(
                        true,
                        data.control.auto_approve_seconds > 0 ? 0 : 10,
                      ),
                    "Approval policy updated",
                  )
                }
              >
                <i />
              </button>
            </div>
            <div className="settings-info">
              <span>Predictor</span>
              <strong>{data.ai.ai_mode.toUpperCase()}</strong>
              <span>Action threshold</span>
              <strong className="mono">
                p &gt; {config.break_even_precision}
              </strong>
              <span>Forecast horizon</span>
              <strong>
                {config.presentation.prediction_horizon_min} sim minutes
              </strong>
              <span>Tick duration</span>
              <strong>{config.tick_minutes} sim minutes</strong>
              <span>Run seed</span>
              <strong>{data.control.seed}</strong>
            </div>
            <p className="small-muted">
              ML or rules fallback is selected by model availability, not a
              cosmetic mode switch. All connected users share these controls.
            </p>
          </Modal>
        )}
        {dialog === "about" && (
          <Modal title="Predictive network operations" onClose={closeDialog}>
            <div className="about-icon">
              <Boxes size={30} />
            </div>
            <p className="dialog-intro">
              AutoNOC is a deterministic LTE digital twin of{" "}
              {config.presentation.network_name}. The Doctor diagnoses, the
              Oracle forecasts, and the Commander applies cost-based policies.
            </p>
            <div className="about-roles">
              {Object.entries(config.rapp_roles).map(([key, value]) => (
                <p key={key}>
                  <Sparkles size={14} />
                  <span>{value}</span>
                </p>
              ))}
            </div>
            <p className="small-muted">
              This is a simulation, not a live operator network or certified
              O-RAN implementation. KPIs and model predictions come from the
              Python backend. AI benefit and saved-time counters are modeled
              estimates.
            </p>
            <a
              href="/docs"
              target="_blank"
              rel="noreferrer"
              className="button secondary"
            >
              Explore the API <ArrowUpRight size={13} />
            </a>
          </Modal>
        )}
        <AnimatePresence>
          {toast && (
            <motion.div
              className={`toast ${toast.error ? "error" : ""}`}
              style={tone(toast.error ? p.critical : p.healthy)}
              initial={{ opacity: 0, y: 15 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: 15 }}
              role={toast.error ? "alert" : "status"}
            >
              <Dot color={toast.error ? p.critical : p.healthy} />
              <span>{toast.text}</span>
              <button
                className="icon-button"
                aria-label="Dismiss notification"
                onClick={() => setToast(null)}
              >
                <X size={15} />
              </button>
            </motion.div>
          )}
        </AnimatePresence>
      </div>
    </MotionConfig>
  );
}
