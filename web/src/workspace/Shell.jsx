import React, { Suspense, lazy, useEffect, useRef, useState } from 'react'
import { api } from '../api.js'
import { Wordmark } from '../brand/Mark.jsx'
import Investigation, { Home } from './Investigation.jsx'

const Views = {
  compare: lazy(() => import('./Views.jsx').then((m) => ({ default: m.CompareView }))),
  reach: lazy(() => import('./Views.jsx').then((m) => ({ default: m.ReachView }))),
  watch: lazy(() => import('./Views.jsx').then((m) => ({ default: m.WatchlistView }))),
  ingest: lazy(() => import('./Views.jsx').then((m) => ({ default: m.IngestView }))),
  history: lazy(() => import('./History.jsx')),
  method: lazy(() => import('./Views.jsx').then((m) => ({ default: m.MethodView }))),
}

const I = {
  check: <path d="M11 11l4 4M7 12.5A5.5 5.5 0 107 1.5a5.5 5.5 0 000 11z" />,
  compare: <path d="M2 3h5v10H2zM9 3h5v10H9z" />,
  reach: <path d="M3 8a5 5 0 1010 0A5 5 0 003 8zm3 0a2 2 0 104 0 2 2 0 00-4 0z" />,
  watch: <path d="M1.5 8S4 3 8 3s6.5 5 6.5 5S12 13 8 13 1.5 8 1.5 8zM8 10a2 2 0 100-4 2 2 0 000 4z" />,
  ingest: <path d="M8 2v8m0 0l-3-3m3 3l3-3M2 12v2h12v-2" />,
  history: <path d="M8 4v4l2.5 2M2.5 8a5.5 5.5 0 105.5-5.5A5.6 5.6 0 003 6M3 2.5V6h3.5" />,
  method: <path d="M3 2h7l3 3v9H3zM10 2v3h3M5.5 8h5M5.5 11h5" />,
}
const Icon = ({ name }) => (
  <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">{I[name]}</svg>
)

const NAV = [
  ['Investigate', [['check', 'Predicate check'], ['compare', 'Compare predicates']]],
  ['Recall evidence', [['reach', 'Recall reach'], ['watch', 'Watchlist']]],
  ['Graph', [['ingest', 'Add a clearance'], ['history', 'History'], ['method', 'Method']]],
]

export default function Shell({ route, go, stats, statsErr, refreshStats, onReplay }) {
  const main = useRef(null)
  useEffect(() => { main.current?.focus({ preventScroll: true }) }, [route.tab])
  const View = Views[route.tab]
  return (
    <div className="ws">
      <header className="ws-top">
        <a className="brand" href="#/" aria-label="Forebear home: the film"><Wordmark size={24} /></a>
        <Search go={go} />
        <span className="spacer" />
        <div className="store-chip" title="Live counts from the Relate single-file store">
          <i className={'dot' + (statsErr ? ' off' : '')} aria-hidden="true" />
          {stats ? (
            <span className="counts"><b>{stats.nodes.Device?.toLocaleString('en-US')}</b> devices · <b>{stats.nodes.Recall?.toLocaleString('en-US')}</b> recalls · Relate</span>
          ) : <span>{statsErr ? 'API unavailable' : 'Connecting…'}</span>}
        </div>
      </header>
      <nav className="ws-rail" aria-label="Workspace">
        {NAV.map(([group, items]) => (
          <React.Fragment key={group}>
            <div className="group">{group}</div>
            {items.map(([id, label]) => (
              <a key={id} href={`#/${id}`} aria-current={route.tab === id ? 'page' : undefined}><Icon name={id} />{label}</a>
            ))}
          </React.Fragment>
        ))}
        <div className="rail-foot">
          Verdicts are deterministic documentation signals from FDA records, not safety findings.
          {!matchMedia('(prefers-reduced-motion: reduce)').matches && <div style={{ marginTop: 10 }}><button onClick={onReplay}>Replay the film</button></div>}
        </div>
      </nav>
      <main className="ws-main" id="main" ref={main} tabIndex={-1} style={{ outline: 'none' }}>
        {route.tab === 'check' && (route.arg
          ? <Investigation k={route.arg.toUpperCase()} go={go} onChanged={refreshStats} />
          : <Home go={go} stats={stats} />)}
        {View && (
          <Suspense fallback={<div className="loading-thread"><i />Loading…</div>}>
            <View initial={route.arg} go={go} onChanged={refreshStats} stats={stats} />
          </Suspense>
        )}
        {!View && route.tab !== 'check' && (
          <div className="panel"><p>Unknown page. <a href="#/check">Go to the workspace →</a></p></div>
        )}
        <footer className="ws-foot">
          Public FDA data: openFDA 510(k), recall and enforcement records; 510(k) summary PDFs. Forebear reports documented
          lineage and recall history; it does not judge device safety. Not regulatory advice.
        </footer>
      </main>
    </div>
  )
}

