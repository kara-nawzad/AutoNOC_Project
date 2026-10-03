import { useEffect, useRef } from "react";
import { useReducedMotion } from "framer-motion";

interface Props {
  value: number;
  decimals?: number;
  suffix?: string;
  className?: string;
  duration?: number;
}
/** Animate text directly, never rerender the entire React tree at 60 Hz.
 * Retarget from the in-flight value. A hidden tab settles instead of catching up. */
export function NumberTween({
  value,
  decimals = 0,
  suffix = "",
  className,
  duration = 850,
}: Props) {
  const el = useRef<HTMLSpanElement>(null);
  const current = useRef(value);
  const reduced = useReducedMotion();
  useEffect(() => {
    let frame = 0;
    const startValue = current.current,
      start = performance.now();
    function draw(now: number) {
      const t =
        reduced || document.hidden ? 1 : Math.min(1, (now - start) / duration);
      current.current =
        startValue + (value - startValue) * (1 - Math.pow(1 - t, 3));
      if (el.current)
        el.current.textContent =
          current.current.toLocaleString("en-US", {
            minimumFractionDigits: decimals,
            maximumFractionDigits: decimals,
          }) + suffix;
      if (t < 1) frame = requestAnimationFrame(draw);
    }
    frame = requestAnimationFrame(draw);
    return () => cancelAnimationFrame(frame);
  }, [value, decimals, suffix, duration, reduced]);
  return (
    <span
      ref={el}
      className={className}
      aria-label={`${value.toFixed(decimals)}${suffix}`}
    >
      {value.toLocaleString("en-US", {
        minimumFractionDigits: decimals,
        maximumFractionDigits: decimals,
      })}
      {suffix}
    </span>
  );
}
