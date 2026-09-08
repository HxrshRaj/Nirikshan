"use client";

export function Sparkline({
  points,
  width = 260,
  height = 60,
  stroke = "#4f9cf9",
  markers,
}: {
  points: { ts: string; value: number }[];
  width?: number;
  height?: number;
  stroke?: string;
  markers?: { index: number; color: string }[];
}) {
  if (!points || points.length < 2)
    return <div className="text-xs text-muted">no data</div>;
  const xs = points.map((_, i) => i);
  const ys = points.map((p) => p.value);
  const minY = Math.min(...ys);
  const maxY = Math.max(...ys);
  const rangeY = maxY - minY || 1;
  const px = (i: number) => (i / (xs.length - 1)) * (width - 4) + 2;
  const py = (v: number) => height - 4 - ((v - minY) / rangeY) * (height - 8);
  const d = points.map((p, i) => `${i === 0 ? "M" : "L"}${px(i).toFixed(1)},${py(p.value).toFixed(1)}`).join(" ");
  return (
    <svg width={width} height={height} className="block">
      <path d={d} fill="none" stroke={stroke} strokeWidth={1.5} />
      {markers?.map((m, k) => (
        <line
          key={k}
          x1={px(m.index)}
          x2={px(m.index)}
          y1={2}
          y2={height - 2}
          stroke={m.color}
          strokeWidth={1}
          strokeDasharray="3 2"
        />
      ))}
      <circle cx={px(points.length - 1)} cy={py(ys[ys.length - 1])} r={2.5} fill={stroke} />
    </svg>
  );
}
