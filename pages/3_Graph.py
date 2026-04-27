"""
3_Graph.py — Obsidian-style question graph with topic cluster hulls.

Nodes keep their module colour. Questions with similar topic labels
are grouped inside a translucent convex-hull "topic bubble".

Drop this file into your pages/ folder alongside 1_Upload.py and 2_Dashboard.py.
"""

from pathlib import Path
import json
import re

import streamlit as st
import streamlit.components.v1 as components

import pipeline
from modules.db import get_distinct_subjects, init_db

DB_PATH = str(Path(__file__).parent.parent / "data" / "papers.db")
Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
init_db(DB_PATH)

st.set_page_config(
    page_title="Question Graph | Papers Please",
    page_icon="🕸️",
    layout="wide",
)

st.title("🕸️ Question Graph")
st.caption(
    "Nodes = question topics, coloured by module. "
    "Shaded regions = topic clusters (questions that share a common theme). "
    "Node size = repeat frequency. Hover to inspect, click to highlight neighbours."
)

subjects = get_distinct_subjects(DB_PATH)
if not subjects:
    st.info("No papers in the database yet. Go to **Upload** to add papers.")
    st.stop()

subject_options = {
    f"{s['subject_code']} — {s['subject_name']}": s["subject_code"]
    for s in subjects
}
selected_label = st.selectbox("Subject", list(subject_options.keys()))
selected_code  = subject_options[selected_label]

try:
    module_ladders, total_papers = pipeline.get_module_analysis(DB_PATH, selected_code)
except Exception as e:
    st.error(f"Could not load analysis: {e}")
    st.stop()

if not module_ladders:
    st.warning("No analysis data found for this subject.")
    st.stop()

# ── Topic-family extraction ────────────────────────────────────────────────────
_STRIP = re.compile(
    r"^(explain|define|describe|derive|prove|illustrate|list|compare|"
    r"differentiate|discuss|write|draw|state|evaluate|analyze|outline|"
    r"find|solve|give|sketch|show|calculate|determine)\s+",
    re.IGNORECASE,
)
_NOISE = {"and", "or", "of", "in", "on", "at", "to", "for", "with",
          "by", "from", "the", "a", "an", "its", "using", "between"}

def topic_family(label: str) -> str:
    cleaned = _STRIP.sub("", label.strip())
    words = [w for w in re.split(r"\W+", cleaned) if w and w.lower() not in _NOISE]
    return words[0].title() if words else label[:12].title()

# ── Build nodes & edges ────────────────────────────────────────────────────────
MODULE_COLORS = {
    1: "#7F77DD",
    2: "#1D9E75",
    3: "#D85A30",
    4: "#D4537E",
    5: "#378ADD",
}

nodes = []
edges = []
nid   = 0

for module_no, steps in module_ladders.items():
    color = MODULE_COLORS.get(module_no, "#888780")
    module_nids = []

    for step in steps:
        freq      = step["frequency"]
        freq_pct  = step["frequency_pct"]
        label     = (step.get("topic_label") or step["representative_text"][:40]).strip()
        avg_marks = step.get("avg_marks") or 0
        years     = step.get("years", [])
        text      = step["representative_text"]
        rank      = step.get("rank", 1)
        family    = topic_family(label)
        radius    = 14 + freq_pct * 28

        nodes.append({
            "id":       nid,
            "label":    label,
            "family":   family,
            "module":   module_no,
            "color":    color,
            "radius":   round(radius, 1),
            "freq":     freq,
            "freq_pct": round(freq_pct * 100),
            "marks":    int(avg_marks),
            "years":    years,
            "rank":     rank,
            "text":     text[:200],
        })
        module_nids.append(nid)
        nid += 1

    for i in range(len(module_nids)):
        for j in range(i + 1, len(module_nids)):
            a, b = module_nids[i], module_nids[j]
            fam_a = topic_family((steps[i].get("topic_label") or steps[i]["representative_text"][:40]).strip())
            fam_b = topic_family((steps[j].get("topic_label") or steps[j]["representative_text"][:40]).strip())
            same_family = fam_a == fam_b
            strength = 0.7 if same_family else max(0.08, 0.35 - abs(steps[i]["rank"] - steps[j]["rank"]) * 0.05)
            edges.append({
                "source":      a,
                "target":      b,
                "strength":    round(strength, 2),
                "same_family": same_family,
                "module":      module_no,
                "color":       color,
            })

