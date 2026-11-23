import React, { useEffect, useMemo, useState } from 'react'
import { api, pmnUrl, reportUrl } from '../api.js'
import {
  EDGE_STATUS, EVIDENCE_REASON_TEXT, VERDICTS, humanReview, countEvents, keyRecall, verdictView, edgeStatus, fmtDate, nodeTone, recallTiming, recallTimingText, shortName, year,
} from '../evidence.js'
import EvidenceGraph from './EvidenceGraph.jsx'
import Timeline from './Timeline.jsx'
import DepthContrast from './DepthContrast.jsx'
import Provenance, { Quote, RecallCard, deviceIn } from './Provenance.jsx'
import ReviewQueue, { reviewItems } from './Review.jsx'

/* The single most important chain: the highest-severity signal that walks the lineage. */
function topChain(a) {
  const strong = a.signals.filter((s) => (s.severity === 'high' || s.severity === 'medium') && s.chain?.length > 1)
  return strong.find((s) => !s.conditional) || strong[0] || null     // a supported route before a conditional one
}

/* One deterministic sentence that states the finding in plain words, built only from the assessment. */
function FindingSentence({ a }) {
  const d = a.device
  const sig = topChain(a)
  const own = a.signals.find((s) => s.code === 'DIRECT_RECALL' && s.severity !== 'info' && s.severity !== 'low')
  if (own && (!sig || own.severity === 'high')) {
    const r = keyRecall(own.evidence.filter((e) => e.type === 'recall'), null)
    return (
      <p className="finding-sentence" data-testid="finding-sentence">
        <span className="k">{a.k}</span> itself appears in FDA recall records
        {r && <>: a <span className="amber">{r.classification || 'unclassified'} {r.root_cause}</span> recall began {fmtDate(r.initiated)}</>}.
        {' '}Citing it as a predicate would need that addressed.
      </p>
    )
  }
  if (sig) {
    const holder = deviceIn(a, sig.chain[sig.chain.length - 1])
    const recs = sig.evidence.filter((e) => e.type === 'recall')
    const r = keyRecall(recs, d.decision_date)
    const first = sig.evidence.find((e) => e.type === 'citation' && e.src === a.k)
    const timing = r ? recallTiming(r.initiated, d.decision_date) : null
    const ev = countEvents(recs)
    return (
      <p className="finding-sentence" data-testid="finding-sentence">
        {shortName(d.name, 48)} cites <span className="k">{sig.chain[1]}</span>{first?.page ? <> on page {first.page} of its summary</> : null}.
        {' '}{sig.conditional ? <>The cited device <span className="k">{holder?.k}</span>, reached through a citation the audit could not resolve,</>
          : sig.chain.length > 2 ? <>Through it, {sig.gen === 2 ? 'grand-predicate' : `generation-${sig.gen} ancestor`} <span className="k">{holder?.k}</span></> : <>That predicate</>}
        {' '}({shortName(holder?.name, 52)}) is listed by FDA on {ev.events} recall event{ev.events === 1 ? '' : 's'} in this signal
        {r && <>, including a <span className="amber">{r.classification || 'unclassified'} {r.root_cause}</span> recall that began {fmtDate(r.initiated)}
          {timing && <>, {timing.relation === 'before'
            ? <><span className="amber">{timing.duration} before</span> {a.k} was cleared</>
            : recallTimingText(timing, a.k)}</>}</>}.
        {sig.conditional && <> This route is <b style={{ color: 'var(--violet)' }}>conditional</b>: it holds only if that citation is a predicate.</>}
      </p>
    )
  }
  return <p className="finding-sentence" data-testid="finding-sentence">{a.verdict_reason}</p>
}

