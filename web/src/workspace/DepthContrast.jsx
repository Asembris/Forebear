import React, { useEffect, useState } from 'react'
import { api } from '../api.js'
import { fmtDate, pdfAt, verdictView } from '../evidence.js'
import { depthContrast, excerpt, strong } from './depth.js'

function Verdict({ a }) {
  const v = verdictView(a.verdict, a.coverage.evidence)
  return <div className={`dc-verdict tone-${v.tone}`}><i aria-hidden="true" />{v.label}</div>
}

function Excerpt({ hop }) {
  const x = excerpt(hop.snippet || hop.quote, hop.dst)
  return <span className="dc-q">“{x.head}{x.k && <mark>{x.k}</mark>}{x.tail}”</span>
}

const join = (xs) => xs.length < 2 ? xs : xs.flatMap((x, i) => (i === 0 ? [x] : [i === xs.length - 1 ? ' and ' : ', ', x]))

/* Depth 1 against depth 2 for the same clearance: what a one-generation lookup reports, and what one more hop
   of the Relate query finds. Every claim links to the FDA page or recall record behind it. */
export default function DepthContrast({ a, onSelect }) {
  const [pair, setPair] = useState(null)
  // only when every strong signal sits beyond the direct predicates: otherwise depth 1 already finds it, so skip the extra queries
  const worth = a.depth >= 2 && a.signals.some((s) => strong(s) && s.chain?.length > 2)
    && !a.signals.some((s) => strong(s) && (s.chain?.length || 0) <= 2)
  useEffect(() => {
    setPair(null)
    if (!worth) return
    let live = true
    Promise.all([api.assess(a.k, 1), api.assess(a.k, 2)]).then(([one, two]) => { if (live) setPair([one, two]) }).catch(() => {})
    return () => { live = false }
  }, [a.k, worth])
  const c = pair && depthContrast(pair[0], pair[1])
  if (!c) return null
  const { recall: r, predicate: p, timing } = c
  const edge = (hop) => onSelect({ type: 'edge', id: hop.src + '>' + hop.dst, hop })
  const holderKs = c.fanout.map((x) => <span key={x.device.k} className="k">{x.device.k}</span>)
  return (
    <section className="panel depth-contrast corner-marks" aria-labelledby="dc-title" data-testid="depth-contrast">
      <div className="panel-head">
        <h2 id="dc-title">Why the graph matters <span className="count">same clearance, same rules, one generation deeper</span></h2>
        <p className="hint">Depth is the number of predicate generations the Relate query walks.</p>
      </div>
      <div className="dc-grid">
        <div className="dc-col" data-testid="depth-1">
          <p className="dc-depth"><b>Depth 1</b> · direct predicates only</p>
          <Verdict a={c.shallow} />
          <p>
            <span className="k">{c.k}</span> cites <span className="k">{p.k}</span> ({p.name.split(',')[0]}).{' '}
            {c.predicateRecalls === 0 ? <>FDA's recall records in this dataset name no recall for {p.k}.</>
              : <>FDA's recall records list {c.predicateRecalls} record(s) for {p.k}, none of them design-related.</>}
            {' '}A one-hop lookup stops here.
          </p>
        </div>
        <div className="dc-step" aria-hidden="true"><span>+1 hop</span></div>
        <div className="dc-col is-deep" data-testid="depth-2">
          <p className="dc-depth"><b>Depth 2</b> · one Relate query, two hops</p>
          <Verdict a={c.deep} />
          <p>
            <span className="k">{p.k}</span> itself cites {join(holderKs)}.
            {' '}FDA lists {c.fanout.length > 1 ? 'both' : 'it'} on <a className="mono" href={r.url} target="_blank" rel="noreferrer">{r.id}</a>, a{' '}
            <span className="amber">{r.classification} · {r.root_cause}</span> recall that began {fmtDate(r.initiated)}
            {timing?.relation === 'before' && <>, <span className="amber">{timing.duration} before</span> {c.k} was cleared</>}.
          </p>
        </div>
      </div>
      <ol className="dc-route" aria-label="Evidence route, from the candidate's summary to the recall">
        {c.steps.map(({ device: d, hop }) => hop && (
          <li key={hop.src + hop.dst}>
            <span className="dc-n mono">{hop.src} → {d.k}</span>
            <Excerpt hop={hop} />
            <span className="dc-a">
              <a href={pdfAt(hop.source_url, hop.page)} target="_blank" rel="noreferrer">{hop.src} summary PDF, p.{hop.page} ↗</a>
              <button className="btn btn-quiet btn-sm" onClick={() => edge(hop)}>Provenance</button>
            </span>
          </li>
        ))}
        {c.fanout.map(({ device: d, hop }) => (
          <li key={hop.src + hop.dst}>
            <span className="dc-n mono">{hop.src} → {d.k}</span>
            <Excerpt hop={hop} />
            <span className="dc-a">
              <a href={pdfAt(hop.source_url, hop.page)} target="_blank" rel="noreferrer">{hop.src} summary PDF, p.{hop.page} ↗</a>
              <button className="btn btn-quiet btn-sm" onClick={() => edge(hop)}>Provenance</button>
            </span>
          </li>
        ))}
        <li className="is-recall">
          <span className="dc-n mono">{r.id}</span>
          <span className="dc-q">{r.classification} · {r.root_cause} · event {r.event} · began {fmtDate(r.initiated)}. FDA's record lists {join(holderKs)}
            {c.predicateOnRecall ? <>, and <span className="k">{p.k}</span></> : <>, not <span className="k">{p.k}</span></>}.</span>
          <span className="dc-a"><a href={r.url} target="_blank" rel="noreferrer">FDA recall record ↗</a>
            <button className="btn btn-quiet btn-sm" onClick={() => onSelect({ type: 'node', k: c.fanout[0]?.device.k })}>Open {c.fanout[0]?.device.k}</button></span>
        </li>
      </ol>
      <p className="dc-foot muted small">A documentation signal for the predicate rationale, not a safety finding about {c.k}. FDA attributes the recall to
        product families that list these clearances; it does not say which model was affected.</p>
    </section>
  )
}
