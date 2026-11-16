import React, { useEffect, useRef, useState } from 'react'
import { api } from './api.js'
import CheckView from './CheckView.jsx'
import { CompareView, ReachView, WatchlistView, IngestView, AboutView } from './Views.jsx'

const TABS = [
  ['check', 'Predicate check'],
  ['compare', 'Compare candidates'],
  ['reach', 'Recall reach'],
  ['watch', 'Watchlist'],
  ['ingest', 'Add a clearance'],
  ['about', 'How it works'],
]

function parseHash() {
  const [tab, arg] = window.location.hash.replace(/^#\/?/, '').split('/')
  return { tab: tab || 'check', arg: arg || '' }
}

export default function App() {
  const [route, setRoute] = useState(parseHash())
  const [stats, setStats] = useState(null)
  const [statsErr, setStatsErr] = useState(null)

  useEffect(() => {
    const on = () => setRoute(parseHash())
    window.addEventListener('hashchange', on)
    return () => window.removeEventListener('hashchange', on)
  }, [])
  const refreshStats = () => api.stats().then(setStats).catch((e) => setStatsErr(e.message))
  useEffect(() => { refreshStats() }, [])

  const go = (tab, arg = '') => { window.location.hash = `/${tab}${arg ? '/' + arg : ''}` }

  return (
    <div className="app">
      <header className="top">
        <div className="brand" onClick={() => go('check')}>
          <svg width="26" height="26" viewBox="0 0 32 32" aria-hidden="true">
            <circle cx="8" cy="8" r="5" className="b1" /><circle cx="24" cy="16" r="5" className="b2" /><circle cx="8" cy="24" r="5" className="b2" />
            <path d="M12 9l8 5M12 23l8-5" className="b3" />
          </svg>
          <div>
            <div className="name">Forebear</div>
            <div className="tag">Check a device's 510(k) ancestry before you cite it</div>
          </div>
        </div>
        <Search onPick={(k) => go('check', k)} />
        <div className="stats" title="Live counts from the Relate store">
          {stats ? (
            <>
              <span><b>{stats.nodes.Device?.toLocaleString()}</b> devices</span>
              <span><b>{stats.citations_by_kind.predicate?.toLocaleString()}</b> predicate links</span>
              <span><b>{stats.nodes.Recall?.toLocaleString()}</b> recalls</span>
              <span className="relate">Relate · single-file store</span>
            </>
          ) : <span className="err">{statsErr || 'connecting…'}</span>}
        </div>
      </header>
      <nav className="tabs">
        {TABS.map(([id, label]) => (
          <button key={id} className={route.tab === id ? 'on' : ''} onClick={() => go(id)}>{label}</button>
        ))}
      </nav>
      <main>
        {route.tab === 'check' && <CheckView k={route.arg} go={go} onChanged={refreshStats} />}
        {route.tab === 'compare' && <CompareView initial={route.arg} go={go} />}
        {route.tab === 'reach' && <ReachView initial={route.arg} go={go} />}
        {route.tab === 'watch' && <WatchlistView go={go} />}
        {route.tab === 'ingest' && <IngestView initial={route.arg} go={go} onChanged={refreshStats} />}
        {route.tab === 'about' && <AboutView stats={stats} />}
      </main>
      <footer>
        Public FDA data (openFDA 510(k), recall and enforcement records; 510(k) summary PDFs). Forebear reports
        documented lineage and recall history; it does not judge device safety. Not regulatory advice.
      </footer>
    </div>
  )
}

function Search({ onPick }) {
  const [q, setQ] = useState('')
  const [res, setRes] = useState([])
  const [open, setOpen] = useState(false)
  const timer = useRef(null)
  useEffect(() => {
    clearTimeout(timer.current)
    if (q.trim().length < 2) { setRes([]); return }
    timer.current = setTimeout(() => api.search(q).then(setRes).catch(() => setRes([])), 180)
  }, [q])
  const pick = (k) => { setOpen(false); setQ(''); onPick(k) }
  return (
    <div className="search">
      <input value={q} placeholder="Search a device or K-number, e.g. DreamStation or K252078"
        onChange={(e) => { setQ(e.target.value); setOpen(true) }}
        onFocus={() => setOpen(true)} onBlur={() => setTimeout(() => setOpen(false), 150)}
        onKeyDown={(e) => {
          if (e.key === 'Enter') {
            const v = q.trim().toUpperCase()
            if (/^K\d{6}$/.test(v)) pick(v)
            else if (res[0]) pick(res[0].k)
          }
        }} />
      {open && res.length > 0 && (
        <ul className="results">
          {res.map((r) => (
            <li key={r.k} onMouseDown={() => pick(r.k)}>
              <b>{r.k}</b> {r.name}<span>{r.applicant} · {r.decision_date} · {r.product_code}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