function CriticalChain({ a, onSelect }) {
  const sig = topChain(a)
  if (!sig) return null
  const hops = sig.evidence.filter((e) => e.type === 'citation')
  const hopOf = (s, d) => hops.find((h) => h.src === s && h.dst === d) || deviceIn(a, d)?.hops?.find((h) => h.src === s && h.dst === d)
  const holderK = sig.chain[sig.chain.length - 1]
  const recs = sig.evidence.filter((e) => e.type === 'recall')
  const r = keyRecall(recs, a.device.decision_date)
  const timing = r ? recallTiming(r.initiated, a.device.decision_date) : null
  return (
    <section className="panel corner-marks" aria-labelledby="chain-title" data-testid="critical-chain">
      <div className="panel-head">
        <h2 id="chain-title">Critical chain <span className="count">predicate → recall, the route that raised the verdict</span></h2>
        <p className="hint">Select a thread for its page and quote.</p>
      </div>
      <div className="chain">
        {sig.chain.map((k, i) => {
          const n = deviceIn(a, k) || { k }
          const role = i === 0 ? 'Candidate' : sig.conditional ? 'Cited device · citation unresolved'
            : i === 1 ? 'Direct predicate' : i === 2 ? 'Grand-predicate' : `Generation ${i}`
          const isHolder = k === holderK
          const tone = isHolder ? nodeTone({ recalls: recs }) : 'none'
          const hop = i > 0 ? hopOf(sig.chain[i - 1], k) : null
          const st = hop ? edgeStatus(hop) : null
          return (
            <React.Fragment key={k}>
              {i > 0 && (
                <button className={`chain-link st-${st?.key || 'extracted'}`} onClick={() => hop && onSelect({ type: 'edge', id: hop.src + '>' + hop.dst, hop })}
                  aria-label={`${sig.chain[i - 1]} cites ${k}${hop?.page ? ` on page ${hop.page}` : ''}, ${EDGE_STATUS[st?.key || 'extracted'].label}. Open provenance.`}>
                  <span className="lbl">cites{hop?.page ? ` · p.${hop.page}` : ''}</span>
                  <span className="sub">{EDGE_STATUS[st?.key || 'extracted'].short}</span>
                </button>
              )}
              <button className={`chain-node${i === 0 ? ' is-self' : ''}${tone === 'design' ? ' tone-design' : ''}`}
                onClick={() => onSelect({ type: 'node', k })}>
                <span className="role">{role}</span>
                <span className="k">{k}</span>
                <span className="nm">{shortName(n.name, 44)}</span>
                <span className="dt">Cleared {fmtDate(n.decision_date)}</span>
                {isHolder && r && (
                  <span className="rc">
                    <span className={`chip tone-${r.design_related ? 'design' : 'class1'}`}>{r.classification || 'Unclassified'} · {r.root_cause}</span>
                    <span className="dt">Recall began {fmtDate(r.initiated)} · <span className="mono">{r.id}</span></span>
                  </span>
                )}
              </button>
            </React.Fragment>
          )
        })}
      </div>
      {r && timing && (
        <div className="chain-timing">
          <span className="chip tone-amber"><span className="glyph" />{recallTimingText(timing, a.k, 'chip')}</span>
          <span className="muted">{countEvents(recs).events} recall event(s) · {recs.length} product record(s) in this signal. Documentation signal, not a safety finding.</span>
        </div>
      )}
    </section>
  )
}

