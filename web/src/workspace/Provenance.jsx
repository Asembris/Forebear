import React, { useEffect, useRef, useState } from 'react'
import { api, pmnUrl } from '../api.js'
import {
  ATTRIBUTION, DOUBT_TEXT, MACHINE_REVIEWERS, PREDATES_CLEARANCE, EDGE_STATUS, TEXT_SOURCE, countEvents, edgeStatus, fmtDate, humanReview, outdatedReview, pdfAt, recallAttribution, recallTone, shortName,
} from '../evidence.js'

/* Highlight the cited K-number inside the verbatim quote. */
export function Quote({ text, k, ocr }) {
  if (!text) return <p className="quote muted">No quote stored for this citation.</p>
  const parts = k ? text.split(new RegExp(`(${k.replace(/^K/, 'K\\s?')})`)) : [text]
  return (
    <blockquote className={'quote' + (ocr ? ' is-ocr' : '')}>
      “{/^[a-z]/.test(text) ? '…' : ''}{parts.map((p, i) => (i % 2 ? <mark key={i}>{p}</mark> : <React.Fragment key={i}>{p}</React.Fragment>))}”
    </blockquote>
  )
}

export function StatusTag({ hop }) {
  const st = edgeStatus(hop)
  return <span className={`status status-${st.key}`}><span className="line" />{EDGE_STATUS[st.key].label}</span>
}

export function RecallCard({ r }) {
  const tone = recallTone(r)
  const att = ATTRIBUTION[recallAttribution(r)]
  return (
    <div className="recall" data-attribution={recallAttribution(r)}>
      <div className="recall-h">
        <span className={`chip tone-${tone}`}>{tone === 'design' ? 'Design-related' : tone === 'class1' ? 'Class I, other cause' : 'Other cause'}</span>
        <span className="k mono">{r.id}</span>
        <span className="muted">{r.classification || 'Unclassified'} · {r.root_cause || 'cause not stated'} · began {fmtDate(r.initiated)}</span>
        {r.url && <a href={r.url} target="_blank" rel="noreferrer">FDA record ↗</a>}
      </div>
      <div className="recall-r"><span className={`chip tone-${att.tone}`} title={att.text}>{att.short}</span> <span className="muted small">{att.text}</span></div>
      {r.linked_before_clearance && (
        <div className="recall-r" data-testid="recall-predates"><span className="chip tone-muted" title={PREDATES_CLEARANCE.text}>{PREDATES_CLEARANCE.short}</span>{' '}
          <span className="muted small">{PREDATES_CLEARANCE.text}</span></div>)}
      {r.reason && <div className="recall-r">{r.reason}</div>}
      {r.status && <div className="recall-r">Status: {r.status}{r.event ? ` · event ${r.event}` : ''}{r.firm ? ` · ${r.firm}` : ''}</div>}
    </div>
  )
}

/* Find what the assessment knows about a device: the candidate, an ancestor or a descendant. */
export function deviceIn(a, k) {
  if (k === a.k) return { ...a.device, k: a.k, gen: 0, side: 'self' }
  return a.ancestors.find((x) => x.k === k) && { ...a.ancestors.find((x) => x.k === k), side: 'up' } ||
    a.descendants.find((x) => x.k === k) && { ...a.descendants.find((x) => x.k === k), side: 'down' } || null
}

export default function Provenance({ sel, a, onClose, go, reload, onSelect }) {
  const panel = useRef(null)
  const closeBtn = useRef(null)
  useEffect(() => {
    const prev = document.activeElement
    closeBtn.current?.focus()
    const key = (e) => {
      if (e.key === 'Escape') onClose()
      if (e.key === 'Tab' && panel.current) {           // keep focus inside the sheet
        const f = panel.current.querySelectorAll('a[href], button:not([disabled]), input, textarea, [tabindex="0"]')
        if (!f.length) return
        const first = f[0], last = f[f.length - 1]
        if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus() }
        else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus() }
      }
    }
    addEventListener('keydown', key)
    return () => { removeEventListener('keydown', key); prev?.focus?.() }
  }, [])
  return (
    <>
      <div className="drawer-scrim" onClick={onClose} />
      <aside className="drawer" ref={panel} role="dialog" aria-modal="true" aria-labelledby="drawer-title" data-testid="provenance">
        {sel.type === 'edge'
          ? <EdgeBody sel={sel} a={a} closeBtn={closeBtn} onClose={onClose} go={go} reload={reload} onSelect={onSelect} />
          : <NodeBody sel={sel} a={a} closeBtn={closeBtn} onClose={onClose} go={go} onSelect={onSelect} />}
      </aside>
    </>
  )
}

function Head({ eyebrow, children, closeBtn, onClose }) {
  return (
    <div className="drawer-head">
      <div className="t">
        <p className="eyebrow">{eyebrow}</p>
        <h2 id="drawer-title">{children}</h2>
      </div>
      <button ref={closeBtn} className="btn btn-quiet" onClick={onClose} aria-label="Close provenance (Escape)">✕</button>
    </div>
  )
}

