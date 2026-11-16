import React, { useEffect, useRef, useState } from 'react'
import { api, pmnUrl } from './api.js'
import LineageChart from './LineageChart.jsx'

const VERDICT = {
  DESIGN_RECALL_ON_FILE: { cls: 'v-avoid', label: 'Design-related recall on file' },
  REVIEW_LINEAGE: { cls: 'v-review', label: 'Review lineage' },
  INSUFFICIENT_LINEAGE: { cls: 'v-unknown', label: 'Lineage not checkable' },
  NO_DESIGN_RECALL_SIGNAL: { cls: 'v-clear', label: 'No design-recall signal' },
}

export default function CheckView({ k, go, onChanged }) {
  const [a, setA] = useState(null)
  const [err, setErr] = useState(null)
  const [loading, setLoading] = useState(false)
  const [hl, setHl] = useState(null)
  const [depth, setDepth] = useState(4)
  const [saved, setSaved] = useState(null)
  const [history, setHistory] = useState([])
  const wrap = useRef(null)
  const [w, setW] = useState(1080)

  const load = () => {
    if (!k) return
    setLoading(true); setErr(null); setSaved(null); setHl(null)
    api.assess(k, depth).then(setA).catch((e) => { setA(null); setErr(e.message) }).finally(() => setLoading(false))
    api.assessments(k).then(setHistory).catch(() => setHistory([]))
  }
  useEffect(load, [k, depth])
  useEffect(() => {
    const on = () => wrap.current && setW(Math.max(720, wrap.current.clientWidth - 2))
    on(); window.addEventListener('resize', on); return () => window.removeEventListener('resize', on)
  }, [a])

  if (!k) return <Landing go={go} />
  if (loading && !a) return <div className="card muted">Querying the Relate graph for {k}…</div>
  if (err) return (
    <div className="card error">
      <b>{err}</b>
      {err.includes('not in the graph') && <p><button onClick={() => go('ingest', k)}>Ingest {k} from FDA now →</button></p>}
    </div>
  )
  if (!a) return null
  const d = a.device
  const v = VERDICT[a.verdict]
  const strong = a.signals.filter((s) => s.severity === 'high' || s.severity === 'medium')

  const save = async () => {
    const note = window.prompt('Optional analyst note to store with this assessment (Cancel = do not save):', '')
    if (note === null) return
    try { const r = await api.save(k, note); setSaved(r); setHistory(await api.assessments(k)); onChanged && onChanged() }
    catch (e) { setSaved({ error: e.message }) }
  }

  return (
    <div className="check" ref={wrap}>
      <section className="card head">
        <div className="head-main">
          <div className="kline">
            <span className="k">{a.k}</span>
            <span className="pc">{d.product_code}{d.product?.name ? ` · ${d.product.name}` : ''}</span>
          </div>
          <h1>{d.name}</h1>
          <div className="meta">{d.applicant} · cleared {d.decision_date} · {d.clearance_type || '510(k)'} ·{' '}
            <a href={pmnUrl(a.k)} target="_blank" rel="noreferrer">FDA record ↗</a>
            {d.summary_url && <> · <a href={d.summary_url} target="_blank" rel="noreferrer">510(k) summary PDF ↗</a></>}
          </div>
        </div>
        <div className={'verdict ' + v.cls}>
          <div className="vlabel">{v.label}</div>
          <div className="vreason">{a.verdict_reason}</div>
          <div className="vactions">
            <button onClick={save}>Save assessment to graph</button>
            <button className="ghost" onClick={() => go('compare', a.k)}>Compare…</button>
          </div>
          {saved && (saved.error ? <div className="err">{saved.error}</div>
            : <div className="ok">Saved {saved.id} to Relate: linked to {saved.flagged_recalls.length} flagged recall(s)</div>)}
        </div>
      </section>

      <section className="card">
        <div className="section-title">
          <h2>Lineage timeline</h2>
          <div className="legend">
            <span><i className="dot design" /> has design-related recall</span>
            <span><i className="dot recall" /> other recall</span>
            <span><i className="dot clean" /> no recall record</span>
            <span><i className="dot unknown" /> own predicates unread</span>
            <span><i className="dia" /> recall initiated</span>
            <label>generations <select value={depth} onChange={(e) => setDepth(+e.target.value)}>
              {[1, 2, 3, 4, 5, 6].map((n) => <option key={n}>{n}</option>)}</select></label>
          </div>
        </div>
        <p className="hint">
          {a.ancestors.length} predicate ancestors and {a.descendants.length} later devices that cite this one, read from
          510(k) summaries and joined to FDA recall records in Relate. Arrows point to the cited predicate. Click a row to check that device.
          {' '}<b>By hand</b> this means opening {1 + a.ancestors.filter((x) => x.lineage_known).length} summary PDFs one generation at a time
          and running {1 + a.ancestors.length} separate recall-database searches; here it is one graph query.
        </p>
        <LineageChart a={a} highlight={hl} onPick={(kk) => go('check', kk)} width={w - 34} />
      </section>

      <div className="grid2">
        <section className="card">
          <h2>Signals <span className="count">{strong.length} need review</span></h2>
          {a.signals.length === 0 && <p className="muted">No recall records anywhere in the readable ancestry.</p>}
          {a.signals.map((s, i) => <Signal key={i} s={s} active={hl && s.chain && hl.join() === s.chain.join()}
            onHover={() => s.chain?.length > 1 && setHl(s.chain)} onLeave={() => setHl(null)} go={go} />)}
        </section>
        <aside className="col">
          <section className="card memo">
            <h2>Due-diligence note</h2>
            <div className="memo-src">{a.memo.source}</div>
            <p><b>{a.memo.headline}</b></p>
            {a.memo.paragraphs.map((p, i) => <p key={i}>{p.text}</p>)}
            <button className="ghost" onClick={() => navigator.clipboard?.writeText(
              a.memo.headline + '\n\n' + a.memo.paragraphs.map((p) => p.text).join('\n\n'))}>Copy note</button>
          </section>
          <Citations a={a} reload={load} go={go} />
          <section className="card">
            <h2>Saved assessments</h2>
            {history.length === 0 ? <p className="muted">None yet for {a.k}.</p> : history.map((h) => (
              <div key={h.id} className="hist"><b>{h.id}</b> · {h.created_at?.slice(0, 16).replace('T', ' ')} · <span className={'pill ' + VERDICT[h.verdict]?.cls}>{h.verdict}</span>
                <span className="muted"> · {h.flagged.length} flagged recall(s)</span>
                {h.stale && <div className="stale">Stale: the graph changed after this was saved
                  {h.verdict_now !== h.verdict && <> (verdict now <b>{h.verdict_now}</b>)</>}
                  {h.changed_edges?.length > 0 && <> · reviewed links: {h.changed_edges.join(', ')}</>}
                  {h.reingested?.length > 0 && <> · re-ingested: {h.reingested.join(', ')}</>}</div>}</div>
            ))}
          </section>
        </aside>
      </div>
    </div>
  )
}

