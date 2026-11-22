import React, { useEffect, useMemo, useRef, useState } from 'react'
import { edgeStatus, EDGE_STATUS, nodeTone, shortName, year } from '../evidence.js'

/*
  The lineage as the film left it: generation columns, newest on the right, threads pointing back in
  time to the cited predicate. Progressive disclosure: by default the verdict window (two generations)
  plus every node on a chain that raised a review signal; deeper generations expand on request.
  Every node and every thread is a keyboard-focusable control that opens its provenance.
*/

const ROW = 70, PAD_X = 110, PAD_T = 46, PAD_B = 62, MIN_COL = 190, MAX_COL = 300

export function criticalChains(a) {
  return a.signals.filter((s) => (s.severity === 'high' || s.severity === 'medium') && s.chain?.length > 1).map((s) => s.chain)
}

export function buildModel(a, { depth, descendants }) {
  const nodes = new Map()
  const crit = criticalChains(a)
  const critK = new Set(crit.flat())
  const critE = new Set()
  crit.forEach((c) => c.slice(1).forEach((k, i) => critE.add(c[i] + '>' + k)))
  nodes.set(a.k, { ...a.device, k: a.k, gen: 0, side: 'self', recalls: a.device.recalls || [] })
  let hidden = 0, hiddenGens = new Set()
  for (const x of a.ancestors) {
    if (x.gen <= depth || critK.has(x.k)) nodes.set(x.k, { ...x, side: 'up' })
    else { hidden++; hiddenGens.add(x.gen) }
  }
  if (descendants) for (const x of a.descendants) nodes.set(x.k, { ...x, side: 'down' })
  const edges = new Map()
  const addHops = (hops) => {
    for (const h of hops || []) {
      if (!nodes.has(h.src) || !nodes.has(h.dst)) continue
      const id = h.src + '>' + h.dst
      if (!edges.has(id)) edges.set(id, { id, hop: h, status: edgeStatus(h), critical: critE.has(id) })
    }
  }
  for (const x of a.ancestors) if (nodes.has(x.k)) addHops(x.hops)
  if (descendants) for (const x of a.descendants) addHops(x.hops)
  return { nodes, edges, hidden, hiddenGens: [...hiddenGens].sort(), critK, critE }
}

function layout(model, avail) {
  const { nodes, edges } = model
  const parent = new Map()
  for (const n of nodes.values()) if (n.chain?.length > 1) parent.set(n.k, n.chain[n.chain.length - 2])
  const ancGens = [...nodes.values()].filter((n) => n.side === 'up').map((n) => n.gen)
  const descGens = [...nodes.values()].filter((n) => n.side === 'down').map((n) => n.gen)
  const maxA = ancGens.length ? Math.max(...ancGens) : 0
  const maxD = descGens.length ? Math.max(...descGens) : 0
  const colOf = (n) => (n.side === 'self' ? maxA : n.side === 'up' ? maxA - n.gen : maxA + n.gen)
  const cols = new Map()
  for (const n of nodes.values()) {
    const c = colOf(n)
    if (!cols.has(c)) cols.set(c, [])
    cols.get(c).push(n)
  }
  const y = new Map([[[...nodes.values()].find((n) => n.side === 'self').k, 0]])
  // place outward from the candidate, ordering each column by its parents (fewer crossings)
  const order = [...cols.keys()].sort((p, q) => Math.abs(p - maxA) - Math.abs(q - maxA))
  const maxRows = Math.max(...[...cols.values()].map((c) => c.length))
  for (const c of order) {
    const list = cols.get(c)
    list.sort((p, q) => {
      const py = y.get(parent.get(p.k)) ?? 0, qy = y.get(parent.get(q.k)) ?? 0
      return py - qy || (q.decision_date || '').localeCompare(p.decision_date || '')
    })
    list.forEach((n, i) => { if (n.side !== 'self') y.set(n.k, (i - (list.length - 1) / 2) * ROW) })
  }
  const span = maxA + maxD
  const COL = span ? Math.max(MIN_COL, Math.min(MAX_COL, (avail - PAD_X * 2) / span)) : MAX_COL
  const width = Math.max(avail, PAD_X * 2 + span * COL)
  const X0 = PAD_X + (width - (PAD_X * 2 + span * COL)) / 2
  const height = PAD_T + PAD_B + Math.max(1, maxRows) * ROW
  const mid = PAD_T + (Math.max(1, maxRows) * ROW) / 2
  const pos = new Map([...nodes.values()].map((n) => [n.k, { x: X0 + colOf(n) * COL, y: mid + y.get(n.k) }]))
  const colLabels = [...cols.keys()].map((c) => {
    const g = c - maxA
    return { x: X0 + c * COL, label: g === 0 ? 'Candidate' : g < 0 ? (g === -1 ? 'Predicates' : g === -2 ? 'Grand-predicates' : `Generation ${-g}`) : `Cites it · +${g}` }
  })
  return { pos, width, height, colLabels, edges }
}

