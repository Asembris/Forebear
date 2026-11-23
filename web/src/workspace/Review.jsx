import React from 'react'
import { DOUBT_TEXT, EDGE_STATUS, edgeStatus } from '../evidence.js'

/*
  Actionable uncertainty. Each review item turns one deterministic signal into three plain answers:
  what conflicts or is missing, why it matters for a predicate rationale, and what a person can do now.
  The explanations restate what each rule in forebear/lineage.py measures; they add no new claim.
*/

const REASON_TEXT = {
  rejected_by_reviewer: 'rejected by a reviewer',
  audit_not_predicate: 'the audit found it is not a predicate citation',
  audit_error: 'the audit found a K-number error',
  audit_unresolved: 'the audit could not resolve it',
  not_in_openfda: 'K-number not found in openFDA',
  cleared_after_citing_device: 'K-number cleared after the citing device',
  audit_variant: 'audit marked it a naming variant',
  audit_corrected: 'K-number corrected by the audit',
}

export function reviewItems(a) {
  const items = []
  for (const s of a.signals) {
    switch (s.code) {
      case 'DIRECT_RECALL':
        if (s.severity === 'info') break
        items.push({ id: s.code, tone: s.severity === 'high' ? 'alert' : 'amber', sev: s.severity, title: s.title,
          what: 'The candidate itself appears in FDA recall records.',
          why: s.severity === 'high' ? 'A design-related recall on the device you would cite is what FDA\'s 2023 draft guidance asks you to avoid or explain.'
            : 'A Class I recall on the candidate is a documented question for any submission that cites it.',
          todo: 'Open each recall record and document how it is addressed (scope, lots, corrective action).',
          node: a.k })
        break
      case 'ANCESTOR_RECALL':
        if (s.severity !== 'medium') break
        items.push({ id: s.code + s.chain.join(), tone: s.conditional ? 'violet' : 'amber', sev: s.severity, title: s.title,
          conditional: s.conditional,
          what: s.conditional ? 'The recall holder is reached only through a citation the audit could not resolve.'
            : `A ${s.gen === 1 ? 'direct predicate' : 'grand-predicate'} carries recall records the verdict rules treat as review-worthy.`,
          why: s.conditional ? 'If that citation is not a predicate, this recall does not belong to the lineage; if it is, it does.'
            : 'Reviewers expect the predicate rationale to address design-related recalls in the lineage (FDA 2023 draft guidance; Kadakia et al., JAMA 2023, an association).',
          todo: s.conditional ? 'Open the uncertain thread, read the PDF page, and confirm or reject it.'
            : 'Verify the citation on its PDF page, read the recall records, and record how the rationale addresses them.',
          chain: s.chain, hops: s.evidence.filter((e) => e.type === 'citation') })
        break
      case 'UNCERTAIN_LINK_IN_LINEAGE':
      case 'NAME_MISMATCH_IN_LINEAGE':
        items.push({ id: s.code, tone: 'alert', sev: 'info', title: s.title,
          what: 'Threads in this ancestry rest on evidence that conflicts with FDA records or needed correction.',
          why: 'A doubtful thread may route the lineage to the wrong device, and the right one may be missing; these links never count as checked.',
          todo: 'Open each thread, compare the quote with the cited device, then confirm or reject it.',
          hops: s.evidence.filter((e) => e.type === 'citation') })
        break
      case 'ADVISORY_LINK_PENDING_REVIEW':
        items.push({ id: s.code, tone: 'violet', sev: 'info', title: s.title,
          what: 'An LLM label or the automated MCP client calls these citations predicates; no person has decided.',
          why: 'They are not used for the verdict. If one is a real predicate, its recalls belong in the lineage and the verdict could change.',
          todo: 'Open each link, read the PDF page, and confirm or reject it yourself.',
          hops: s.evidence.filter((e) => e.type === 'advisory_citation') })
        break
      case 'CITATION_RETIRED_BY_REINGEST':
        items.push({ id: s.code, tone: 'muted', sev: 'info', title: s.title,
          what: "Re-reading the citing device's FDA summary no longer found these citations, so they were retired from the lineage.",
          why: 'Earlier reviews, labels and provenance are kept for the record; a review made on the old text may no longer apply.',
          todo: 'Compare the refreshed summary with the earlier one and record a new review if the citation still matters.',
          hops: s.evidence })
        break
      case 'PREDICATE_CITATION_UNRESOLVED':
        items.push({ id: s.code, tone: 'muted', sev: 'info', title: s.title,
          what: 'Predicate citations printed in a summary did not become lineage threads.',
          why: 'A missing thread means part of the ancestry is invisible: a recall there would not show.',
          todo: 'Check each quote. If the citation is real and the K-number valid, add that clearance to extend the graph.',
          missing: s.evidence })
        break
      case 'LINEAGE_UNKNOWN':
      case 'LINEAGE_TRUNCATED':
        items.push({ id: s.code, tone: 'muted', sev: 'info', title: s.title,
          what: 'Some summaries are not machine-readable, so the ancestry stops there.',
          why: 'Recalls further up those branches cannot be seen. The verdict reports this gap; it never fills it in.',
          todo: 'Try reading each summary live (needs internet), which extends the lineage by one generation.',
          ingest: s.code === 'LINEAGE_UNKNOWN' ? [{ k: a.k }] : s.evidence })
        break
      case 'UNATTRIBUTED_RECALLS_IN_PRODUCT_CODE':
        items.push({ id: s.code, tone: 'muted', sev: 'info', title: s.title,
          what: 'FDA filed these recalls under the product code without naming a 510(k) number.',
          why: 'No lineage query can attribute them; one may still concern a device in this lineage.',
          todo: 'Read the product descriptions and check whether any names a device in this ancestry.',
          recalls: s.evidence })
        break
      case 'RECALL_CAUSE_OR_CLASS_UNKNOWN':
        items.push({ id: s.code, tone: 'muted', sev: 'info', title: s.title,
          what: 'Recall records without a stated root cause or FDA classification.',
          why: 'They cannot be ruled out as design-related or Class I, so they could change the verdict once classified.',
          todo: 'Re-check the FDA records for an updated classification or root cause.', recalls: s.evidence })
        break
      case 'DEEPER_ANCESTRY_GAPS':
        items.push({ id: s.code, tone: 'muted', sev: 'info', title: s.title,
          what: 'Gaps beyond the two-generation verdict window.',
          why: 'They cannot change the verdict, but the lower-severity list may be incomplete.',
          todo: 'Expand the graph to deeper generations if the deeper ancestry matters to your rationale.' })
        break
      default:
    }
  }
  return items
}