function EdgeBody({ sel, a, closeBtn, onClose, go, reload, onSelect }) {
  const h = sel.hop
  const src = deviceIn(a, h.src) || {}
  const dst = deviceIn(a, h.dst) || {}
  const st = edgeStatus(h)
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState(null)
  const url = h.source_url || src.summary_url
  const ocr = (h.text_source || src.text_source) && (h.text_source || src.text_source) !== 'pdf_text_layer'
  const review = async (status) => {
    setBusy(true); setMsg(null)
    try {
      const r = await api.review(h.src, h.dst, status)
      // show the edge exactly as the graph now stores it (review, reviewer, the PDF versions reviewed and current, trust)
      if (r?.citation) onSelect({ ...sel, hop: r.citation })
      setMsg(r?.citation
        ? { ok: true, text: status ? `Recorded: ${status}. The assessment has been recomputed from the graph.` : 'Review cleared. The assessment has been recomputed.' }
        : { ok: false, text: 'The review was sent, but the graph did not return the citation. Reopen it to see its current state.' })
      reload()
    } catch (e) { setMsg({ ok: false, text: e.message }) } finally { setBusy(false) }
  }
  return (
    <>
      <Head eyebrow="Citation provenance" closeBtn={closeBtn} onClose={onClose}>
        <span className="k">{h.src}</span> cites <span className="k">{h.dst}</span>
      </Head>
      <div className="drawer-body">
        <div className="drawer-sec">
          <StatusTag hop={h} />
          {st.reasons.length > 0 && (
            <ul style={{ margin: '8px 0 0', paddingLeft: 18, color: 'var(--ink-2)', fontSize: 12.5 }}>
              {st.reasons.map((r) => <li key={r}>{DOUBT_TEXT[r] || r}</li>)}
            </ul>
          )}
          {st.key === 'conditional' && (
            <p className="note-box violet" style={{ marginTop: 10 }}>Recall signals reached through this thread are <b>conditional</b>: they hold only if
              this citation is a predicate. Read the page, then confirm or reject it: your review rewrites the verdict.</p>
          )}
        </div>
        <div className="drawer-sec">
          <h3>What the summary says</h3>
          <Quote text={h.quote || h.snippet} k={h.dst} ocr={ocr} />
        </div>
        {url && (
          <a className="page-card" href={pdfAt(url, h.page)} target="_blank" rel="noreferrer" data-testid="pdf-page-link">
            <span className="sheet"><b>p.{h.page ?? '?'}</b></span>
            <span className="tx"><b>Open the original FDA PDF{h.page ? ` at page ${h.page}` : ''} ↗</b>
              <span>{h.src} 510(k) summary · accessdata.fda.gov</span></span>
          </a>
        )}
        <div className="drawer-sec">
          <h3>Source and extraction</h3>
          <dl className="prov-grid">
            <dt>Citing device</dt><dd>{h.src} · {shortName(src.name, 40)}{src.decision_date ? ` · ${fmtDate(src.decision_date)}` : ''}</dd>
            <dt>Cited device</dt><dd>{h.dst} · {shortName(dst.name, 40)}{dst.decision_date ? ` · ${fmtDate(dst.decision_date)}` : ''}</dd>
            <dt>Role</dt><dd>{h.kind || 'predicate'}</dd>
            <dt>Page</dt><dd>{h.page ?? 'not recorded'}</dd>
            <dt>Text source</dt><dd>{TEXT_SOURCE[h.text_source || src.text_source] || h.text_source || src.text_source || 'not recorded'}</dd>
            <dt>Extraction</dt><dd>{h.method || '—'}{h.confidence != null ? ` · confidence ${h.confidence}` : ''}</dd>
            <dt>Name check</dt><dd>{h.name_check || '—'}</dd>
            <dt>FDA panel</dt><dd>{h.panel_check || '—'}</dd>
            {h.audit && <><dt>Audit</dt><dd>{h.audit}{h.audit_note ? ` — ${h.audit_note}` : ''}</dd></>}
            {h.ai_label && <><dt>LLM label</dt><dd>{h.ai_label}{h.ai_model ? ` · ${h.ai_model}` : ''} (advisory; never a verdict input until a person confirms)</dd></>}
            <dt>Review</dt><dd data-testid="edge-review">{h.review ? `${h.review} by ${h.reviewer || 'unknown'}${MACHINE_REVIEWERS.includes(h.reviewer) ? ' (automated client; advisory)' : outdatedReview(h) ? ' on an earlier version of the summary; needs re-review' : ''}` : 'not reviewed by a person'}</dd>
            <dt>Trust</dt><dd data-testid="edge-trust">{EDGE_STATUS[edgeStatus(h).key].label}</dd>
            {h.retired_at && <><dt>Retired</dt><dd>{fmtDate(h.retired_at)} · no longer cited by the refreshed summary</dd></>}
            {src.summary_sha256 && <><dt>PDF SHA-256</dt><dd><span className="mono">{src.summary_sha256}</span></dd></>}
          </dl>
        </div>
        <div className="drawer-sec">
          <h3>Your review</h3>
          <div className="drawer-acts">
            <button className="btn btn-line btn-sm" disabled={busy} onClick={() => review(h.review === 'confirmed' && humanReview(h) ? '' : 'confirmed')}>
              {h.review === 'confirmed' && humanReview(h) ? 'Clear confirmation' : 'Confirm citation'}</button>
            <button className="btn btn-line btn-sm" disabled={busy} onClick={() => review(h.review === 'rejected' && humanReview(h) ? '' : 'rejected')}>
              {h.review === 'rejected' && humanReview(h) ? 'Restore citation' : 'Reject citation'}</button>
          </div>
          <p className="note" style={{ marginTop: 8 }}>A review is a write to the Relate graph. Every lineage query, verdict and saved-assessment
            staleness check reads it immediately.</p>
          {msg && <p className={msg.ok ? 'ok' : 'err'} role="status">{msg.text}</p>}
        </div>
        <div className="drawer-acts">
          <button className="btn btn-quiet btn-sm" onClick={() => onSelect({ type: 'node', k: h.dst })}>{h.dst} record →</button>
          <button className="btn btn-quiet btn-sm" onClick={() => onSelect({ type: 'node', k: h.src })}>{h.src} record →</button>
        </div>
      </div>
    </>
  )
}