export default function EvidenceGraph({ a, depth, onDepth, descendants, selected, onSelect, focusChain }) {
  const model = useMemo(() => buildModel(a, { depth, descendants }), [a, depth, descendants])
  const wrap = useRef(null)
  const [avail, setAvail] = useState(900)
  useEffect(() => {
    const on = () => wrap.current && setAvail(wrap.current.clientWidth)
    on()
    const ro = new ResizeObserver(on)
    ro.observe(wrap.current)
    return () => ro.disconnect()
  }, [])
  const L = useMemo(() => layout(model, avail), [model, avail])
  const [hover, setHover] = useState(null)
  useEffect(() => {
    const w = wrap.current
    if (w) w.scrollLeft = w.scrollWidth   // the candidate sits on the right: start there
  }, [a.k, L.width])

  const hoverPath = useMemo(() => {
    const k = hover || null
    if (!k) return focusChain ? new Set(focusChain) : null
    const n = model.nodes.get(k)
    return new Set(n?.chain || [k])
  }, [hover, model, focusChain])
  const onPath = (id) => {
    if (!hoverPath) return true
    const [s, d] = id.split('>')
    return hoverPath.has(s) && hoverPath.has(d)
  }
  const nodeLabel = (n) => {
    const rs = n.recalls || []
    const design = rs.filter((r) => r.design_related).length
    return `${n.k}, ${n.name || 'unnamed'}, cleared ${n.decision_date || 'date unknown'}. ` +
      (n.side === 'self' ? 'Candidate. ' : n.side === 'up' ? `Generation ${n.gen} predicate. ` : `Cites the candidate, ${n.gen} generation(s) later. `) +
      (rs.length ? `${rs.length} recall record(s), ${design} design-related. ` : 'No recall records. ') +
      (n.lineage_known === false ? 'Its own predicates were not read.' : '')
  }
  const key = (fn) => (e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); fn() } }

  return (
    <div>
      <div className="graph-wrap" ref={wrap} data-testid="evidence-graph">
        <svg width={L.width} height={L.height} role="group" aria-label={`Predicate lineage graph for ${a.k}: ${model.nodes.size} devices, ${model.edges.size} citations`}>
          {L.colLabels.map((c) => (
            <g key={c.x}>
              <line className="g-col-rule" x1={c.x} x2={c.x} y1={30} y2={L.height - 10} />
              <text className="g-col-label" x={c.x} y={20} textAnchor="middle">{c.label}</text>
            </g>
          ))}
          {[...model.edges.values()].map((e) => {
            const s = L.pos.get(e.hop.src), d = L.pos.get(e.hop.dst)
            const mx = (s.x + d.x) / 2
            const path = `M${s.x - 12},${s.y} C${mx},${s.y} ${mx},${d.y} ${d.x + 12},${d.y}`
            const st = e.status.key
            const dim = !onPath(e.id)
            const isSel = selected?.type === 'edge' && selected.id === e.id
            return (
              <g key={e.id} className="g-edge-g" tabIndex={0} role="button"
                aria-label={`Citation: ${e.hop.src} cites ${e.hop.dst}${e.hop.page ? `, page ${e.hop.page}` : ''}. ${EDGE_STATUS[st].label}. Open provenance.`}
                aria-pressed={isSel}
                onClick={() => onSelect({ type: 'edge', id: e.id, hop: e.hop })} onKeyDown={key(() => onSelect({ type: 'edge', id: e.id, hop: e.hop }))}>
                <path d={path} className={`g-edge st-${st}${e.critical ? ' is-critical' : ''}${dim ? ' is-dim' : ''}`}
                  style={isSel ? { opacity: 1, strokeWidth: 3.2 } : undefined} />
                {e.critical && !dim && <path d={path} className="g-flow" />}
                <path d={path} className="g-edge-hit" />
                <rect x={mx - 22} y={(s.y + d.y) / 2 - 9} width={44} height={18} rx={9} fill="transparent" style={{ cursor: 'pointer' }} />
                <title>{`${e.hop.src} → ${e.hop.dst} · p.${e.hop.page ?? '?'} · ${EDGE_STATUS[st].label}`}</title>
              </g>
            )
          })}
          {[...model.nodes.values()].map((n) => {
            const p = L.pos.get(n.k)
            const tone = nodeTone(n)
            const self = n.side === 'self'
            const r = self ? 11 : 8
            const dim = hoverPath && !hoverPath.has(n.k)
            const isSel = selected?.type === 'node' && selected.k === n.k
            return (
              <g key={n.k} transform={`translate(${p.x},${p.y})`} tabIndex={0} role="button" aria-label={nodeLabel(n)} aria-pressed={isSel}
                className={`g-node${self ? ' is-self' : ''}${dim ? ' is-dim' : ''}${isSel ? ' is-selected' : ''}`} data-k={n.k}
                onMouseEnter={() => setHover(n.k)} onMouseLeave={() => setHover(null)} onFocus={() => setHover(n.k)} onBlur={() => setHover(null)}
                onClick={() => onSelect({ type: 'node', k: n.k })} onKeyDown={key(() => onSelect({ type: 'node', k: n.k }))}>
                {tone === 'design' && !self && <circle className="glow" r={r * 2.2} />}
                <circle className="halo" r={r + 5} />
                <circle className={`dot tone-${tone}${n.lineage_known === false ? ' unread' : ''}`} r={r} />
                <text className="lk" y={-r - 9} textAnchor="middle">{n.k}</text>
                <text className="ln" y={r + 16} textAnchor="middle">{shortName(n.name, 26)} · {year(n.decision_date)}</text>
              </g>
            )
          })}
          {model.hidden > 0 && (
            <g className="g-more" tabIndex={0} role="button" transform={`translate(14, ${L.height - 40})`}
              aria-label={`Show ${model.hidden} more ancestors in generations ${model.hiddenGens.join(', ')}`}
              onClick={() => onDepth(Math.max(...model.hiddenGens))} onKeyDown={key(() => onDepth(Math.max(...model.hiddenGens)))}>
              <rect width="212" height="28" rx="14" />
              <text x="106" y="18.5" textAnchor="middle">+ {model.hidden} more in generation{model.hiddenGens.length > 1 ? `s ${model.hiddenGens[0]}–${model.hiddenGens[model.hiddenGens.length - 1]}` : ` ${model.hiddenGens[0]}`}</text>
            </g>
          )}
        </svg>
      </div>
      <div className="g-legend" aria-label="Legend">
        <span className="sw"><i className="lg-design" />design-related recall</span>
        <span className="sw"><i className="lg-recall" />other recall</span>
        <span className="sw"><i className="lg-clean" />no recall record</span>
        <span className="sw"><i className="lg-unread" />own predicates unread</span>
        <span className="sep" aria-hidden="true" />
        {['confirmed', 'extracted', 'disputed', 'conditional'].map((s) => (
          <span key={s} className={`status status-${s}`}><span className="line" />{EDGE_STATUS[s].short}</span>
        ))}
        <span className="status" style={{ color: 'var(--amber)' }}><span className="line" />critical chain</span>
      </div>
      <div className="graph-hint">Select any device or thread for its record, quote, page and source PDF. Tab moves between them; Enter opens.</div>
    </div>
  )
}