export default function Investigation({ k, go, onChanged }) {
  const [a, setA] = useState(null)
  const [err, setErr] = useState(null)
  const [loading, setLoading] = useState(false)
  const [depth, setDepth] = useState(4)
  const [shown, setShown] = useState(2)
  const [mode, setMode] = useState('graph')
  const [desc, setDesc] = useState(false)
  const [sel, setSel] = useState(null)
  const [focusChain, setFocusChain] = useState(null)
  const [assessments, setAssessments] = useState([])
  const [runs, setRuns] = useState([])

  const load = () => {
    setLoading(true); setErr(null)
    api.assess(k, depth).then((r) => { setA(r) }).catch((e) => { setA(null); setErr(e.message) }).finally(() => setLoading(false))
    api.assessments(k).then(setAssessments).catch(() => setAssessments([]))
    api.investigations(k, 10).then(setRuns).catch(() => setRuns([]))
  }
  useEffect(() => { setSel(null); setShown(2); load() }, [k, depth])

  if (err) return (
    <div className="panel" role="alert">
      <p className="err" style={{ fontSize: 15 }}>{err}</p>
      {err.includes('not in the graph') && <button className="btn btn-primary" onClick={() => go('ingest', k)}>Read {k} from FDA now <span className="arr">→</span></button>}
    </div>
  )
  if (!a) return (
    <div aria-busy="true">
      <div className="loading-thread"><i />Walking {k}'s lineage in the Relate graph…</div>
      <div className="skeleton" style={{ height: 210, marginBottom: 16 }} />
      <div className="skeleton" style={{ height: 160, marginBottom: 16 }} />
      <div className="skeleton" style={{ height: 380 }} />
    </div>
  )
  const d = a.device
  const cov = a.coverage
  const v = { ...VERDICTS[a.verdict], ...verdictView(a.verdict, cov.evidence) }
  const nReview = reviewItems(a).length
  const conditional = a.signals.filter((s) => s.conditional).length
  return (
    <div className="investigation" aria-busy={loading}>
      <section className={`finding tone-${v.tone}`} aria-labelledby="finding-title" data-testid="finding">
        <div className="finding-top">
          <div className="finding-id">
            <div className="kline">
              <span className="k">{a.k}</span>
              <span>{d.product_code}{d.product?.name ? ` · ${d.product.name}` : ''}</span>
            </div>
            <h1 id="finding-title">{d.name}</h1>
            <div className="meta">
              <span>{d.applicant}</span><span>Cleared {fmtDate(d.decision_date)}</span><span>{d.clearance_type || '510(k)'}</span>
              <a href={pmnUrl(a.k)} target="_blank" rel="noreferrer">FDA record ↗</a>
              {d.summary_url && <a href={d.summary_url} target="_blank" rel="noreferrer">510(k) summary PDF ↗</a>}
            </div>
          </div>
          <div className={`verdict tone-${v.tone}`} data-testid="verdict">
            <div className="verdict-label"><i aria-hidden="true" />{v.label}</div>
            <p className="verdict-reason">{a.verdict_reason}</p>
            <div className="verdict-actions">
              <button className="btn btn-line btn-sm" onClick={() => go('compare', a.k)}>Compare with other candidates</button>
            </div>
            <div className="authority">
              <svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.6" aria-hidden="true"><path d="M8 1.5l5.5 2v4.2c0 3.3-2.3 5.8-5.5 6.8-3.2-1-5.5-3.5-5.5-6.8V3.5z M5.5 8l1.8 1.8L10.8 6.3" /></svg>
              <span><b>Deterministic assessment</b> · {a.rules_version}. Authoritative within its documented scope: {cov.evidence_scope}, from
                machine-readable FDA records. A documentation signal, not a safety determination.</span>
            </div>
          </div>
        </div>
        <FindingSentence a={a} />
        <div className="coverage-row" aria-label="Evidence coverage">
          <span className={`chip tone-${cov.evidence === 'complete' ? 'calm' : cov.evidence === 'uncertain' ? 'alert' : 'muted'}`} title="Completeness of evidence inside the verdict window">
            Evidence {cov.evidence}</span>
          {(cov.evidence_reasons || []).map((c) => <span key={c} className="chip tone-muted" data-testid="evidence-reason">{EVIDENCE_REASON_TEXT[c] || c}</span>)}
          <span className="chip">{cov.ancestors} ancestors · {cov.generations_traversed} generations</span>
          {cov.ancestors_lineage_unknown > 0 && <span className="chip tone-muted">{cov.ancestors_lineage_unknown} with unread summaries</span>}
          {cov.doubtful_links > 0 && <span className="chip tone-alert">{cov.doubtful_links} doubtful link(s)</span>}
          {conditional > 0 && <span className="chip tone-violet">{conditional} conditional signal(s)</span>}
          {nReview > 0 && <a className="chip tone-blue" href="#review" onClick={(e) => { e.preventDefault(); document.getElementById('review')?.scrollIntoView({ block: 'start' }) }}>{nReview} item(s) need human review ↓</a>}
        </div>
      </section>

      <DepthContrast a={a} onSelect={setSel} />

      <CriticalChain a={a} onSelect={setSel} />

      <section className="panel" aria-labelledby="graph-title">
        <div className="panel-head">
          <h2 id="graph-title">Evidence graph <span className="count">{a.ancestors.length} ancestors · {a.descendants.length} later devices</span></h2>
          <div className="graph-tools">
            <div className="seg" role="group" aria-label="View">
              <button aria-pressed={mode === 'graph'} onClick={() => setMode('graph')}>Graph</button>
              <button aria-pressed={mode === 'timeline'} onClick={() => setMode('timeline')}>Timeline</button>
            </div>
            <label className="small muted">Show <select className="field" value={shown} onChange={(e) => setShown(+e.target.value)} aria-label="Generations shown">
              {Array.from({ length: depth }, (_, i) => i + 1).map((n) => <option key={n} value={n}>{n} gen</option>)}</select></label>
            <label className="small muted">Query <select className="field" value={depth} onChange={(e) => setDepth(+e.target.value)} aria-label="Generations traversed by the query">
              {[2, 3, 4, 5, 6].map((n) => <option key={n} value={n}>{n} gen</option>)}</select></label>
            {mode === 'graph' && a.descendants.length > 0 && (
              <button className="btn btn-line btn-sm" aria-pressed={desc} onClick={() => setDesc(!desc)}>{desc ? 'Hide' : 'Show'} later devices</button>
            )}
          </div>
        </div>
        {mode === 'graph'
          ? <EvidenceGraph a={a} depth={shown} onDepth={setShown} descendants={desc} selected={sel} onSelect={setSel} focusChain={focusChain} />
          : <Timeline a={a} depth={shown} highlight={focusChain || topChain(a)?.chain} onSelect={setSel} />}
        <p className="graph-hint">By hand, this is {1 + a.ancestors.filter((x) => x.lineage_known).length} summary PDFs opened one generation at a time and {1 + a.ancestors.length} separate
          recall searches. Here it is one Relate query.</p>
      </section>

      <div className="grid-main">
        <div style={{ minWidth: 0 }}>
          <section className="panel" id="review" aria-labelledby="review-title" style={{ scrollMarginTop: 120 }}>
            <div className="panel-head">
              <h2 id="review-title">What needs human review <span className="count">{nReview}</span></h2>
              <p className="hint">What conflicts, why it matters, and what to do next.</p>
            </div>
            <ReviewQueue a={a} onSelect={setSel} go={go} onFocusChain={setFocusChain} />
          </section>

          <Signals a={a} onSelect={setSel} />
        </div>

        <aside style={{ minWidth: 0 }}>
          <Citations a={a} reload={load} go={go} onSelect={setSel} />
          <Note a={a} onSaved={() => { api.assessments(k).then(setAssessments); onChanged && onChanged() }} />
          <HistoryPanel a={a} assessments={assessments} runs={runs} go={go} />
        </aside>
      </div>
      {sel && <Provenance sel={sel} a={a} onClose={() => setSel(null)} go={(t, x) => { setSel(null); go(t, x) }} reload={load} onSelect={setSel} />}
    </div>
  )
}

