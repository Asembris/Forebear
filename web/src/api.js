async function req(path, opts = {}) {
  const r = await fetch(path, {
    headers: { 'content-type': 'application/json' },
    ...opts,
    body: opts.body ? JSON.stringify(opts.body) : undefined,
  })
  let data = null
  try { data = await r.json() } catch { /* empty */ }
  if (!r.ok) {
    const msg = data?.detail ? (typeof data.detail === 'string' ? data.detail : JSON.stringify(data.detail)) : `HTTP ${r.status}`
    throw new Error(msg)
  }
  return data
}

export const api = {
  stats: () => req('/api/stats'),
  search: (q) => req(`/api/search?q=${encodeURIComponent(q)}`),
  assess: (k, depth = 4) => req(`/api/assess/${k}?depth=${depth}`),
  compare: (ks) => req('/api/compare', { method: 'POST', body: { ks } }),
  recallEvent: (e) => req(`/api/recall-event/${e}`),
  watchlist: () => req('/api/watchlist'),
  ingest: (k) => req('/api/ingest', { method: 'POST', body: { k } }),
  review: (src, dst, status, note) => req('/api/citation/review', { method: 'POST', body: { src, dst, status, note } }),
  triage: (src, dst) => req('/api/citation/triage', { method: 'POST', body: { src, dst } }),
  save: (k, note) => req('/api/assessments', { method: 'POST', body: { k, note } }),
  assessments: (k) => req(`/api/assessments${k ? `?k=${k}` : ''}`),
  // Phase 2 agent runs: secondary to the deterministic assessment, shown as history
  investigations: (k, limit = 30) => req(`/api/investigations?limit=${limit}${k ? `&k=${k}` : ''}`),
  investigation: (id) => req(`/api/investigations/${id}`),
  startInvestigation: (k, request, mode = 'auto') => req('/api/investigations', { method: 'POST', body: { k, request, mode } }),
  proposals: (status) => req(`/api/proposals${status ? `?status=${status}` : ''}`),
  decide: (pid, decision, reviewer, note) => req(`/api/proposals/${pid}/decision`, { method: 'POST', body: { decision, reviewer, human: true, note } }),
}

export const pmnUrl = (k) => `https://www.accessdata.fda.gov/scripts/cdrh/cfdocs/cfpmn/pmn.cfm?ID=${k}`
export const reportUrl = (id, md = true) => `/api/investigations/${id}/report${md ? '?format=markdown' : ''}`
