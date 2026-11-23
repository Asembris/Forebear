import React, { Suspense, lazy, useCallback, useEffect, useState } from 'react'
import { flushSync } from 'react-dom'
import { api } from './api.js'
import Intro, { introSeen, forgetIntro } from './film/Intro.jsx'
import { useMedia } from './hooks.js'
import Shell from './workspace/Shell.jsx'

const Landing = lazy(() => import('./film/Landing.jsx'))

const ALIASES = { about: 'method' }

export function parseHash(h = window.location.hash) {
  if (!h.startsWith('#/')) return { tab: 'film', arg: '' }   // "#the-filing" etc. are anchors inside the film
  const raw = h.replace(/^#\/?/, '')
  if (!raw) return { tab: 'film', arg: '' }
  const [tab, ...rest] = raw.split('/')
  return { tab: ALIASES[tab] || tab || 'film', arg: decodeURIComponent(rest.join('/') || '') }
}
const hashFor = (tab, arg) => (tab === 'film' ? '#/' : `#/${tab}${arg ? '/' + arg : ''}`)

export default function App() {
  const [route, setRoute] = useState(parseHash)
  const [stats, setStats] = useState(null)
  const [statsErr, setStatsErr] = useState(null)
  const reduced = useMedia('(prefers-reduced-motion: reduce)')
  // The opening plays once per tab session, only on the landing page, never under reduced motion,
  // and never in front of a deep link: real work is never delayed.
  const [intro, setIntro] = useState(() => route.tab === 'film' && !introSeen() &&
    !matchMedia('(prefers-reduced-motion: reduce)').matches)
  const [introDone, setIntroDone] = useState(intro ? 'pending' : 'none')

  useEffect(() => {
    document.documentElement.dataset.motion = reduced ? 'reduced' : 'full'
  }, [reduced])
  useEffect(() => {
    const on = () => setRoute(parseHash())
    addEventListener('hashchange', on)
    return () => removeEventListener('hashchange', on)
  }, [])
  // the API may still be opening the store: retry a few times before reporting it unavailable
  const refreshStats = useCallback((attempt = 0) => api.stats().then((s) => { setStats(s); setStatsErr(null) })
    .catch((e) => { if (attempt < 5) setTimeout(() => refreshStats(attempt + 1), 800 * (attempt + 1)); else setStatsErr(e.message) }), [])
  useEffect(() => { refreshStats() }, [refreshStats])

  useEffect(() => {
    const titles = { film: 'Forebear · Every clearance has a past', check: route.arg ? `${route.arg} · Forebear` : 'Investigate · Forebear',
      compare: 'Compare predicates · Forebear', reach: 'Recall reach · Forebear', watch: 'Watchlist · Forebear',
      ingest: 'Add a clearance · Forebear', history: 'History · Forebear', method: 'Method · Forebear' }
    document.title = titles[route.tab] || 'Forebear'
  }, [route])

  const go = useCallback((tab, arg = '', opts = {}) => {
    const h = hashFor(tab, arg)
    const apply = () => {
      history.pushState(null, '', h)
      setRoute(parseHash(h))
      window.scrollTo(0, 0)
    }
    const vt = opts.transition && !reduced && document.startViewTransition
    if (vt) document.startViewTransition(() => flushSync(apply))
    else apply()
  }, [reduced])
  useEffect(() => {
    const on = () => setRoute(parseHash())
    addEventListener('popstate', on)
    return () => removeEventListener('popstate', on)
  }, [])

  const replay = () => {
    forgetIntro()
    if (route.tab !== 'film') go('film')
    window.scrollTo(0, 0)
    if (!reduced) { setIntroDone('pending'); setIntro(true) }
  }

  return (
    <>
      <a className="skip-link" href="#main" onClick={(e) => { e.preventDefault(); document.getElementById('main')?.focus() }}>Skip to content</a>
      {intro && <Intro onDone={() => {
        setIntroDone('bloom')
        setTimeout(() => setIntro(false), 700)
        requestAnimationFrame(() => document.getElementById('hero-title')?.focus({ preventScroll: true }))
      }} />}
      <div inert={intro && introDone === 'pending' ? '' : undefined} style={{ display: 'contents' }}>
      {route.tab === 'film' ? (
        <Suspense fallback={<div style={{ minHeight: '100vh' }} />}>
          <Landing go={go} stats={stats} introDone={introDone} reduced={reduced} />
        </Suspense>
      ) : (
        <Shell route={route} go={go} stats={stats} statsErr={statsErr} refreshStats={refreshStats} onReplay={replay} />
      )}
      </div>
    </>
  )
}
