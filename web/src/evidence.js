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
/** Order two ISO dates by calendar day: -1 if a is earlier, 0 if the same day, 1 if later, null if either is missing.
    Zero-padded YYYY-MM-DD strings sort chronologically, so no rounding can blur the order. */
export function dateOrder(a, b) {
  if (!a || !b) return null
  const x = String(a).slice(0, 10), y = String(b).slice(0, 10)
  return x < y ? -1 : x > y ? 1 : 0
}

/** When a recall began relative to a clearance. The relation comes from the dates themselves; the elapsed
    duration is measured separately, always forwards in time, and is display text only. */
export function recallTiming(initiated, clearance) {
  const order = dateOrder(initiated, clearance)
  if (order == null) return null
  if (order === 0) return { relation: 'same-day', months: 0, duration: '' }
  const months = order < 0 ? monthsBetween(initiated, clearance) : monthsBetween(clearance, initiated)
  return { relation: order < 0 ? 'before' : 'after', months, duration: spanText(months) }
}

/** Wording for a recallTiming() result: 'clause' continues a sentence, 'chip' stands alone. */
export function recallTimingText(timing, k, form = 'clause') {
  if (!timing) return ''
  const { relation, duration } = timing
  if (form === 'chip') {
    return relation === 'same-day' ? `Recall began on the day of ${k}'s clearance`
      : `Recall began ${duration} ${relation} ${k}'s clearance`
  }
  return relation === 'same-day' ? `on the day ${k} was cleared` : `${duration} ${relation} ${k} was cleared`
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

/** Mirror of lineage.provisional(): a "no signal" verdict on an incomplete verdict window. */
export function isProvisional(verdict, evidence) {
  return verdict === 'NO_DESIGN_RECALL_SIGNAL' && evidence !== 'complete'
}

/** Verdict chip for a verdict plus its evidence coverage. A provisional "no signal" never shows the calm tone. */
export function verdictView(verdict, evidence) {
  const v = VERDICTS[verdict]
  if (!v) return { tone: 'muted', label: verdict || 'Unknown', provisional: false }
  return isProvisional(verdict, evidence)
    ? { tone: 'muted', label: `${v.label} · provisional`, provisional: true }
    : { tone: v.tone, label: v.label, provisional: false }
}

export const EVIDENCE_TONE = { complete: 'calm', partial: 'amber', uncertain: 'alert', none: 'muted' }

/** Mirror of the coverage.evidence_reasons codes in lineage.assess(). */
export const EVIDENCE_REASON_TEXT = {
  direct_predicate_links_all_uncertain: 'every direct predicate link rests on uncertain evidence',
  unresolved_predicate_citations: 'predicate citations within two generations could not be resolved',
  direct_predicate_summaries_unread: "a direct predicate's own summary was not read",
  doubtful_links_in_window: 'links within two generations rest on doubtful evidence',
  recall_cause_or_class_unknown: 'a recall has no stated cause or FDA class',
  unattributed_recalls_in_product_code: 'design-related recalls in the product code name no 510(k)',
  shallow_traversal: 'grand-predicates were not traversed',
}

/** Mirror of lineage.recall_attribution(). Every link is FDA's own listing of the K-number on the recall record: an
    association, never verified model identity. The code only reports the fuzzy name heuristic (evidence.name_check). */
export const ATTRIBUTION = {
  name_token_match: { short: 'FDA-listed · name match (heuristic)', tone: 'other',
    text: 'FDA lists this 510(k) on the recall. A distinctive word of its FDA device name appears in the recall text, possibly as a fuzzy match. This heuristic does not verify that the recall names this exact model.' },
  name_token_absent: { short: 'FDA-listed · name not found (heuristic)', tone: 'muted',
    text: 'FDA lists this 510(k) on the recall, but no distinctive word of its FDA device name was found in the recall text. The recalled model may differ, or the text may name it differently.' },
  name_not_checkable: { short: 'FDA-listed · name not checked', tone: 'muted',
    text: 'FDA lists this 510(k) on the recall. No name check is available: its FDA device name has no distinctive word to look for, or no check was recorded for this link. Which model was recalled is not established here.' },
}

/** Caveat for a recall that began before the clearance it is listed on. Dates alone do not settle whether the model was affected. */
export const PREDATES_CLEARANCE = {
  short: 'Recall began before this clearance',
  text: 'This recall began before this 510(k) was cleared, yet FDA lists it on the record. The dates alone do not establish whether this cleared model was affected: read the FDA record.',
}

/** Recall reach timing (lineage.date_relation) as display text. */
export const TIMING_TEXT = {
  after: 'cleared after the recall began',
  before: 'cleared before the recall began',
  same_day: 'cleared the day the recall began (order unknown)',
  unknown: 'timing unknown (a date is missing)',
}

export function recallAttribution(r) {
  if (r?.attribution && ATTRIBUTION[r.attribution]) return r.attribution
  return r?.link_name_check === 'match' ? 'name_token_match' : r?.link_name_check === 'mismatch' ? 'name_token_absent' : 'name_not_checkable'
}
