import React, { useEffect, useMemo, useRef, useState } from 'react'
import { nodeTone, shortName } from '../evidence.js'

/*
  Timeline mode. Every row is one device; x is its FDA clearance date. Diamonds are recall records
  at their initiation date on the device's row, so "cited after the predicate was already recalled"
  reads at a glance against the candidate's dashed clearance line.
*/
const ROW = 28, PAD_T = 34, LABEL_W = 260
const t = (d) => (d ? Date.parse(d.slice(0, 10) + 'T00:00:00Z') : null)

function buildRows(a, depth) {
  const nodes = new Map()
  const add = (dev, side, gen, parent) => { if (!nodes.has(dev.k)) nodes.set(dev.k, { ...dev, side, gen, parent, children: [] }) }
  add({ ...a.device, k: a.k }, 'self', 0, null)
  for (const x of a.ancestors) if (x.gen <= depth) add(x, 'up', x.gen, x.chain[x.chain.length - 2])
  for (const x of a.descendants) add(x, 'down', x.gen, x.chain[x.chain.length - 2])
  for (const n of nodes.values()) if (n.parent && nodes.has(n.parent)) nodes.get(n.parent).children.push(n.k)
  const byDate = (p, q) => (nodes.get(p).decision_date || '').localeCompare(nodes.get(q).decision_date || '')
  const order = []
  const walkDown = (k) => { for (const c of nodes.get(k).children.filter((c) => nodes.get(c).side === 'down').sort(byDate).reverse()) { walkDown(c); order.push(c) } }
  const walkUp = (k) => { for (const c of nodes.get(k).children.filter((c) => nodes.get(c).side === 'up').sort(byDate).reverse()) { order.push(c); walkUp(c) } }
  walkDown(a.k); order.push(a.k); walkUp(a.k)
  return { nodes, order }
}

export default function Timeline({ a, depth, highlight, onSelect }) {
  const wrap = useRef(null)
  const [width, setWidth] = useState(1000)
  useEffect(() => {
    const on = () => wrap.current && setWidth(Math.max(760, wrap.current.clientWidth))
    on()
    const ro = new ResizeObserver(on)
    ro.observe(wrap.current)
    return () => ro.disconnect()
  }, [])
  const { nodes, order } = useMemo(() => buildRows(a, depth), [a, depth])
  const rowOf = new Map(order.map((k, i) => [k, i]))
  const times = []
  for (const n of nodes.values()) {
    if (n.decision_date) times.push(t(n.decision_date))
    for (const r of n.recalls || []) if (r.initiated) times.push(t(r.initiated))
  }
  const y0 = new Date(Math.min(...times)).getUTCFullYear(), y1 = new Date(Math.max(...times)).getUTCFullYear() + 1
  const x0 = Date.UTC(y0, 0, 1), x1 = Date.UTC(y1, 0, 1)
  const plotW = width - LABEL_W - 40
  const X = (ms) => 16 + ((ms - x0) / (x1 - x0)) * plotW
  const Y = (i) => PAD_T + i * ROW + ROW / 2
  const height = PAD_T + order.length * ROW + 16
  const hl = new Set(highlight || [])
  const hlEdge = new Set()
  if (highlight) for (let i = 0; i + 1 < highlight.length; i++) hlEdge.add(highlight[i] + '>' + highlight[i + 1])
  const step = y1 - y0 > 24 ? 4 : y1 - y0 > 12 ? 2 : 1
  const years = []
  for (let y = y0; y <= y1; y += step) years.push(y)
  const cx = X(t(a.device.decision_date))
  return (
    <div className="graph-wrap" ref={wrap} data-testid="timeline">
      <svg width={width} height={height} role="group" aria-label={`Lineage timeline for ${a.k}`}>
        {years.map((y) => (
          <g key={y}>
            <line className="tl-grid" x1={X(Date.UTC(y, 0, 1))} x2={X(Date.UTC(y, 0, 1))} y1={PAD_T - 8} y2={height - 8} />
            <text className="tl-axis" x={X(Date.UTC(y, 0, 1))} y={18} textAnchor="middle">{y}</text>
          </g>
        ))}
        <rect x={0} y={Y(rowOf.get(a.k)) - ROW / 2} width={width} height={ROW} className="tl-band" />
        <line className="tl-clear" x1={cx} x2={cx} y1={PAD_T - 8} y2={height - 8} />
        {[...nodes.values()].filter((n) => n.parent && nodes.has(n.parent)).map((n) => {
          const [from, to] = n.side === 'up' ? [n.parent, n.k] : [n.k, n.parent]
          const f = nodes.get(from), g = nodes.get(to)
          if (!f.decision_date || !g.decision_date) return null
          const xa = X(t(f.decision_date)), ya = Y(rowOf.get(from)), xb = X(t(g.decision_date)), yb = Y(rowOf.get(to))
          const mx = (xa + xb) / 2
          return <path key={from + to} d={`M${xa - 6},${ya} C${mx},${ya} ${mx},${yb} ${xb + 7},${yb}`} className={'tl-edge' + (hlEdge.has(from + '>' + to) ? ' on' : '')} />
        })}
        {order.map((k, i) => {
          const n = nodes.get(k)
          if (!n.decision_date) return null
          const x = X(t(n.decision_date)), y = Y(i)
          const tone = nodeTone(n)
          const dim = hl.size && !hl.has(k)
          return (
            <g key={k} className="tl-row g-node" style={{ opacity: dim ? 0.3 : 1 }} tabIndex={0} role="button"
              aria-label={`${k} ${n.name}, cleared ${n.decision_date}, ${(n.recalls || []).length} recall records`}
              onClick={() => onSelect({ type: 'node', k })} onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); onSelect({ type: 'node', k }) } }}>
              <rect className="tl-rowhit" x={0} y={y - ROW / 2} width={width} height={ROW} />
              {(n.recalls || []).map((r) => r.initiated && (
                <g key={r.id}>
                  <line className="tl-rlink" x1={x} x2={X(t(r.initiated))} y1={y} y2={y} />
                  <path d={`M${X(t(r.initiated))},${y - 5} l5,5 l-5,5 l-5,-5 z`} className={'tl-dia ' + (r.design_related ? 'design' : 'other')}>
                    <title>{`${r.id} · ${r.classification || 'unclassified'} · ${r.root_cause} · began ${r.initiated}`}</title>
                  </path>
                </g>
              ))}
              <circle cx={x} cy={y} r={k === a.k ? 7 : 5.5} className={`dot tone-${tone}${n.lineage_known === false ? ' unread' : ''}`}
                style={k === a.k ? { fill: 'var(--ivory)', stroke: 'var(--blue)', strokeWidth: 3 } : undefined} />
              <text x={width - LABEL_W + 8} y={y + 4} className="tl-label"><tspan className="lk">{k}</tspan><tspan dx="7">{shortName(n.name, 24)}</tspan></text>
              <text x={width - LABEL_W - 6} y={y + 4} textAnchor="end" className="tl-gen">{n.side === 'self' ? 'candidate' : n.side === 'up' ? `G-${n.gen}` : `D+${n.gen}`}</text>
            </g>
          )
        })}
      </svg>
    </div>
  )
}