function Signals({ a, onSelect }) {
  const strong = a.signals.filter((s) => s.severity === 'high' || s.severity === 'medium' || s.severity === 'low')
  return (
    <section className="panel" aria-labelledby="signals-title">
      <div className="panel-head">
        <h2 id="signals-title">Recall signals <span className="count">{strong.length} in the readable ancestry</span></h2>
        <p className="hint">Every recall record behind the verdict, by generation.</p>
      </div>
      {strong.length === 0 && <p className="muted">No recall records anywhere in the readable ancestry.</p>}
      {strong.map((s, i) => <Signal key={i} s={s} onSelect={onSelect} />)}
    </section>
  )
}

function Signal({ s, onSelect }) {
  const [open, setOpen] = useState(s.severity === 'high')
  const recalls = s.evidence.filter((e) => e.type === 'recall')
  return (
    <div className="signal">
      <button className="signal-head" aria-expanded={open} onClick={() => setOpen(!open)}>
        <span className={`sev sev-${s.severity}`}>{s.conditional ? 'cond.' : s.severity}</span>
        <span className="t">{s.title}</span>
        <svg className="chev" width="12" height="12" viewBox="0 0 12 12" aria-hidden="true"><path d="M4 2l4 4-4 4" stroke="currentColor" fill="none" strokeWidth="1.5" /></svg>
      </button>
      {open && (
        <div className="signal-body">
          {s.chain?.length > 1 && (
            <div className="tags">{s.chain.map((c, i) => (
              <React.Fragment key={c}>{i > 0 && <span className="muted small" aria-hidden="true">→</span>}
                <button className="tag-btn" onClick={() => onSelect({ type: 'node', k: c })}><span className="k">{c}</span></button></React.Fragment>))}</div>
          )}
          {recalls.slice(0, 6).map((r) => <RecallCard key={r.id} r={r} />)}
          {recalls.length > 6 && <p className="muted small">+ {recalls.length - 6} more record(s): open {s.chain[s.chain.length - 1]} for all.</p>}
        </div>
      )}
    </div>
  )
}

