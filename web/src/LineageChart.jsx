import React, { useMemo, useState } from 'react'

/*
  Lineage timeline. Every row is one device; x is its FDA clearance date.
  Ancestors (predicates) are below the candidate, descendants above.
  Arrows point from a device to the predicate it cites (leftwards, back in time).
  Diamonds are recall records placed at their initiation date on the device's row,
  so "cleared after the predicate was already recalled" is visible at a glance.
*/

const ROW = 24
const PAD_T = 34
const LABEL_W = 250

function t(d) { return d ? new Date(d + 'T00:00:00Z').getTime() : null }

function buildRows(a) {
  // tree edges from shortest chains
  const nodes = new Map()
  const add = (dev, side, gen, parent) => {
    if (!nodes.has(dev.k)) nodes.set(dev.k, { ...dev, side, gen, parent, children: [] })
  }
  add({ ...a.device, k: a.k }, 'self', 0, null)
  for (const x of a.ancestors) add(x, 'up', x.gen, x.chain[x.chain.length - 2])
  for (const x of a.descendants) add(x, 'down', x.gen, x.chain[x.chain.length - 2])
  for (const n of nodes.values()) if (n.parent && nodes.has(n.parent)) nodes.get(n.parent).children.push(n.k)

  const byDate = (p, q) => (nodes.get(p).decision_date || '').localeCompare(nodes.get(q).decision_date || '')
  const order = []
  // descendants: newest-first preorder so the tree reads top-down towards the candidate
  const walkDown = (k) => {
    const kids = nodes.get(k).children.filter((c) => nodes.get(c).side === 'down').sort(byDate).reverse()
    for (const c of kids) { walkDown(c); order.push(c) }
  }
  const walkUp = (k) => {
    const kids = nodes.get(k).children.filter((c) => nodes.get(c).side === 'up').sort(byDate).reverse()
    for (const c of kids) { order.push(c); walkUp(c) }
  }
  walkDown(a.k)
  order.push(a.k)
  walkUp(a.k)
  return { nodes, order }
}

