import {
  useEffect,
  useId,
  useRef,
  type CSSProperties,
  type ReactNode,
} from "react";
import { motion } from "framer-motion";
import { X, ArrowUpRight } from "lucide-react";
import type { Config, Severity } from "../types/api";

export const tone = (color: string): CSSProperties =>
  ({ "--tone": color }) as CSSProperties;
export function Dot({
  color,
  pulse = false,
}: {
  color: string;
  pulse?: boolean;
}) {
  return (
    <span
      aria-hidden="true"
      className={`status-dot ${pulse ? "pulse" : ""}`}
      style={{ background: color, color }}
    />
  );
}
export function Badge({
  severity,
  config,
}: {
  severity: Severity;
  config: Config;
}) {
  return (
    <span
      className="severity"
      style={tone(config.presentation.severity_colors[severity])}
    >
      {severity}
    </span>
  );
}
export function PanelHeading({
  eyebrow,
  title,
  right,
}: {
  eyebrow?: string;
  title: string;
  right?: ReactNode;
}) {
  return (
    <div className="panel-heading">
      <div>
        {eyebrow && <div className="eyebrow">{eyebrow}</div>}
        <h2>{title}</h2>
      </div>
      {right}
    </div>
  );
}
/** Chart geometry only: no derived operational metrics or synthetic samples. */
export function chartPath(
  values: number[],
  width: number,
  height: number,
  domain?: [number, number],
) {
  if (!values.length) return "";
  const lo = domain?.[0] ?? Math.min(...values);
  const hi = domain?.[1] ?? Math.max(...values);
  const span = Math.max(hi - lo, 0.001);
  return values
    .map((value, index) => {
      const x =
        values.length === 1 ? width : (index / (values.length - 1)) * width;
      const y =
        height -
        3 -
        Math.max(0, Math.min(1, (value - lo) / span)) * (height - 6);
      return `${index === 0 ? "M" : "L"}${x.toFixed(2)},${y.toFixed(2)}`;
    })
    .join(" ");
}
export function Sparkline({
  values,
  color,
}: {
  values: number[];
  color: string;
}) {
  const id = useId().replace(/:/g, "");
  const d = chartPath(values, 110, 34);
  return (
    <svg
      className="sparkline"
      viewBox="0 0 110 34"
      preserveAspectRatio="none"
      aria-hidden="true"
    >
      <defs>
        <linearGradient id={id} x1="0" y1="0" x2="0" y2="1">
          <stop stopColor={color} stopOpacity=".24" />
          <stop offset="1" stopColor={color} stopOpacity="0" />
        </linearGradient>
      </defs>
      {values.length > 1 && (
        <motion.path
          initial={false}
          d={`${d} L110,34 L0,34 Z`}
          animate={{ d: `${d} L110,34 L0,34 Z` }}
          transition={{ duration: 0.6 }}
          fill={`url(#${id})`}
        />
      )}
      <motion.path
        initial={false}
        d={d}
        animate={{ d }}
        transition={{ duration: 0.6 }}
        stroke={color}
        strokeWidth="1.7"
        fill="none"
        vectorEffect="non-scaling-stroke"
      />
    </svg>
  );
}
export function Modal({
  title,
  children,
  onClose,
  wide = false,
}: {
  title: string;
  children: ReactNode;
  onClose: () => void;
  wide?: boolean;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  const id = useId();
  useEffect(() => {
    const dialog = ref.current;
    dialog?.showModal();
    return () => dialog?.close();
  }, []);
  return (
    <dialog
      ref={ref}
      className={`dialog ${wide ? "wide" : ""}`}
      aria-labelledby={id}
      onCancel={onClose}
      onClick={(e) => {
        if (e.target === ref.current) onClose();
      }}
    >
      <div className="dialog-content">
        <div className="dialog-heading">
          <div>
            <span className="eyebrow">AUTONOC COMMAND</span>
            <h2 id={id}>{title}</h2>
          </div>
          <button
            className="icon-button"
            aria-label="Close dialog"
            onClick={onClose}
          >
            <X size={18} />
          </button>
        </div>
        {children}
      </div>
    </dialog>
  );
}
export function TextLink({
  children,
  onClick,
}: {
  children: ReactNode;
  onClick: () => void;
}) {
  return (
    <button className="text-link" onClick={onClick}>
      {children}
      <ArrowUpRight size={13} />
    </button>
  );
}