function Signal({ s, onHover, onLeave, active, go }) {
  const [open, setOpen] = useState(s.severity === 'high' || s.severity === 'medium')
  const recalls = s.evidence.filter((e) => e.type === 'recall')
  const hops = s.evidence.filter((e) => e.type === 'citation')
  const devices = s.evidence.filter((e) => e.type === 'device')
  return (
    <div className={`signal sev-${s.severity}${active ? ' active' : ''}`} onMouseEnter={onHover} onMouseLeave={onLeave}>
      <div className="sig-head" onClick={() => setOpen(!open)}>
        <span className={'sev ' + s.severity}>{s.severity}</span>
        <span className="sig-title">{s.title}</span>
        <span className="chev">{open ? '−' : '+'}</span>
      </div>
      {open && (
        <div className="sig-body">
          {s.chain?.length > 1 && (
            <div className="chain">{s.chain.map((c, i) => (
              <React.Fragment key={c}>{i > 0 && <span className="arr">cites →</span>}
                <a onClick={() => go('check', c)}>{c}</a></React.Fragment>))}
            </div>
          )}
          {hops.map((h, i) => (
            <div key={i} className="hop">
              <div className="hop-h">{h.src} → {h.dst} · page {h.page}
                {h.source_url && <a href={h.source_url} target="_blank" rel="noreferrer"> summary PDF ↗</a>}
                {h.review && <span className={'pill ' + h.review}>{h.review}</span>}
                {h.name_check === 'mismatch' && <span className="pill mismatch" title={"The cited device's openFDA name does not appear near this citation: possibly a K-number typo in the PDF, or just a name variant / OCR noise. Verify before relying on it."}>name ≠ FDA record</span>}</div>
              <q>{h.snippet}</q>
            </div>
          ))}
          {recalls.slice(0, 6).map((r) => (
            <div key={r.id} className="rec">
              <div className="rec-h">
                <span className={'pill ' + (r.design_related ? 'design' : 'other')}>{r.design_related ? 'design-related' : 'other cause'}</span>
                <b>{r.id}</b> · {r.classification || 'unclassified'} · {r.root_cause} · initiated {r.initiated} · {r.firm}
                {r.url && <a href={r.url} target="_blank" rel="noreferrer"> FDA recall ↗</a>}
              </div>
              {r.reason && <div className="rec-r">{r.reason}</div>}
            </div>
          ))}
          {recalls.length > 6 && <div className="muted">+ {recalls.length - 6} more recall record(s)</div>}
          {devices.length > 0 && <div className="trunc">{devices.map((x) => (
            <span key={x.k}><a onClick={() => go('ingest', x.k)}>{x.k}</a> <small>{x.summary_status}</small></span>))}
            <div className="muted">Click a device to read its summary and extend the lineage.</div>
          </div>}
        </div>
      )}
    </div>
  )
}