// a person's own review (an automated client's review is advisory and never shows as one)
const mine = (c, status) => c.review === status && humanReview(c)

function Citations({ a, reload, go, onSelect }) {
  const [busy, setBusy] = useState(null)
  const [msg, setMsg] = useState(null)
  const act = async (c, fn, label) => {
    setBusy(c.dst + label); setMsg(null)
    try {
      const r = await fn()
      setMsg(label === 'ai' ? { ok: true, text: `LLM labelled ${c.dst} "${r.ai_label}" (${r.model.split('/')[1]}, ${r.seconds}s). Advisory only: it is not used for the verdict until a person confirms the citation.` } : null)
      reload()
    } catch (e) { setMsg({ ok: false, text: e.message }) } finally { setBusy(null) }
  }
  return (
    <section className="panel" aria-labelledby="cites-title">
      <div className="panel-head">
        <h2 id="cites-title">What {a.k} cites <span className="count">{a.citations.length}</span></h2>
      </div>
      <p className="lede">Read from its 510(k) summary. Your review is written to the graph and changes every lineage query.</p>
      {a.device.lineage_known === false && <p className="note-box">Summary not machine-readable ({a.device.summary_status}).{' '}
        <button className="btn btn-quiet btn-sm" onClick={() => go('ingest', a.k)}>Try reading it now →</button></p>}
      {msg && <p className={msg.ok ? 'ok' : 'err'} role="status">{msg.text}</p>}
      {a.citations.map((c) => {
        const hop = { ...c, src: a.k }
        const inLineage = c.in_lineage ?? (c.kind === 'predicate')
        const st = edgeStatus(hop)
        return (
          <div key={c.dst} className={'cit' + (c.review === 'rejected' && humanReview(c) ? ' is-rejected' : '')}>
            <div className="cit-h">
              <button className="k mono" onClick={() => onSelect({ type: 'edge', id: a.k + '>' + c.dst, hop })}>{c.dst}</button>
              <span className={`chip ${c.kind === 'predicate' ? 'tone-blue' : 'tone-muted'}`}>{c.kind}</span>
              {inLineage || st.key === 'advisory' || st.key === 'retired'
                ? <span className={`status status-${st.key}`} title={EDGE_STATUS[st.key].label} data-testid={`cit-status-${c.dst}`}><span className="line" />{EDGE_STATUS[st.key].short}</span>
                : <span className="status status-rejected" title="Reference devices and mentions are not lineage links" data-testid={`cit-status-${c.dst}`}>Not a lineage link</span>}
              {c.ai_label && <span className="chip tone-violet" title={c.ai_quote}>LLM: {c.ai_label}</span>}
              <span className="muted small">{shortName(c.name, 34)} · {year(c.dst_decision_date)}</span>
            </div>
            <Quote text={c.quote || c.snippet} k={c.dst} ocr={c.text_source && c.text_source !== 'pdf_text_layer'} />
            <div className="cit-a">
              <button className="btn btn-line btn-sm" disabled={!!busy} onClick={() => act(c, () => api.review(a.k, c.dst, mine(c, 'confirmed') ? '' : 'confirmed'), 'ok')}>
                {mine(c, 'confirmed') ? 'Unconfirm' : 'Confirm'}</button>
              <button className="btn btn-line btn-sm" disabled={!!busy} onClick={() => act(c, () => api.review(a.k, c.dst, mine(c, 'rejected') ? '' : 'rejected'), 'no')}>
                {mine(c, 'rejected') ? 'Restore' : 'Reject'}</button>
              {c.kind !== 'predicate' && <button className="btn btn-quiet btn-sm" disabled={!!busy} onClick={() => act(c, () => api.triage(a.k, c.dst), 'ai')}>
                {busy === c.dst + 'ai' ? 'Asking…' : 'Ask LLM to label'}</button>}
              <button className="btn btn-quiet btn-sm" onClick={() => onSelect({ type: 'edge', id: a.k + '>' + c.dst, hop })}>Provenance · p.{c.page}</button>
            </div>
          </div>
        )
      })}
    </section>
  )
}

