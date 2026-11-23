import { keyRecall, recallTiming, shortName } from '../evidence.js'

export const strong = (s) => (s.severity === 'high' || s.severity === 'medium') && !s.conditional

/* Whether walking one generation deeper changes the verdict, and the evidence route that changes it.
   Built only from the two deterministic assessments; null when depth does not matter for this clearance. */
export function depthContrast(shallow, deep) {
  if (!shallow || !deep || shallow.k !== deep.k || shallow.depth !== 1 || deep.depth < 2) return null
  if (shallow.verdict === deep.verdict) return null
  const deeper = deep.signals.filter((s) => strong(s) && s.chain?.length > 2)
  if (!deeper.length || deep.signals.some((s) => strong(s) && (s.chain?.length || 0) <= 2)) return null
  const sig = deeper[0]
  const recall = keyRecall(sig.evidence.filter((e) => e.type === 'recall'), deep.device.decision_date)
  if (!recall) return null
  const anc = (k) => deep.ancestors.find((x) => x.k === k)
  const hopTo = (src, dst) => anc(dst)?.hops?.find((h) => h.src === src && h.dst === dst) || null
  const route = sig.chain.slice(0, -1)                     // candidate → … → the device whose citations reach the holders
  const via = route[route.length - 1]
  const holders = deeper.filter((s) => s.chain.slice(0, -1).join('>') === route.join('>')
    && s.evidence.some((e) => e.type === 'recall' && e.id === recall.id)).map((s) => anc(s.chain[s.chain.length - 1])).filter(Boolean)
  const steps = route.slice(1).map((k, i) => ({ device: anc(k), hop: hopTo(route[i], k) }))
  const fanout = holders.map((h) => ({ device: h, hop: hopTo(via, h.k) })).filter((x) => x.hop)
  const predicate = anc(sig.chain[1])
  return {
    k: deep.k, device: deep.device, shallow, deep, recall, steps, fanout, predicate,
    predicateOnRecall: !!predicate?.recalls?.some((r) => r.id === recall.id),
    predicateRecalls: predicate?.recalls?.length || 0,
    timing: recallTiming(recall.initiated, deep.device.decision_date),
    gen: sig.gen,
  }
}

/* The words around the cited K-number, cut at word boundaries, with the K-number marked. */
export function excerpt(text, k, before = 64, after = 16) {
  const t = (text || '').replace(/\s+/g, ' ').trim()
  const i = t.indexOf(k)
  if (i < 0) return { head: shortName(t, 140), k: '', tail: '' }
  let a = Math.max(0, i - before), b = Math.min(t.length, i + k.length + after)
  if (a > 0) a = t.indexOf(' ', a) + 1 || a
  if (b < t.length) b = t.lastIndexOf(' ', b) > i + k.length ? t.lastIndexOf(' ', b) : b
  return { head: (a > 0 ? '…' : '') + t.slice(a, i), k, tail: t.slice(i + k.length, b) + (b < t.length ? '…' : '') }
}

/* The query depth a saved assessment was computed and is re-checked at. Assessments saved before depth was stored
   carry 'legacy': their depth is read from the saved payload, or is the old API default of 4 when that is missing. */
export function depthLabel(h) {
  if (h?.depth == null) return ''
  return `${h.depth} gen${h.depth_source && h.depth_source !== 'recorded' ? ' · legacy' : ''}`
}
