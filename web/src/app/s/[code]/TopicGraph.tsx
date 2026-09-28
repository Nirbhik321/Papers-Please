"use client";

import { forceCollide, forceLink, forceManyBody, forceSimulation, forceX, forceY } from "d3-force";
import type { SimulationLinkDatum, SimulationNodeDatum } from "d3-force";
import { useMemo, useState } from "react";
import type { Module } from "@/lib/types";

const MODULE_COLORS = ["#7F77DD", "#1D9E75", "#D85A30", "#D4537E", "#378ADD"];
const W = 1000;
const H = 640;

type Node = SimulationNodeDatum & {
  key: string; label: string; text: string; module: number; r: number; pct: number; freq: number; family: string;
};
type Link = SimulationLinkDatum<Node> & { strength: number };

const STRIP = /^(explain|define|describe|derive|prove|illustrate|list|compare|differentiate|discuss|write|draw|state|evaluate|analy[sz]e|outline|find|solve|give|sketch|show|calculate|determine)\s+/i;
const NOISE = new Set(["and", "or", "of", "in", "on", "at", "to", "for", "with", "by", "from", "the", "a", "an", "its", "using", "between"]);

/** Topics whose labels start with the same key word ("TCP …", "CRC …") pull together. */
function family(label: string) {
  const words = label.replace(STRIP, "").split(/\W+/).filter((w) => w && !NOISE.has(w.toLowerCase()));
  return (words[0] || label).toLowerCase();
}

function layout(modules: Module[]) {
  const anchors = modules.map((_, i) => {
    const a = (i / modules.length) * Math.PI * 2 - Math.PI / 2;
    return { x: W / 2 + Math.cos(a) * 260, y: H / 2 + Math.sin(a) * 190 };
  });
  const nodes: Node[] = modules.flatMap((m, mi) => m.topics.map((t) => ({
    key: t.key, label: t.label, text: t.text, module: m.no, freq: t.frequency, pct: t.frequencyPct,
    r: 7 + t.frequencyPct * 20, family: family(t.label),
    x: anchors[mi].x + (Math.random() - 0.5) * 40, y: anchors[mi].y + (Math.random() - 0.5) * 40,
  })));
  const links: Link[] = [];
  for (let i = 0; i < nodes.length; i++) {
    for (let j = i + 1; j < nodes.length; j++) {
      const a = nodes[i], b = nodes[j];
      if (a.family === b.family) links.push({ source: a.key, target: b.key, strength: 0.6 });
      else if (a.module === b.module && Math.abs(i - j) === 1) links.push({ source: a.key, target: b.key, strength: 0.15 });
    }
  }
  const anchorOf = (n: Node) => anchors[modules.findIndex((m) => m.no === n.module)];
  const sim = forceSimulation(nodes)
    .force("link", forceLink<Node, Link>(links).id((n) => n.key).distance(55).strength((l) => l.strength))
    .force("charge", forceManyBody().strength(-60))
    .force("x", forceX<Node>((n) => anchorOf(n).x).strength(0.12))
    .force("y", forceY<Node>((n) => anchorOf(n).y).strength(0.12))
    .force("collide", forceCollide<Node>((n) => n.r + 3))
    .stop();
  for (let i = 0; i < 300; i++) sim.tick();
  nodes.forEach((n) => {
    n.x = Math.max(n.r + 4, Math.min(W - n.r - 4, n.x ?? 0));
    n.y = Math.max(n.r + 4, Math.min(H - n.r - 4, n.y ?? 0));
  });
  return { nodes, links: links as (Link & { source: Node; target: Node })[] };
}

export default function TopicGraph({ modules, studied, onOpen }: {
  modules: Module[]; studied: Set<string>; onOpen: (key: string) => void;
}) {
  const { nodes, links } = useMemo(() => layout(modules), [modules]);
  const [hover, setHover] = useState<Node | null>(null);

  return (
    <div className="relative overflow-hidden rounded-2xl border border-line bg-surface">
      <svg viewBox={`0 0 ${W} ${H}`} className="block h-[640px] w-full" role="img"
        aria-label="Graph of topics grouped by module; larger circles repeat more often">
        {links.map((l, i) => (
          <line key={i} x1={l.source.x} y1={l.source.y} x2={l.target.x} y2={l.target.y}
            stroke="var(--line-strong)" strokeWidth={l.strength > 0.3 ? 1.5 : 0.75}
            opacity={hover && hover.key !== l.source.key && hover.key !== l.target.key ? 0.25 : 0.8} />
        ))}
        {nodes.map((n) => {
          const color = MODULE_COLORS[(n.module - 1) % MODULE_COLORS.length];
          const dim = hover && hover.key !== n.key && hover.family !== n.family;
          return (
            <g key={n.key} transform={`translate(${n.x},${n.y})`} opacity={dim ? 0.35 : 1}
              onMouseEnter={() => setHover(n)} onMouseLeave={() => setHover(null)}
              onClick={() => onOpen(n.key)} className="cursor-pointer">
              <circle r={n.r} fill={color} fillOpacity={studied.has(n.key) ? 1 : 0.8}
                stroke={studied.has(n.key) ? "var(--ink)" : "var(--surface)"} strokeWidth={studied.has(n.key) ? 2.5 : 1.5} />
              {(n.pct >= 0.5 || hover?.key === n.key) && (
                <text y={n.r + 14} textAnchor="middle" fontSize={12} fill="var(--ink)"
                  style={{ paintOrder: "stroke", stroke: "var(--surface)", strokeWidth: 4 }}>
                  {n.label.length > 28 ? `${n.label.slice(0, 27)}…` : n.label}
                </text>
              )}
            </g>
          );
        })}
      </svg>

      <div className="absolute top-4 left-4 flex flex-col gap-1.5 rounded-xl border border-line bg-surface/95 px-3.5 py-3 text-[13px]">
        {modules.map((m) => (
          <span key={m.no} className="flex items-center gap-2">
            <span className="h-2.5 w-2.5 rounded-full" style={{ background: MODULE_COLORS[(m.no - 1) % MODULE_COLORS.length] }} />
            Module {m.no} · {m.topics.length}
          </span>
        ))}
        <span className="mt-1 text-ink-2">Outlined = studied</span>
      </div>

      {hover && (
        <div className="pointer-events-none absolute right-4 bottom-4 max-w-[360px] rounded-xl border border-line bg-surface px-4 py-3 shadow-lg">
          <p className="font-display text-lg font-semibold">{hover.label}</p>
          <p className="mt-1 text-[13px] text-ink-2">Module {hover.module} · in {hover.freq} paper{hover.freq === 1 ? "" : "s"}</p>
          <p className="mt-2 text-sm leading-normal">“{hover.text}”</p>
        </div>
      )}
    </div>
  );
}