function Note({ a, onSaved }) {
  const [open, setOpen] = useState(false)
  const [note, setNote] = useState('')
  const [saved, setSaved] = useState(null)
  const [busy, setBusy] = useState(false)
  useEffect(() => { setSaved(null); setOpen(false); setNote('') }, [a.k])
  const save = async () => {
    setBusy(true)
    try { const r = await api.save(a.k, note); setSaved(r); setOpen(false); setNote(''); onSaved() }
    catch (e) { setSaved({ error: e.message }) } finally { setBusy(false) }
  }
  const text = a.memo.headline + '\n\n' + a.memo.paragraphs.map((p) => p.text).join('\n\n')
  return (
    <section className="panel memo" aria-labelledby="memo-title">
      <div className="panel-head"><h2 id="memo-title">Due-diligence note</h2></div>
      <div className="src">{a.memo.source}</div>
      <p><b>{a.memo.headline}</b></p>
      {a.memo.paragraphs.slice(0, 2).map((p, i) => <p key={i}>{p.text}</p>)}
      {a.memo.paragraphs.length > 2 && <p className="muted small">+ {a.memo.paragraphs.length - 2} more paragraph(s) in the copied note.</p>}
      <div className="cit-a" style={{ marginTop: 8 }}>
        <button className="btn btn-primary btn-sm" onClick={() => setOpen(!open)} aria-expanded={open}>Save assessment to graph</button>
        <button className="btn btn-line btn-sm" onClick={() => navigator.clipboard?.writeText(text)}>Copy note</button>
      </div>
      {open && (
        <div style={{ marginTop: 10, display: 'grid', gap: 8 }}>
          <label className="small muted" htmlFor="analyst-note">Optional analyst note, stored with the assessment</label>
          <textarea id="analyst-note" className="field" rows={3} value={note} onChange={(e) => setNote(e.target.value)} maxLength={1000} />
          <div className="cit-a"><button className="btn btn-primary btn-sm" disabled={busy} onClick={save}>{busy ? 'Saving…' : 'Save to Relate'}</button>
            <button className="btn btn-quiet btn-sm" onClick={() => setOpen(false)}>Cancel</button></div>
        </div>
      )}
      {saved && (saved.error ? <p className="err">{saved.error}</p>
        : <p className="ok" role="status">Saved {saved.id}: linked to {saved.flagged_recalls.length} flagged recall record(s).</p>)}
    </section>
  )
}

