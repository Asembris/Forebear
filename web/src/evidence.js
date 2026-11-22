/*
  Evidence semantics shared by every view. These mirror the deterministic rules in forebear/lineage.py
  (doubt(), the verdict rules) so the UI never invents a status the backend would not assign.
  If lineage.py changes, change this file with it.
*/

export const MACHINE_REVIEWERS = ['mcp-client']

export const VERDICTS = {
  DESIGN_RECALL_ON_FILE: {
    tone: 'alert', label: 'Design-related recall on file',
    plain: 'The candidate itself has a design-related recall on file.',
  },
  REVIEW_LINEAGE: {
    tone: 'amber', label: 'Review lineage',
    plain: 'A recall in the predicate lineage warrants documented review.',
  },
  INSUFFICIENT_LINEAGE: {
    tone: 'muted', label: 'Lineage not checkable',
    plain: 'The ancestry could not be checked from readable evidence.',
  },
  NO_DESIGN_RECALL_SIGNAL: {
    tone: 'calm', label: 'No design-recall signal',
    plain: 'No design-related recall in the readable verdict window. Not a safety finding.',
  },
}

export const DOUBT_TEXT = {
  audit_unresolved: 'The extraction audit could not resolve whether this is the predicate',
  audit_correction: 'K-number supplied by the audit, not as printed in the PDF',
  name_mismatch: "The cited device's FDA name does not appear near the citation",
  different_fda_panel: 'Cited device sits in a different FDA review panel',
  llm_label_only: 'A predicate only because an LLM labelled the mention',
  client_confirmation_only: 'Confirmed only through the automated MCP client, not a person',
}

/** Mirror of lineage.doubt(): why a lineage hop's evidence is doubtful ([] if not). */
export function doubt(h) {
  if (!h) return []
  if (h.review === 'confirmed' && !MACHINE_REVIEWERS.includes(h.reviewer)) return []
  const why = []
  if (h.audit === 'unresolved') why.push('audit_unresolved')
  if (h.audit === 'corrected') why.push('audit_correction')
  if (h.name_check === 'mismatch' && !['variant', 'corrected'].includes(h.audit)) why.push('name_mismatch')
  if (h.panel_check === 'different' && !['variant', 'corrected'].includes(h.audit)) why.push('different_fda_panel')
  if (h.kind != null && h.kind !== 'predicate' && h.ai_label === 'predicate') why.push('llm_label_only')
  if (h.kind != null && h.kind !== 'predicate' && h.review === 'confirmed' && MACHINE_REVIEWERS.includes(h.reviewer))
    why.push('client_confirmation_only')
  return why
}

export const EDGE_STATUS = {
  confirmed: { label: 'Confirmed by a person', short: 'Confirmed' },
  extracted: { label: 'Machine-extracted', short: 'Extracted' },
  disputed: { label: 'Disputed evidence', short: 'Disputed' },
  conditional: { label: 'Conditional route', short: 'Conditional' },
  rejected: { label: 'Rejected by a reviewer', short: 'Rejected' },
}

/** One of confirmed | extracted | disputed | conditional | rejected, with the reasons behind it. */
export function edgeStatus(h) {
  if (h?.review === 'rejected') return { key: 'rejected', reasons: [] }
  const reasons = doubt(h)
  if (reasons.includes('audit_unresolved')) return { key: 'conditional', reasons }
  if (reasons.length) return { key: 'disputed', reasons }
  if (h?.review === 'confirmed') return { key: 'confirmed', reasons }
  return { key: 'extracted', reasons }
}

export function recallTone(r) {
  if (r.design_related) return 'design'
  if (r.classification === 'Class I') return 'class1'
  return 'other'
}

export function nodeTone(n) {
  const rs = n.recalls || []
  if (rs.some((r) => r.design_related)) return 'design'
  if (rs.length) return 'recall'
  return 'clean'
}

/** Recall events vs product records: FDA files one record per product in an event. */
export function countEvents(recs) {
  const ev = new Set(recs.map((x) => x.event || x.id))
  return { events: ev.size, records: recs.length }
}

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
export function fmtDate(d) {
  if (!d) return '—'
  const [y, m, day] = String(d).slice(0, 10).split('-').map(Number)
  if (!y) return String(d)
  return `${day} ${MONTHS[(m || 1) - 1]} ${y}`
}
export const year = (d) => (d ? String(d).slice(0, 4) : '')

/** Whole months between two ISO dates (b - a). */
export function monthsBetween(a, b) {
  if (!a || !b) return null
  const [ya, ma, da] = a.slice(0, 10).split('-').map(Number)
  const [yb, mb, db] = b.slice(0, 10).split('-').map(Number)
  return (yb - ya) * 12 + (mb - ma) - (db < da ? 1 : 0)
}
export function spanText(months) {
  if (months == null) return ''
  const neg = months < 0
  const m = Math.abs(months)
  const y = Math.floor(m / 12), r = m % 12
  const s = [y ? `${y} yr` : '', r ? `${r} mo` : ''].filter(Boolean).join(' ') || '<1 mo'
  return neg ? `-${s}` : s
}

/** The PDF link opens the original FDA document at the cited page. */
export const pdfAt = (url, page) => (url ? (page ? `${url}#page=${page}` : url) : null)

export const TEXT_SOURCE = {
  pdf_text_layer: 'PDF text layer',
  ocr: 'Local OCR of the scanned PDF',
  embedded_pdf_attachment: 'Summary embedded in a PDF Portfolio',
}

export function shortName(n, max = 30) {
  const s = (n || '').replace(/\s+/g, ' ').trim()
  return s.length > max ? s.slice(0, max - 1) + '…' : s
}
