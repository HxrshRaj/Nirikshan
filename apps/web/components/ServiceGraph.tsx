"use client";

import { useMemo, useState } from "react";

export interface GraphNode {
  id: string;
  display_name: string;
  kind: string;
  tier: number;
  health: string;
  open_incidents: number;
  depends_on: string[];
}
export interface GraphEdge {
  source: string;
  target: string;
  critical: boolean;
}

const healthColor: Record<string, string> = {
  HEALTHY: "#3fb950",
  DEGRADED: "#d29922",
  UNHEALTHY: "#f85149",
  UNKNOWN: "#8b97ad",
};

/** Simple layered layout: column = longest path from a root; row = order within column. */
function layout(nodes: GraphNode[], edges: GraphEdge[]) {
  const byId = new Map(nodes.map((n) => [n.id, n]));
  const depth = new Map<string, number>();
  const visiting = new Set<string>();
  function d(id: string): number {
    if (depth.has(id)) return depth.get(id)!;
    if (visiting.has(id)) return 0;
    visiting.add(id);
    const outs = edges.filter((e) => e.source === id).map((e) => e.target);
    const val = outs.length ? 1 + Math.max(...outs.map(d)) : 0;
    visiting.delete(id);
    depth.set(id, val);
    return val;
  }
  nodes.forEach((n) => d(n.id));
  const cols = new Map<number, GraphNode[]>();
  nodes.forEach((n) => {
    const c = depth.get(n.id) ?? 0;
    if (!cols.has(c)) cols.set(c, []);
    cols.get(c)!.push(n);
  });
  const maxCol = Math.max(...[...cols.keys()], 0);
  const pos = new Map<string, { x: number; y: number }>();
  const colW = 210;
  const rowH = 92;
  [...cols.entries()].forEach(([c, list]) => {
    list
      .sort((a, b) => a.tier - b.tier || a.id.localeCompare(b.id))
      .forEach((n, i) => {
        pos.set(n.id, { x: (maxCol - c) * colW + 40, y: i * rowH + 40 });
      });
  });
  const height = Math.max(...[...cols.values()].map((l) => l.length)) * rowH + 80;
  const width = (maxCol + 1) * colW + 200;
  return { pos, width, height, byId };
}

export function ServiceGraph({
  nodes,
  edges,
  onSelect,
  selected,
}: {
  nodes: GraphNode[];
  edges: GraphEdge[];
  onSelect?: (id: string) => void;
  selected?: string | null;
}) {
  const { pos, width, height } = useMemo(() => layout(nodes, edges), [nodes, edges]);
  const [hover, setHover] = useState<string | null>(null);

  return (
    <div className="overflow-auto rounded-lg border border-border bg-bg">
      <svg width={width} height={height} className="block">
        {edges.map((e, i) => {
          const a = pos.get(e.source);
          const b = pos.get(e.target);
          if (!a || !b) return null;
          const active = hover === e.source || hover === e.target || selected === e.source || selected === e.target;
          return (
            <line
              key={i}
              x1={a.x + 150}
              y1={a.y + 26}
              x2={b.x}
              y2={b.y + 26}
              stroke={active ? "#4f9cf9" : "#232b3b"}
              strokeWidth={e.critical ? 2 : 1}
              strokeDasharray={e.critical ? undefined : "4 3"}
              markerEnd="url(#arrow)"
            />
          );
        })}
        <defs>
          <marker id="arrow" markerWidth="8" markerHeight="8" refX="7" refY="3" orient="auto">
            <path d="M0,0 L0,6 L7,3 z" fill="#3a465c" />
          </marker>
        </defs>
        {nodes.map((n) => {
          const p = pos.get(n.id);
          if (!p) return null;
          const sel = selected === n.id;
          return (
            <g
              key={n.id}
              transform={`translate(${p.x},${p.y})`}
              className="cursor-pointer"
              onMouseEnter={() => setHover(n.id)}
              onMouseLeave={() => setHover(null)}
              onClick={() => onSelect?.(n.id)}
            >
              <rect
                width={150}
                height={52}
                rx={8}
                fill="#121722"
                stroke={sel ? "#4f9cf9" : "#232b3b"}
                strokeWidth={sel ? 2 : 1}
              />
              <circle cx={14} cy={16} r={5} fill={healthColor[n.health] || "#8b97ad"} />
              <text x={28} y={20} fill="#e6ebf4" fontSize={11} fontWeight={600}>
                {n.display_name.length > 18 ? n.display_name.slice(0, 17) + "…" : n.display_name}
              </text>
              <text x={12} y={38} fill="#8b97ad" fontSize={10}>
                {n.kind} · tier {n.tier}
              </text>
              {n.open_incidents > 0 && (
                <>
                  <circle cx={136} cy={16} r={8} fill="#f85149" />
                  <text x={136} y={19} fill="#fff" fontSize={9} textAnchor="middle">
                    {n.open_incidents}
                  </text>
                </>
              )}
            </g>
          );
        })}
      </svg>
    </div>
  );
}