# ── Cluster colour map ─────────────────────────────────────────────────────────
from collections import Counter
family_module: dict[str, list] = {}
for n in nodes:
    family_module.setdefault(n["family"], []).append(n["module"])

clusters = {}
for fam, mods in family_module.items():
    most_common_mod = Counter(mods).most_common(1)[0][0]
    clusters[fam] = MODULE_COLORS.get(most_common_mod, "#888780")

graph_data   = json.dumps({"nodes": nodes, "edges": edges})
cluster_data = json.dumps(clusters)

legend_items = [
    {"module": m, "color": MODULE_COLORS.get(m, "#888"), "count": len(steps)}
    for m, steps in sorted(module_ladders.items())
]
legend_json = json.dumps(legend_items)

# ── Render ─────────────────────────────────────────────────────────────────────
html = f"""
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  #graph-wrap {{
    position: relative; width: 100%; height: 640px;
    background: #0d0e14; border-radius: 12px; overflow: hidden;
    font-family: 'JetBrains Mono', 'Fira Code', monospace;
  }}
  #graph-canvas {{ width: 100%; height: 100%; display: block; }}

  #legend {{
    position: absolute; top: 14px; left: 14px;
    background: rgba(13,14,20,0.88); border: 1px solid rgba(255,255,255,0.09);
    border-radius: 8px; padding: 10px 14px; font-size: 11px; color: #aaa; z-index: 10;
  }}
  #legend .leg-title {{ font-size:10px; color:#555; text-transform:uppercase; letter-spacing:.07em; margin-bottom:6px; }}
  #legend .leg-row {{ display:flex; align-items:center; gap:7px; margin:4px 0; color:#ccc; }}
  #legend .leg-dot  {{ width:10px; height:10px; border-radius:50%; flex-shrink:0; }}

  #cluster-legend {{
    position: absolute; top: 14px; right: 14px;
    background: rgba(13,14,20,0.88); border: 1px solid rgba(255,255,255,0.09);
    border-radius: 8px; padding: 10px 14px; font-size: 11px; z-index: 10;
    max-width: 190px; max-height: 280px; overflow-y: auto;
  }}
  #cluster-legend .leg-title {{ font-size:10px; color:#555; text-transform:uppercase; letter-spacing:.07em; margin-bottom:6px; }}
  #cluster-legend .cl-row {{ display:flex; align-items:center; gap:7px; margin:4px 0; color:#aaa; font-size:10px; }}
  #cluster-legend .cl-swatch {{ width:24px; height:9px; border-radius:3px; flex-shrink:0; opacity:0.45; }}

  #tooltip {{
    position: absolute; pointer-events: none; display: none;
    background: rgba(13,14,20,0.96); border: 1px solid rgba(255,255,255,0.13);
    border-radius: 8px; padding: 10px 14px; font-size: 12px; color: #e2e8f0;
    max-width: 280px; line-height: 1.5; z-index: 30;
  }}
  #tooltip .tt-label {{ font-size:13px; font-weight:600; color:#fff; margin-bottom:4px; word-break:break-word; }}
  #tooltip .tt-family {{ font-size:10px; color:#64748b; margin-bottom:6px; }}
  #tooltip .tt-row {{ display:flex; justify-content:space-between; gap:16px; font-size:11px; color:#94a3b8; margin:2px 0; }}
  #tooltip .tt-row span:last-child {{ color:#cbd5e1; font-weight:500; }}
  #tooltip .tt-text {{ margin-top:8px; font-size:10px; color:#64748b; font-style:italic; word-break:break-word; }}

  #controls {{
    position: absolute; bottom: 14px; right: 14px;
    display: flex; flex-direction: column; gap: 6px; z-index: 10;
  }}
  #controls button {{
    width:30px; height:30px; background: rgba(255,255,255,0.07);
    border: 1px solid rgba(255,255,255,0.12); border-radius:6px; color:#aaa;
    font-size:16px; cursor:pointer; display:flex; align-items:center;
    justify-content:center; transition: background .15s; line-height:1;
  }}
  #controls button:hover {{ background:rgba(255,255,255,0.15); color:#fff; }}

  #cluster-toggle {{
    position: absolute; bottom: 52px; left: 14px;
    background: rgba(255,255,255,0.07); border: 1px solid rgba(255,255,255,0.12);
    border-radius: 6px; color: #aaa; font-size: 10px; padding: 5px 10px;
    cursor: pointer; z-index: 10; transition: background .15s; font-family: inherit;
  }}
  #cluster-toggle:hover {{ background: rgba(255,255,255,0.14); color:#fff; }}
  #cluster-toggle.active {{ background: rgba(127,119,221,0.22); border-color: rgba(127,119,221,0.45); color:#c4bff6; }}

  #hint {{
    position:absolute; bottom:14px; left:14px;
    font-size:10px; color:rgba(255,255,255,0.2); pointer-events:none;
  }}
</style>

<div id="graph-wrap">
  <svg id="graph-canvas"></svg>
  <div id="legend"><div class="leg-title">Modules</div></div>
  <div id="cluster-legend"><div class="leg-title">Topic clusters</div></div>
  <div id="tooltip"></div>
  <button id="cluster-toggle" class="active">⬡ topic hulls ON</button>
  <div id="controls">
    <button id="btn-zoom-in">+</button>
    <button id="btn-zoom-out">−</button>
    <button id="btn-reset">⊙</button>
  </div>
  <div id="hint">scroll to zoom · drag to pan · drag nodes to rearrange</div>
</div>

<script src="https://cdnjs.cloudflare.com/ajax/libs/d3/7.8.5/d3.min.js"></script>
<script>
const GRAPH    = {graph_data};
const CLUSTERS = {cluster_data};
const LEGEND   = {legend_json};

const wrap      = document.getElementById('graph-wrap');
const svg       = d3.select('#graph-canvas');
const legDiv    = document.getElementById('legend');
const clLeg     = document.getElementById('cluster-legend');
const tooltip   = document.getElementById('tooltip');
const toggleBtn = document.getElementById('cluster-toggle');

const W = wrap.clientWidth  || 860;
const H = wrap.clientHeight || 640;
svg.attr('viewBox', `0 0 ${{W}} ${{H}}`);

let hullsVisible = true;

/* Module legend */
LEGEND.forEach(item => {{
  const row = document.createElement('div');
  row.className = 'leg-row';
  row.innerHTML = `<span class="leg-dot" style="background:${{item.color}}"></span>Module ${{item.module}}<span style="color:#555;margin-left:auto">${{item.count}}q</span>`;
  legDiv.appendChild(row);
}});

/* Cluster legend */
Object.entries(CLUSTERS).forEach(([fam, col]) => {{
  const row = document.createElement('div');
  row.className = 'cl-row';
  row.innerHTML = `<span class="cl-swatch" style="background:${{col}}"></span>${{fam}}`;
  clLeg.appendChild(row);
}});

/* Zoom */
const g = svg.append('g');
const zoom = d3.zoom().scaleExtent([0.2, 5]).on('zoom', e => g.attr('transform', e.transform));
svg.call(zoom);
document.getElementById('btn-zoom-in').onclick  = () => svg.transition().call(zoom.scaleBy, 1.4);
document.getElementById('btn-zoom-out').onclick = () => svg.transition().call(zoom.scaleBy, 0.7);
document.getElementById('btn-reset').onclick    = () => svg.transition().call(zoom.transform, d3.zoomIdentity);

/* Simulation */
const nodes = GRAPH.nodes.map(d => ({{...d}}));
const edges = GRAPH.edges.map(d => ({{...d}}));

const familyGroups = {{}};
nodes.forEach(n => {{ if (!familyGroups[n.family]) familyGroups[n.family] = []; familyGroups[n.family].push(n); }});
const familyNames = Object.keys(familyGroups);
const angleStep   = (2 * Math.PI) / Math.max(familyNames.length, 1);

/* spread initial positions by family cluster */
familyNames.forEach((fam, fi) => {{
  const cx = W/2 + Math.cos(angleStep*fi) * W*0.27;
  const cy = H/2 + Math.sin(angleStep*fi) * H*0.27;
  familyGroups[fam].forEach(n => {{
    n.x = cx + (Math.random()-.5)*45;
    n.y = cy + (Math.random()-.5)*45;
  }});
}});

const sim = d3.forceSimulation(nodes)
  .force('link', d3.forceLink(edges).id(d=>d.id)
    .distance(d => d.same_family ? 55 : 135)
    .strength(d => d.strength))
  .force('charge', d3.forceManyBody().strength(-210).distanceMax(320))
  .force('center', d3.forceCenter(W/2, H/2).strength(0.04))
  .force('collide', d3.forceCollide(d => d.radius+10).strength(0.8))
  .force('familyX', d3.forceX(d => W/2 + Math.cos(angleStep*familyNames.indexOf(d.family))*W*0.24).strength(0.13))
  .force('familyY', d3.forceY(d => H/2 + Math.sin(angleStep*familyNames.indexOf(d.family))*H*0.24).strength(0.13))
  .alphaDecay(0.022);

/* Defs */
const defs = svg.append('defs');
LEGEND.forEach(item => {{
  const f = defs.append('filter').attr('id', `glow-${{item.module}}`);
  f.append('feGaussianBlur').attr('stdDeviation', 3).attr('result', 'blur');
  const m = f.append('feMerge');
  m.append('feMergeNode').attr('in','blur');
  m.append('feMergeNode').attr('in','SourceGraphic');
}});

/* Hull layer */
const hullLayer = g.append('g').attr('class','hull-layer');

const catmullLine = d3.line().curve(d3.curveCatmullRomClosed.alpha(0.5));

function buildHulls() {{
  hullLayer.selectAll('*').remove();
  if (!hullsVisible) return;

  familyNames.forEach(fam => {{
    const members = familyGroups[fam];
    if (!members.length) return;
    const col = CLUSTERS[fam] || '#888';
    const pad = 22;

    if (members.length === 1) {{
      const n = members[0];
      hullLayer.append('circle')
        .attr('cx', n.x).attr('cy', n.y).attr('r', n.radius + pad)
        .attr('fill', col).attr('fill-opacity', 0.07)
        .attr('stroke', col).attr('stroke-opacity', 0.25)
        .attr('stroke-width', 1).attr('stroke-dasharray','4 3');
    }} else {{
      const rawPts = [];
      members.forEach(n => {{
        const r = n.radius + pad;
        for (let a=0; a<10; a++)
          rawPts.push([n.x + Math.cos(a*Math.PI*2/10)*r, n.y + Math.sin(a*Math.PI*2/10)*r]);
      }});
      const hull = d3.polygonHull(rawPts);
      if (!hull) return;
      hullLayer.append('path')
        .attr('d', catmullLine(hull))
        .attr('fill', col).attr('fill-opacity', 0.07)
        .attr('stroke', col).attr('stroke-opacity', 0.28)
        .attr('stroke-width', 1.2).attr('stroke-dasharray','5 3');

      /* label at top of hull */
      const cx = d3.mean(members, n => n.x);
      const topY = d3.min(members, n => n.y - n.radius) - pad + 4;
      hullLayer.append('text')
        .attr('x', cx).attr('y', topY)
        .attr('text-anchor','middle').attr('font-size', 10)
        .attr('fill', col).attr('fill-opacity', 0.55)
        .attr('font-family','JetBrains Mono, Fira Code, monospace')
        .attr('pointer-events','none')
        .text(fam);
    }}
  }});
}}

/* Edges */
const link = g.append('g').selectAll('line').data(edges).join('line')
  .attr('stroke', d => d.same_family ? d.color : 'rgba(255,255,255,0.08)')
  .attr('stroke-opacity', d => d.same_family ? 0.3 : 0.1)
  .attr('stroke-width', d => d.same_family ? 1.2 : 0.6)
  .attr('stroke-dasharray', d => d.same_family ? 'none' : '3 3');

/* Nodes */
const node = g.append('g').selectAll('g').data(nodes).join('g').attr('cursor','grab')
  .call(d3.drag()
    .on('start',(e,d)=>{{ if(!e.active) sim.alphaTarget(0.3).restart(); d.fx=d.x; d.fy=d.y; }})
    .on('drag', (e,d)=>{{ d.fx=e.x; d.fy=e.y; }})
    .on('end',  (e,d)=>{{ if(!e.active) sim.alphaTarget(0); d.fx=null; d.fy=null; }}));

node.append('circle').attr('r', d=>d.radius+5)
  .attr('fill', d=>d.color).attr('opacity', 0.1)
  .attr('filter', d=>`url(#glow-${{d.module}})`);

const mainCircle = node.append('circle')
  .attr('r', d=>d.radius)
  .attr('fill', d=>d.color).attr('fill-opacity', d=>0.15+d.freq_pct/220)
  .attr('stroke', d=>d.color).attr('stroke-width', 1.5).attr('stroke-opacity', 0.85);

node.append('text')
  .text(d => d.label.length>20 ? d.label.slice(0,18)+'…' : d.label)
  .attr('text-anchor','middle').attr('dy','0.35em')
  .attr('font-size', d=>Math.max(8, Math.min(11, d.radius*0.46)))
  .attr('fill','#e2e8f0').attr('fill-opacity',0.9)
  .attr('pointer-events','none').style('user-select','none');

node.filter(d=>d.freq>1).append('circle')
  .attr('cx',d=>d.radius*0.65).attr('cy',d=>-d.radius*0.65)
  .attr('r',7).attr('fill',d=>d.color)
  .attr('stroke','#0d0e14').attr('stroke-width',1.5);
node.filter(d=>d.freq>1).append('text')
  .text(d=>d.freq)
  .attr('x',d=>d.radius*0.65).attr('y',d=>-d.radius*0.65)
  .attr('text-anchor','middle').attr('dy','0.35em')
  .attr('font-size',7).attr('fill','#fff').attr('pointer-events','none');

/* Tooltip */
node.on('mouseenter',(e,d)=>{{
  const yrs = d.years.length ? d.years.join(', ') : '—';
  tooltip.style.display='block';
  tooltip.innerHTML=`
    <div class="tt-label">${{d.label}}</div>
    <div class="tt-family">cluster: ${{d.family}}</div>
    <div class="tt-row"><span>Module</span><span>Module ${{d.module}}</span></div>
    <div class="tt-row"><span>Frequency</span><span>${{d.freq}} paper(s) · ${{d.freq_pct}}%</span></div>
    <div class="tt-row"><span>Avg marks</span><span>${{d.marks}}M</span></div>
    <div class="tt-row"><span>Years seen</span><span>${{yrs}}</span></div>
    <div class="tt-text">${{d.text}}</div>
  `;
}})
.on('mousemove', e=>{{
  const bx=wrap.getBoundingClientRect();
  let lx=e.clientX-bx.left+14, ly=e.clientY-bx.top+14;
  if(lx+295>W) lx-=310; if(ly+220>H) ly-=230;
  tooltip.style.left=lx+'px'; tooltip.style.top=ly+'px';
}})
.on('mouseleave',()=>{{ tooltip.style.display='none'; }});

/* Click highlight */
let selected=null;
node.on('click',(e,d)=>{{
  e.stopPropagation();
  if(selected===d.id){{
    selected=null;
    link.attr('stroke-opacity',l=>l.same_family?0.3:0.1);
    mainCircle.attr('stroke-width',1.5).attr('fill-opacity',n=>0.15+n.freq_pct/220);
    return;
  }}
  selected=d.id;
  const nb=new Set();
  edges.forEach(l=>{{ if(l.source.id===d.id) nb.add(l.target.id); if(l.target.id===d.id) nb.add(l.source.id); }});
  link.attr('stroke-opacity',l=>l.source.id===d.id||l.target.id===d.id?0.75:0.04);
  mainCircle.attr('stroke-width',n=>n.id===d.id?2.5:1.5)
    .attr('fill-opacity',n=>n.id===d.id||nb.has(n.id)?0.38:0.05);
}});
svg.on('click',()=>{{
  selected=null;
  link.attr('stroke-opacity',l=>l.same_family?0.3:0.1);
  mainCircle.attr('stroke-width',1.5).attr('fill-opacity',n=>0.15+n.freq_pct/220);
}});

/* Toggle */
toggleBtn.addEventListener('click',()=>{{
  hullsVisible=!hullsVisible;
  toggleBtn.textContent=hullsVisible?'⬡ topic hulls ON':'⬡ topic hulls OFF';
  toggleBtn.classList.toggle('active',hullsVisible);
  buildHulls();
}});

/* Tick */
sim.on('tick',()=>{{
  link.attr('x1',d=>d.source.x).attr('y1',d=>d.source.y)
      .attr('x2',d=>d.target.x).attr('y2',d=>d.target.y);
  node.attr('transform',d=>`translate(${{d.x}},${{d.y}})`);
  buildHulls();
}});
</script>
"""

components.html(html, height=660, scrolling=False)

# ── Stats ──────────────────────────────────────────────────────────────────────
st.divider()
total_nodes = sum(len(s) for s in module_ladders.values())
unique_families = len(set(
    topic_family((s.get("topic_label") or s["representative_text"][:40]).strip())
    for steps in module_ladders.values()
    for s in steps
))

c1, c2, c3, c4 = st.columns(4)
c1.metric("Total Topics",    total_nodes)
c2.metric("Topic Clusters",  unique_families)
c3.metric("Modules Mapped",  len(module_ladders))
c4.metric("Papers Analysed", total_papers)

st.caption(
    "Shaded hulls = topic clusters grouped by first meaningful keyword from the topic label. "
    "Solid edges = within-cluster links · dashed edges = cross-cluster links. "
    "Toggle hulls on/off with the button in the bottom-left of the graph."
)