function NodeBody({ sel, a, closeBtn, onClose, go, onSelect }) {
  const n = deviceIn(a, sel.k)
  if (!n) return <><Head eyebrow="Device" closeBtn={closeBtn} onClose={onClose}>{sel.k}</Head><div className="drawer-body">Not in this view.</div></>
  const recalls = [...(n.recalls || [])].sort((p, q) => (q.design_related - p.design_related) || (p.initiated || '').localeCompare(q.initiated || ''))
  const ev = countEvents(recalls)
  const role = n.side === 'self' ? 'Candidate' : n.side === 'up' ? ({ 1: 'Direct predicate', 2: 'Grand-predicate' }[n.gen] || `Generation ${n.gen} ancestor`) : `Later device citing this lineage (+${n.gen})`
  const before = recalls.filter((r) => r.initiated && a.device.decision_date && r.initiated < a.device.decision_date)
  return (
    <>
      <Head eyebrow={role} closeBtn={closeBtn} onClose={onClose}>
        <span className="k">{n.k}</span> {shortName(n.name, 60)}
      </Head>
      <div className="drawer-body">
        <dl className="prov-grid">
          <dt>Applicant</dt><dd>{n.applicant || '—'}</dd>
          <dt>Cleared</dt><dd>{fmtDate(n.decision_date)}{n.received_date ? ` (received ${fmtDate(n.received_date)})` : ''}</dd>
          <dt>Product code</dt><dd>{n.product_code || '—'}</dd>
          <dt>Summary</dt><dd>{n.summary_status || '—'}{n.lineage_known === false ? ' · its own predicates were not read' : ''}</dd>
          {n.chain?.length > 1 && <><dt>Route</dt><dd className="mono" style={{ fontSize: 12 }}>{n.chain.join(' → ')}</dd></>}
        </dl>
        <div className="drawer-acts">
          {n.k !== a.k && <button className="btn btn-primary btn-sm" onClick={() => go('check', n.k)}>Investigate {n.k} <span className="arr" aria-hidden="true">→</span></button>}
          <a className="btn btn-line btn-sm" href={pmnUrl(n.k)} target="_blank" rel="noreferrer">FDA 510(k) record ↗</a>
          {n.summary_url && <a className="btn btn-line btn-sm" href={n.summary_url} target="_blank" rel="noreferrer">Summary PDF ↗</a>}
          {n.lineage_known === false && <button className="btn btn-line btn-sm" onClick={() => go('ingest', n.k)}>Try to read its summary</button>}
        </div>
        {n.hops?.length > 0 && (
          <div className="drawer-sec">
            <h3>How it is reached</h3>
            <div className="tags">
              {n.hops.map((h) => (
                <button key={h.src + h.dst} className="tag-btn" onClick={() => onSelect({ type: 'edge', id: h.src + '>' + h.dst, hop: h })}>
                  <span className="k">{h.src}</span> → <span className="k">{h.dst}</span> · p.{h.page ?? '?'} · {EDGE_STATUS[edgeStatus(h).key].short}
                </button>
              ))}
            </div>
          </div>
        )}
        <div className="drawer-sec">
          <h3>Recall records on which FDA lists this 510(k) · {ev.events} event(s), {ev.records} product record(s)</h3>
          {n.side !== 'self' && before.length > 0 && (
            <p className="note-box amber" style={{ marginBottom: 10 }}>{before.length} of these record(s) began before {a.k} was cleared on {fmtDate(a.device.decision_date)}.</p>
          )}
          {recalls.length === 0 ? <p className="muted">openFDA lists this 510(k) on no recall record.</p>
            : <div style={{ display: 'grid', gap: 8 }}>{recalls.slice(0, 20).map((r) => <RecallCard key={r.id} r={r} />)}</div>}
          {recalls.length > 20 && <p className="muted small">+ {recalls.length - 20} more record(s): open the device to see all.</p>}
        </div>
      </div>
    </>
  )
}