function Citations({ a, reload, go }) {
  const [busy, setBusy] = useState(null)
  const [msg, setMsg] = useState(null)
  const act = async (c, fn, label) => {
    setBusy(c.dst + label); setMsg(null)
    try { const r = await fn(); setMsg(label === 'ai' ? `AI labelled ${c.dst} as "${r.ai_label}" (${r.model.split('/')[1]}, ${r.seconds}s), quote: “${r.quote}”` : null); reload() }
    catch (e) { setMsg(e.message) } finally { setBusy(null) }
  }
  return (
    <section className="card">
      <h2>What {a.k} cites <span className="count">{a.citations.length}</span></h2>
      <p className="hint">Extracted from the 510(k) summary. Your review is written to the graph and changes every lineage query.</p>
      {a.device.lineage_known === false && <p className="muted">Summary not readable ({a.device.summary_status}).{' '}
        <a onClick={() => go('ingest', a.k)}>Try reading it now →</a></p>}
      {msg && <div className="note">{msg}</div>}
      {a.citations.map((c) => (
        <div key={c.dst} className={'cit ' + (c.review === 'rejected' ? 'rejected' : '')}>
          <div className="cit-h">
            <a onClick={() => go('check', c.dst)}><b>{c.dst}</b></a> <span className={'pill ' + c.kind}>{c.kind}</span>
            {c.ai_label && <span className="pill ai" title={c.ai_quote}>AI: {c.ai_label}</span>}
            {c.review && <span className={'pill ' + c.review}>{c.review}{c.reviewer === 'curated' ? ' (curated)' : ''}</span>}
            {c.name_check === 'mismatch' && <span className="pill mismatch" title={"The cited device's openFDA name does not appear near this citation: possibly a K-number typo in the PDF, or just a name variant / OCR noise. Verify before relying on it."}>name ≠ FDA record</span>}
            <span className="muted"> {c.name?.slice(0, 32)}</span>
          </div>
          <q>{c.snippet}</q>
          <div className="cit-a">
            <button disabled={!!busy} onClick={() => act(c, () => api.review(a.k, c.dst, c.review === 'confirmed' ? '' : 'confirmed'), 'ok')}>
              {c.review === 'confirmed' ? 'Unconfirm' : 'Confirm'}</button>
            <button disabled={!!busy} className="ghost" onClick={() => act(c, () => api.review(a.k, c.dst, c.review === 'rejected' ? '' : 'rejected'), 'no')}>
              {c.review === 'rejected' ? 'Restore' : 'Reject'}</button>
            {c.kind !== 'predicate' && <button disabled={!!busy} className="ghost" onClick={() => act(c, () => api.triage(a.k, c.dst), 'ai')}>
              {busy === c.dst + 'ai' ? 'Asking…' : 'Ask AI to label'}</button>}
            <span className="muted">p.{c.page}</span>
          </div>
        </div>
      ))}
    </section>
  )
}

function Landing({ go }) {
  return (
    <div className="landing">
      <section className="card hero">
        <h1>Before you cite a predicate, check its family.</h1>
        <p>
          Most moderate-risk devices reach the US market through a 510(k): the maker shows the new device is
          "substantially equivalent" to an already-cleared <i>predicate</i>, which was itself cleared against an older one.
          FDA's 2023 draft guidance on predicate selection recommends choosing predicates that have <b>not</b> been
          subject to a design-related recall. A JAMA study (Kadakia et al., 2023) found devices cleared on predicates
          with Class I recalls were associated with a 6.4-fold higher risk of their own Class I recall.
        </p>
        <p>
          FDA's own databases answer one hop at a time. Forebear reads the predicates out of every machine-readable 510(k) summary,
          links each clearance to the device it cites and to FDA recall records in a Relate graph, then walks the
          family tree in one query and shows the evidence for every link.
        </p>
        <div className="tryit">
          <div className="try-h">Try the real cases in the shipped dataset (CPAP, BiPAP and ventilators):</div>
          <button onClick={() => go('check', 'K252078')}><b>K252078</b> BreathePal Bilevel, cleared 2026</button>
          <button onClick={() => go('check', 'K251770')}><b>K251770</b> SleepRes PAP System, cleared 2025</button>
          <button onClick={() => go('check', 'K200480')}><b>K200480</b> DreamStation 2, cleared 2020</button>
          <button onClick={() => go('reach', '88058,88071')}><b>Recall 88058 + 88071</b>: the June 2021 Philips foam recall: who descends from it?</button>
        </div>
      </section>
    </div>
  )
}