function Search({ go }) {
  const [q, setQ] = useState('')
  const [res, setRes] = useState([])
  const [open, setOpen] = useState(false)
  const [sel, setSel] = useState(0)
  const input = useRef(null)
  const timer = useRef(null)
  useEffect(() => {
    clearTimeout(timer.current)
    if (q.trim().length < 2) { setRes([]); return }
    let live = true                    // drop responses for a query the user has already changed
    timer.current = setTimeout(() => api.search(q).then((r) => { if (live) { setRes(r); setSel(0) } }).catch(() => live && setRes([])), 160)
    return () => { live = false }
  }, [q])
  useEffect(() => {
    const on = (e) => {
      if (e.key === '/' && !/INPUT|TEXTAREA|SELECT/.test(document.activeElement?.tagName)) { e.preventDefault(); input.current?.focus() }
    }
    addEventListener('keydown', on)
    return () => removeEventListener('keydown', on)
  }, [])
  const pick = (k) => { setOpen(false); setQ(''); input.current?.blur(); go('check', k) }
  const show = open && res.length > 0
  return (
    <div className="search" role="search">
      <svg className="icon" width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.6" aria-hidden="true"><path d="M11 11l4 4M7 12.5A5.5 5.5 0 107 1.5a5.5 5.5 0 000 11z" /></svg>
      <input ref={input} className="field" value={q} placeholder="Search a device or K-number"
        aria-label="Search devices by name or K-number" role="combobox" aria-expanded={show} aria-controls="search-results"
        aria-activedescendant={show ? `sr-${sel}` : undefined} aria-autocomplete="list"
        onChange={(e) => { setQ(e.target.value); setOpen(true) }}
        onFocus={() => setOpen(true)} onBlur={() => setTimeout(() => setOpen(false), 150)}
        onKeyDown={(e) => {
          if (e.key === 'ArrowDown') { e.preventDefault(); setSel((s) => Math.min(s + 1, res.length - 1)) }
          else if (e.key === 'ArrowUp') { e.preventDefault(); setSel((s) => Math.max(s - 1, 0)) }
          else if (e.key === 'Escape') { setOpen(false); e.currentTarget.blur() }
          else if (e.key === 'Enter') {
            const v = q.trim().toUpperCase()
            if (/^K\d{6}$/.test(v)) pick(v)
            else if (res[sel]) pick(res[sel].k)
          }
        }} />
      {!q && <kbd aria-hidden="true">/</kbd>}
      {show && (
        <ul className="search-results" id="search-results" role="listbox">
          {res.map((r, i) => (
            <li key={r.k} id={`sr-${i}`} role="option" aria-selected={i === sel} onMouseDown={() => pick(r.k)} onMouseEnter={() => setSel(i)}>
              <span><span className="k">{r.k}</span> {r.name}</span>
              <small>{r.applicant} · {r.decision_date} · {r.product_code}</small>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