export default function LineageChart({ a, highlight, onPick, width = 1080 }) {
  const [hover, setHover] = useState(null)
  const { nodes, order } = useMemo(() => buildRows(a), [a])
  const rowOf = useMemo(() => new Map(order.map((k, i) => [k, i])), [order])

  const times = []
  for (const n of nodes.values()) {
    if (n.decision_date) times.push(t(n.decision_date))
    for (const r of n.recalls || []) if (r.initiated) times.push(t(r.initiated))
  }
  const minT = Math.min(...times), maxT = Math.max(...times, Date.now())
  const y0 = new Date(minT).getUTCFullYear(), y1 = new Date(maxT).getUTCFullYear() + 1
  const x0 = Date.UTC(y0, 0, 1), x1 = Date.UTC(y1, 0, 1)
  const plotW = width - LABEL_W - 84
  const X = (ms) => 16 + ((ms - x0) / (x1 - x0)) * plotW
  const Y = (i) => PAD_T + i * ROW + ROW / 2
  const height = PAD_T + order.length * ROW + 16
  const hl = new Set(highlight || [])
  const hlEdge = new Set()
  if (highlight) for (let i = 0; i + 1 < highlight.length; i++) hlEdge.add(highlight[i] + '>' + highlight[i + 1])

  const years = []
  const step = y1 - y0 > 24 ? 4 : y1 - y0 > 12 ? 2 : 1
  for (let y = y0; y <= y1; y += step) years.push(y)

  const status = (n) => {
    const rs = n.recalls || []
    if (rs.some((r) => r.design_related)) return 'design'
    if (rs.length) return 'recall'
    return 'clean'
  }

  return (
    <div className="chart-wrap">
      <svg width={width} height={height} role="img" aria-label="Predicate lineage timeline">
        {years.map((y) => (
          <g key={y}>
            <line x1={X(Date.UTC(y, 0, 1))} x2={X(Date.UTC(y, 0, 1))} y1={PAD_T - 8} y2={height - 8} className="grid" />
            <text x={X(Date.UTC(y, 0, 1))} y={18} className="axis" textAnchor="middle">{y}</text>
          </g>
        ))}
        {/* candidate row band */}
        <rect x={0} y={Y(rowOf.get(a.k)) - ROW / 2} width={width} height={ROW} className="self-band" />

        {/* citation edges: from citing device to its predicate */}
        {[...nodes.values()].filter((n) => n.parent).map((n) => {
          const [from, to] = n.side === 'up' ? [n.parent, n.k] : [n.k, n.parent]
          const f = nodes.get(from), g = nodes.get(to)
          if (!f || !g || !f.decision_date || !g.decision_date) return null
          const xa = X(t(f.decision_date)), ya = Y(rowOf.get(from))
          const xb = X(t(g.decision_date)), yb = Y(rowOf.get(to))
          const on = hlEdge.has(from + '>' + to) || hlEdge.has(to + '>' + from)
          const mx = (xa + xb) / 2
          return (
            <path key={from + to} d={`M${xa - 6},${ya} C${mx},${ya} ${mx},${yb} ${xb + 7},${yb}`}
              className={'edge' + (on ? ' on' : '') + (hl.size && !on ? ' dim' : '')} markerEnd="url(#arrow)" />
          )
        })}
        <defs>
          <marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
            <path d="M 0 0 L 10 5 L 0 10 z" className="arrowhead" />
          </marker>
        </defs>

        {order.map((k, i) => {
          const n = nodes.get(k)
          if (!n.decision_date) return null
          const x = X(t(n.decision_date)), y = Y(i)
          const st = status(n)
          const dim = hl.size && !hl.has(k)
          return (
            <g key={k} className={'row' + (dim ? ' dim' : '')} onMouseEnter={() => setHover(k)} onMouseLeave={() => setHover(null)}
              onClick={() => onPick && k !== a.k && onPick(k)} style={{ cursor: k === a.k ? 'default' : 'pointer' }}>
              <rect x={0} y={y - ROW / 2} width={width} height={ROW} className={'row-hit' + (hover === k ? ' hov' : '')} />
              {(n.recalls || []).map((r) => r.initiated && (
                <g key={r.id}>
                  <line x1={x} x2={X(t(r.initiated))} y1={y} y2={y} className={'recall-link ' + (r.design_related ? 'design' : 'other')} />
                  <path d={`M${X(t(r.initiated))},${y - 5} l5,5 l-5,5 l-5,-5 z`} className={'diamond ' + (r.design_related ? 'design' : 'other')}>
                    <title>{`${r.id} · ${r.classification || 'unclassified'} · ${r.root_cause} · initiated ${r.initiated}`}</title>
                  </path>
                </g>
              ))}
              <circle cx={x} cy={y} r={k === a.k ? 7 : 5.5} className={`node ${st} ${n.lineage_known === false ? 'unknown' : ''} ${k === a.k ? 'self' : ''}`} />
              <text x={width - LABEL_W + 8} y={y + 4} className="label">
                <tspan className="lk">{k}</tspan>
                <tspan dx="6" className="ln">{(n.name || '').slice(0, 26)}</tspan>
              </text>
              <text x={width - LABEL_W - 4} y={y + 4} textAnchor="end" className="gen">
                {n.side === 'self' ? 'candidate' : n.side === 'up' ? `G-${n.gen}` : `D+${n.gen}`}
              </text>
            </g>
          )
        })}
      </svg>
      {hover && nodes.get(hover) && (
        <div className="chart-tip">
          <b>{hover}</b> · {nodes.get(hover).name}<br />
          {nodes.get(hover).applicant} · cleared {nodes.get(hover).decision_date}<br />
          {(nodes.get(hover).recalls || []).length} recall record(s)
          {nodes.get(hover).lineage_known === false && <><br /><i>own predicates not read (summary {nodes.get(hover).summary_status})</i></>}
        </div>
      )}
    </div>
  )
}
