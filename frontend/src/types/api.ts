/** Wire contracts for autonoc.api.schemas and its presentation projections. */
export type LatLng = [number, number];
export type Severity =
  "CRITICAL" | "MAJOR" | "MINOR" | "WARNING" | "INFO" | "CLEARED";
export type PowerSource = "Grid" | "Solar" | "Battery" | "Generator";
export type FleetState =
  "IDLE" | "EN_ROUTE" | "STANDBY" | "REPAIRING" | "RETURNING";
export interface GaugeSpec {
  lo: number;
  hi: number;
  good: number;
  warn: number;
  bad: number;
  lower_bad: boolean;
}
export interface Config {
  status_names: Record<number, string>;
  status_colors: Record<number, string>;
  thresholds: Record<string, number>;
  metric_labels: Record<string, string>;
  gauges: Record<string, GaugeSpec>;
  x733_severity: Record<number, Severity>;
  power_configs: Record<string, string>;
  vswr_alarm: number;
  rapp_roles: Record<string, string>;
  map_center: LatLng;
  map_zoom: number;
  bounds: {
    lat_min: number;
    lat_max: number;
    lon_min: number;
    lon_max: number;
  };
  epc_primary: { name: string; lat: number; lon: number; backhaul: string };
  epc_backup: { name: string; lat: number; lon: number; backhaul: string };
  depot: { lat: number; lon: number };
  agg_sites: {
    id: number;
    name: string;
    lat: number;
    lon: number;
    nodes: number;
    clutter: number;
    color: string;
  }[];
  num_nodes: number;
  num_teams: number;
  tick_minutes: number;
  break_even_precision: number;
  presentation: {
    roads: { name: string; path: LatLng[] }[];
    network_name: string;
    region_label: string;
    palette: Record<
      | "healthy"
      | "warning"
      | "critical"
      | "fiber"
      | "prediction"
      | "crew"
      | "muted",
      string
    >;
    severity_colors: Record<Severity, string>;
    power_colors: Record<PowerSource, string>;
    healthy_status: number;
    offline_statuses: number[];
    poll_ms: number;
    history_ticks: number;
    prediction_horizon_min: number;
    speed_min: number;
    speed_max: number;
    fault_options: { value: number; label: string }[];
    generation_names: Record<number, string>;
  };
}
export interface NodeData {
  id: string;
  lat: number;
  lon: number;
  agg: number;
  ring: number;
  gen: number;
  critical: boolean;
  status: number;
  rsrp: number;
  sinr: number;
  s11: number;
  latency: number;
  jitter: number;
  loss: number;
  throughput: number;
  temp: number;
  cpu: number;
  vswr: number;
  cqi: number;
  prb: number;
  power: PowerSource;
  pwr: "A" | "B" | "C";
  voltage: number;
  battery: number;
  fuel: number;
  ats: boolean;
  dust: number;
  dispatched: boolean;
  repairing: boolean;
  warn: boolean;
}
export interface Team {
  id: number;
  name: string;
  skill: "RF" | "POWER" | "GENERAL";
  lat: number;
  lon: number;
  state: FleetState;
  available: boolean;
  target: string | null;
  target_lat: number | null;
  target_lon: number | null;
  eta: number;
  missions: number;
}
export interface District {
  id: number;
  name: string;
  lat: number;
  lon: number;
  color: string;
  node_count: number;
  health: number;
  weather: string;
  wind: number;
  clutter: number;
  pwr: "A" | "B" | "C";
}
export interface Cut {
  lat: number;
  lon: number;
  seg: string;
  cause: string;
  path?: LatLng[];
}
export interface Ring {
  id: number;
  nodes: string[];
  path: LatLng[];
  circumference_km: number;
  cut: Cut | null;
  cuts: Cut[];
  isolated: boolean;
}
export interface LogEntry {
  tick: number;
  time: string;
  severity: Severity;
  message: string;
  node_id: string | null;
}
export interface Kpis {
  tick: number;
  sim_time: string;
  availability: number;
  healthy: number;
  congestion: number;
  overheat: number;
  rf: number;
  power: number;
  backhaul: number;
  active_teams: number;
  grid_failures: number;
  mttr_min: number;
  injected: number;
  masked: number;
  repairs: number;
  ats_failures: number;
  fuel_thefts: number;
}
export interface PendingAction {
  action_id: number;
  node_id: string;
  node: string;
  cls: number;
  probability: number;
  action: string;
  tier: number;
  label: string;
  created_tick: number;
  state: string;
  eta?: number;
}
export interface AiState {
  ai_enabled: boolean;
  ai_mode: "off" | "ml" | "rules";
  ai_policy: "auto" | "advisory";
  pre_empted: number;
  acted_upon: number;
  false_dispatches: number;
  precision: number | null;
  break_even_precision: number;
  crew_hours_saved: number;
  unpredictable_pct: number;
  pending: PendingAction[];
}
export interface TelemetrySample {
  tick: number;
  sim_time: string;
  availability: number;
  incidents: number;
  power_events: number;
  throughput_gbps: number;
  drop_rate: number;
  prb: number;
  online: number;
  degraded: number;
  offline: number;
}
export interface Incident {
  id: string;
  node_id: string | null;
  title: string;
  detail: string;
  severity: Severity;
  affected: number;
  since_tick: number;
  dispatched: boolean;
}
export interface Dashboard {
  current: TelemetrySample;
  history: TelemetrySample[];
  traffic_change_pct: number | null;
  operational_pct: number;
  incidents: Incident[];
  top_cells: {
    node_id: string;
    district: string;
    prb: number;
    cqi: number;
    status: number;
  }[];
  forecast: {
    node_id: string;
    probability: number;
    label: string;
    actionable: boolean;
  } | null;
  actionable_predictions: number;
  power: { name: PowerSource; count: number; fraction: number }[];
  active_ats: number;
  fuel_thefts: number;
  fleet: Record<FleetState, number>;
}
export interface RunSummary {
  completed_at: string;
  simulated_days: number;
  completed_sim_time: string;
  seed: number;
  availability: number;
  injected: number;
  masked: number;
  repairs: number;
  mttr_min: number;
  ats_failures: number;
  fuel_thefts: number;
  active_incidents: number;
  ai_enabled: boolean;
  ai_mode: string;
  pre_empted: number;
  acted_upon: number;
  false_dispatches: number;
  crew_hours_saved: number;
  precision: number | null;
}
export interface RunHistory {
  summaries: RunSummary[];
}
export interface Snapshot {
  run_id: string;
  reset_notice: boolean;
  run_error: string | null;
  tick: number;
  resync: boolean;
  kpis: Kpis;
  control: {
    paused: boolean;
    speed: number;
    seed: number;
    auto_approve_seconds: number;
  };
  nodes: NodeData[];
  teams: Team[];
  agg: District[];
  rings: Ring[];
  logs: LogEntry[];
  ai: AiState;
  dashboard: Dashboard;
}
export interface ActionResult {
  ok?: boolean;
  reason?: string;
  error?: string;
  late?: boolean;
  [key: string]: unknown;
}
export type Command = () => Promise<ActionResult>;
