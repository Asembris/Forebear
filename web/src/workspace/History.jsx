import React, { useEffect, useState } from 'react'
import { api, reportUrl } from '../api.js'
import { VERDICTS } from '../evidence.js'

/* Everything that was saved or run against the graph: assessments first (deterministic), agent runs second. */
export default function History({ go }) {
  const [assess, setAssess] = useState(null)
  const [runs, setRuns] = useState(null)
  const [props, setProps] = useState(null)
  const [err, setErr] = useState(null)
  const load = () => {
    api.assessments().then(setAssess).catch((e) => setErr(e.message))
    api.investigations(null, 50).then(setRuns).catch(() => setRuns([]))
    api.proposals('pending_human_decision').then(setProps).catch(() => setProps([]))
  }
  useEffect(load, [])
  return (
    <div>
      <div className="page-head">
        <p className="eyebrow">Graph</p>
        <h1>Investigation history</h1>
        <p>Saved assessments and their staleness against today's graph, then optional agent runs and the proposals they left for a person.</p>
      </div>
      {err && <p className="err">{err}</p>}
      <section className="panel">
        <div className="panel-head"><h2>Saved assessments <span className="count">{assess?.length ?? '…'}</span></h2>
          <p className="hint">Stale means a citation in the ancestry was reviewed or re-ingested after saving.</p></div>
        {assess && assess.length === 0 && <p className="muted">None yet. Save one from any investigation.</p>}
        {assess && assess.length > 0 && (
          <div className="tbl-wrap"><table className="tbl">
            <thead><tr><th>Assessment</th><th>Device</th><th>Saved verdict</th><th>Now</th><th>Saved</th></tr></thead>
            <tbody>{assess.map((h) => (
              <tr key={h.id} className="click" tabIndex={0} onClick={() => go('check', h.k)} onKeyDown={(e) => e.key === 'Enter' && go('check', h.k)}>
                <td className="mono">{h.id}</td>
                <td><span className="k mono">{h.k}</span><div className="sub">{h.name}</div></td>
                <td><span className={`chip tone-${VERDICTS[h.verdict]?.tone || 'muted'}`}>{VERDICTS[h.verdict]?.label || h.verdict}</span></td>
                <td>{h.stale ? <span className="stale">Stale{h.verdict_now !== h.verdict ? ` · now ${VERDICTS[h.verdict_now]?.label || h.verdict_now}` : ''}</span> : <span className="ok">Current</span>}</td>
                <td className="sub num">{h.created_at?.slice(0, 16).replace('T', ' ')}</td>
              </tr>))}</tbody>
          </table></div>
        )}
      </section>
      <section className="panel">
        <div className="panel-head"><h2>Agent runs (optional) <span className="count">{runs?.length ?? '…'}</span></h2></div>
        <p className="lede">Machine findings, verified against tool results but never human-approved. Deterministic assessments remain the authoritative record.</p>
        {runs && runs.length === 0 && <p className="muted">No agent runs in this store. They can be started from the command line or the API (see README).</p>}
        {runs && runs.length > 0 && (
          <div className="tbl-wrap"><table className="tbl">
            <thead><tr><th>Run</th><th>Target</th><th>Status</th><th>Mode</th><th>Pending proposals</th><th /></tr></thead>
            <tbody>{runs.map((r) => (
              <tr key={r.id}>
                <td className="mono">{r.id}<div className="sub">{r.created_at?.slice(0, 16).replace('T', ' ')}</div></td>
                <td><a href={`#/check/${r.target_k}`} className="k mono">{r.target_k}</a></td>
                <td><span className="chip">{r.status}</span>{r.stale && <span className="stale"> · stale</span>}</td>
                <td className="sub">{r.mode}{r.model_used ? ` · ${r.model_used}` : ''}</td>
                <td className="num">{r.pending_proposals}</td>
                <td><a href={reportUrl(r.id)} target="_blank" rel="noreferrer">Report ↗</a></td>
              </tr>))}</tbody>
          </table></div>
        )}
      </section>
      <section className="panel">
        <div className="panel-head"><h2>Proposals awaiting a person <span className="count">{props?.length ?? '…'}</span></h2></div>
        {props && props.length === 0 && <p className="muted">None pending.</p>}
        {props && props.map((p) => <Proposal key={p.id} p={p} onDone={load} />)}
      </section>
    </div>
  )
}

function Proposal({ p, onDone }) {
  const [name, setName] = useState('')
  const [human, setHuman] = useState(false)
  const [msg, setMsg] = useState(null)
  const decide = async (d) => {
    try { await api.decide(p.id, d, name.trim()); setMsg({ ok: true, text: `Recorded: ${d}.` }); onDone() }
    catch (e) { setMsg({ ok: false, text: e.message }) }
  }
  return (
    <div className="review-item tone-muted">
      <h3><span className="sev sev-info">{p.kind}</span><span className="mono">{p.id}</span>
        <span>{p.k || `${p.src} → ${p.dst}`}</span></h3>
      {p.reason && <p className="muted small" style={{ margin: '0 0 8px' }}>{p.reason}</p>}
      <div className="cit-a">
        <input className="field" style={{ maxWidth: 220 }} placeholder="Your name" value={name} onChange={(e) => setName(e.target.value)} aria-label="Your name" />
        <label className="small"><input type="checkbox" checked={human} onChange={(e) => setHuman(e.target.checked)} /> I am a person deciding this</label>
        <button className="btn btn-line btn-sm" disabled={!human || name.trim().length < 2} onClick={() => decide('approve')}>Approve</button>
        <button className="btn btn-quiet btn-sm" disabled={!human || name.trim().length < 2} onClick={() => decide('dismiss')}>Dismiss</button>
      </div>
      {msg && <p className={msg.ok ? 'ok' : 'err'}>{msg.text}</p>}
    </div>
  )
}