export default function ReviewQueue({ a, onSelect, go, onFocusChain }) {
  const items = reviewItems(a)
  if (!items.length) return <p className="muted">Nothing in this lineage needs a person's attention under the current rules.</p>
  return (
    <div data-testid="review-queue">
      {items.map((it) => (
        <section key={it.id} className={`review-item tone-${it.tone}`}
          onMouseEnter={() => it.chain && onFocusChain(it.chain)} onMouseLeave={() => onFocusChain(null)}>
          <h3>
            <span className={`sev sev-${it.sev}`}>{it.conditional ? 'conditional' : it.sev === 'info' ? 'gap' : it.sev}</span>
            <span>{it.title}</span>
          </h3>
          <dl>
            <dt>Conflict</dt><dd>{it.what}</dd>
            <dt>Why it matters</dt><dd>{it.why}</dd>
            <dt>Next step</dt><dd>{it.todo}</dd>
          </dl>
          {it.hops?.length > 0 && (
            <div className="links">
              {it.hops.slice(0, 8).map((h) => {
                const st = edgeStatus(h)
                return (
                  <button key={h.src + h.dst} className="tag-btn" onClick={() => onSelect({ type: 'edge', id: h.src + '>' + h.dst, hop: h })}
                    title={st.reasons.map((r) => DOUBT_TEXT[r]).join('; ') || EDGE_STATUS[st.key].label}>
                    <span className="k">{h.src}</span> → <span className="k">{h.dst}</span> · p.{h.page ?? '?'} · <span className={`status-${st.key}`}>{EDGE_STATUS[st.key].short}</span>
                  </button>
                )
              })}
            </div>
          )}
          {it.missing?.length > 0 && (
            <div className="links">
              {it.missing.slice(0, 8).map((m) => (
                <button key={m.src + m.cited} className="tag-btn" title={m.quote || ''} onClick={() => go('ingest', m.cited)}>
                  <span className="k">{m.src}</span> → <span className="k">{m.cited}</span> · {REASON_TEXT[m.reason] || m.reason}
                </button>
              ))}
            </div>
          )}
          {it.ingest?.length > 0 && (
            <div className="links">
              {it.ingest.slice(0, 10).map((d) => (
                <button key={d.k} className="tag-btn" onClick={() => go('ingest', d.k)}><span className="k">{d.k}</span>{d.summary_status ? ` · ${d.summary_status}` : ''} · read now</button>
              ))}
            </div>
          )}
          {it.recalls?.length > 0 && (
            <div className="links">
              {it.recalls.slice(0, 8).map((r) => r.url
                ? <a key={r.id} className="tag-btn" href={r.url} target="_blank" rel="noreferrer">{r.id} ↗</a>
                : <span key={r.id} className="tag-btn">{r.id}</span>)}
            </div>
          )}
          {it.node && <div className="acts"><button className="btn btn-line btn-sm" onClick={() => onSelect({ type: 'node', k: it.node })}>Open recall records</button></div>}
          {it.chain && <div className="acts"><button className="btn btn-line btn-sm" onClick={() => onSelect({ type: 'node', k: it.chain[it.chain.length - 1] })}>Open {it.chain[it.chain.length - 1]} records</button></div>}
        </section>
      ))}
    </div>
  )
}
