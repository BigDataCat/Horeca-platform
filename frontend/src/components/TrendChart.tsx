import { useState } from "react";
import { useT } from "../i18n";

export type TrendPoint = { label: string; value: number };

const W = 640;
const H = 200;
const PAD = { top: 12, right: 8, bottom: 28, left: 52 };

function niceMax(value: number) {
  if (value <= 0) return 1;
  const exponent = Math.floor(Math.log10(value));
  const base = 10 ** exponent;
  const fraction = value / base;
  const step = fraction <= 1 ? 1 : fraction <= 2 ? 2 : fraction <= 5 ? 5 : 10;
  return step * base;
}

/** Single-series bar chart. Bars are thin, anchored to the baseline, with a 4px rounded top;
 * the grid is recessive and the exact values are always available in the table beneath it. */
export default function TrendChart({ points, title: titleKey, unit = "", format }: { points: TrendPoint[]; title: string; unit?: string; format?: (n: number) => string }) {
  const t = useT();
  const title = t(titleKey);
  const [active, setActive] = useState<number | null>(null);
  const fmt = format ?? ((n: number) => n.toLocaleString(undefined, { maximumFractionDigits: 2 }));
  if (points.length === 0) return null;

  const max = niceMax(Math.max(...points.map((p) => p.value)));
  const innerW = W - PAD.left - PAD.right;
  const innerH = H - PAD.top - PAD.bottom;
  const slot = innerW / points.length;
  const barW = Math.min(28, Math.max(4, slot * 0.6));
  const y = (value: number) => PAD.top + innerH - (Math.max(value, 0) / max) * innerH;
  const ticks = [0, max / 2, max];
  const labelEvery = Math.ceil(points.length / 8);
  const current = active === null ? null : points[active];

  return (
    <figure className="trend" aria-label={title}>
      <div className="trend-head">
        <strong>{title}</strong>
        <span className="trend-readout" aria-live="polite">{current ? `${current.label}: ${fmt(current.value)} ${unit}` : ""}</span>
      </div>
      <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label={`${title}: ${points.map((p) => `${p.label} ${fmt(p.value)}`).join(", ")}`}>
        {ticks.map((tick) => (
          <g key={tick}>
            <line x1={PAD.left} x2={W - PAD.right} y1={y(tick)} y2={y(tick)} className="trend-grid" />
            <text x={PAD.left - 8} y={y(tick) + 4} textAnchor="end" className="trend-axis">{fmt(tick)}</text>
          </g>
        ))}
        {points.map((point, index) => {
          const x = PAD.left + slot * index + (slot - barW) / 2;
          const top = y(point.value);
          const height = Math.max(PAD.top + innerH - top, point.value > 0 ? 2 : 0);
          return (
            <g key={point.label} onMouseEnter={() => setActive(index)} onMouseLeave={() => setActive(null)} onFocus={() => setActive(index)} onBlur={() => setActive(null)} tabIndex={0}>
              {/* wide invisible hit target, larger than the mark */}
              <rect x={PAD.left + slot * index} y={PAD.top} width={slot} height={innerH} fill="transparent" />
              <path
                d={`M${x},${top + height} V${top + 4} Q${x},${top} ${x + 4},${top} H${x + barW - 4} Q${x + barW},${top} ${x + barW},${top + 4} V${top + height} Z`}
                className={active === index ? "trend-bar active" : "trend-bar"}
              />
              {index % labelEvery === 0 && (
                <text x={x + barW / 2} y={H - 8} textAnchor="middle" className="trend-axis">{point.label.slice(5)}</text>
              )}
            </g>
          );
        })}
      </svg>
    </figure>
  );
}