function HistoryPanel({ a, assessments, runs, go }) {
  return (
    <section className="panel" aria-labelledby="hist-title">
      <div className="panel-head"><h2 id="hist-title">Investigation history</h2><a className="small" href="#/history">All history →</a></div>
      <h3 className="eyebrow" style={{ fontSize: 10.5, margin: '0 0 8px' }}>Saved assessments</h3>
      {assessments.length === 0 ? <p className="muted small">None saved for {a.k} yet.</p> : assessments.map((h) => (
        <div key={h.id} className="hist">
          <div className="hist-h"><span className="k mono">{h.id}</span><span className="muted">{h.created_at?.slice(0, 16).replace('T', ' ')}</span>
            <span className={`chip tone-${VERDICTS[h.verdict]?.tone || 'muted'}`}>{VERDICTS[h.verdict]?.label || h.verdict}</span></div>
          {h.stale && <div className="stale">Stale: the graph changed after this was saved
            {h.verdict_now !== h.verdict && <> (verdict now {VERDICTS[h.verdict_now]?.label || h.verdict_now})</>}
            {h.changed_edges?.length > 0 && <> · reviewed links: {h.changed_edges.join(', ')}</>}
            {h.reingested?.length > 0 && <> · re-ingested: {h.reingested.join(', ')}</>}</div>}
        </div>
      ))}
      <h3 className="eyebrow" style={{ fontSize: 10.5, margin: '16px 0 8px' }}>Agent runs (optional)</h3>
      <p className="muted small" style={{ margin: '0 0 6px' }}>Machine findings, never human-approved. The verdict above does not depend on them.</p>
      {runs.length === 0 ? <p className="muted small">No agent runs examined {a.k} in this store.</p> : runs.map((r) => (
        <div key={r.id} className="hist">
          <div className="hist-h"><span className="k mono">{r.id}</span><span className="chip">{r.status}</span>{r.stale && <span className="stale">stale</span>}
            <a href={reportUrl(r.id)} target="_blank" rel="noreferrer">Report ↗</a></div>
          <div className="muted">{(r.request || '').slice(0, 110)}</div>
        </div>
      ))}
    </section>
  )
}

export function Home({ go, stats }) {
  const cases = [
    ['K252078', 'BreathePal Bilevel', 'Cleared 2026 · direct predicate under a Class I design recall'],
    ['K251770', 'SleepRes PAP System', 'Cleared 2025 · depth 1 finds no signal; depth 2 finds a Class I design recall'],
    ['K200480', 'DreamStation 2', 'Cleared 2020, before the June 2021 recall began'],
  ]
  return (
    <div className="home-hero">
      <div className="page-head">
        <p className="eyebrow">Investigate</p>
        <h1>Check a predicate's ancestry before you cite it.</h1>
        <p>Search any clearance above (press <code>/</code>), or open one of the real cases in the shipped dataset of CPAP, BiPAP and ventilator clearances.</p>
      </div>
      <div className="home-cases">
        {cases.map(([k, name, sub]) => (
          <button key={k} className="case" onClick={() => go('check', k)}><span className="k mono">{k}</span><h3>{name}</h3><p>{sub}</p></button>
        ))}
        <button className="case" onClick={() => go('reach', '88058,88071')}><span className="k mono">Recall 88058 + 88071</span><h3>Philips foam recall reach</h3><p>Who descends from the June 2021 recall?</p></button>
      </div>
      {stats && <p className="muted small" style={{ marginTop: 18 }}>{stats.nodes.Device.toLocaleString('en-US')} clearances · {stats.citations_by_kind.predicate.toLocaleString('en-US')} predicate links · {stats.nodes.Recall.toLocaleString('en-US')} recall records in the Relate store.</p>}
    </div>
  )
}
