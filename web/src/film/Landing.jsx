import React, { useEffect, useRef, useState } from 'react'
import facts from '../story/facts.json'
import { Wordmark, Mark } from '../brand/Mark.jsx'
import { fmtDate, monthsBetween, pdfAt } from '../evidence.js'
export { useMedia } from '../hooks.js'

/* Reveal when a block enters the frame; hide again when it leaves, so scrolling back replays cleanly. */
function useReveal() {
  const ref = useRef(null)
  useEffect(() => {
    const el = ref.current
    if (!el || typeof IntersectionObserver === 'undefined') { el?.classList.add('in-frame'); return }
    const io = new IntersectionObserver(([e]) => el.classList.toggle('in-frame', e.isIntersecting), { rootMargin: '-12% 0px -12% 0px' })
    io.observe(el)
    return () => io.disconnect()
  }, [])
  return ref
}

/* Scene time follows where each chapter's words actually sit, re-measured on layout change only. */
function readAnchors() {
  const h = innerHeight
  return [...document.querySelectorAll('[data-scene]')]
    .map((el) => {
      const b = el.getBoundingClientRect()
      const top = b.top + scrollY
      const y = el.dataset.align === 'top' ? 0 : top + b.height / 2 - h * 0.5
      return [Math.max(0, y), Number(el.dataset.scene)]
    })
    .sort((a, b) => a[1] - b[1])
    .map((a, i, arr) => (i && a[0] <= arr[i - 1][0] ? [arr[i - 1][0] + 1, a[1]] : a))
}

function canDraw() {
  try {
    const c = document.createElement('canvas')
    return !!c.getContext('2d')
  } catch { return false }
}

/* One fixed canvas behind the page; the CSS scene beneath it is the no-canvas / reduced-motion still. */
function FilmStage({ reduced, introDone, stats, onScene }) {
  const host = useRef(null)
  const film = useRef(null)
  const [live, setLive] = useState(false)
  useEffect(() => {
    if (reduced || !canDraw()) { document.documentElement.dataset.film = 'off'; return }
    let cancelled = false
    const compact = matchMedia('(max-width: 860px), (pointer: coarse)').matches
    import('./renderer.js').then(({ createFilm }) => {
      if (cancelled || !host.current) return
      try {
        film.current = createFilm(host.current, { facts, deviceCount: stats?.nodes?.Device || 1187, compact, onScene })
        film.current.setAnchors(readAnchors())
        film.current.snap()
        delete document.documentElement.dataset.film
        setLive(true)
      } catch { document.documentElement.dataset.film = 'off' }
    }).catch(() => { document.documentElement.dataset.film = 'off' })
    return () => { cancelled = true; film.current?.dispose(); film.current = null }
  }, [reduced])
  useEffect(() => {
    if (!live) return
    const measure = () => film.current?.setAnchors(readAnchors())
    const ro = new ResizeObserver(() => { film.current?.resize(); measure() })
    ro.observe(document.body)
    document.fonts?.ready.then(measure)
    const move = (e) => film.current?.setPointer(e.clientX, e.clientY, true)
    const out = () => film.current?.setPointer(-9999, -9999, false)
    addEventListener('pointermove', move, { passive: true })
    document.addEventListener('pointerleave', out)
    return () => { ro.disconnect(); removeEventListener('pointermove', move); document.removeEventListener('pointerleave', out) }
  }, [live])
  useEffect(() => { if (live && introDone === 'bloom') film.current?.bloom() }, [live, introDone])
  return (
    <div className="film-stage" aria-hidden="true">
      <div className="film-fallback">
        <svg viewBox="0 0 560 320">
          <path d="M520 60 C 380 60, 380 160, 240 160" stroke="#7fa2ff" strokeWidth="1.6" fill="none" />
          <path d="M240 160 C 160 160, 160 80, 80 80 M240 160 C 160 160, 160 250, 70 250" stroke="#7fa2ff" strokeOpacity=".4" fill="none" />
          <path d="M240 160 L 420 160" stroke="#e7a948" strokeDasharray="2 4" />
          <path d="M420 152 l8 8 -8 8 -8 -8z" fill="#e7a948" />
          <circle cx="520" cy="60" r="9" fill="#f1ebdd" stroke="#7fa2ff" strokeWidth="3" />
          <circle cx="240" cy="160" r="7" fill="#e7a948" /><circle cx="80" cy="80" r="6" fill="#e7a948" /><circle cx="70" cy="250" r="6" fill="#9aa7c2" />
        </svg>
      </div>
      <canvas ref={host} className={live ? 'is-live' : ''} data-testid="film-canvas" data-renderer={live ? 'canvas2d' : 'fallback'} />
      <div className="film-vignette" />
    </div>
  )
}

const Line = ({ children }) => <span className="ln"><span>{children}</span></span>

function Chapter({ id, scene, mark, label, place, statement, children, foot }) {
  const ref = useReveal()
  return (
    <article id={id} className={`chapter place-${place}`} aria-labelledby={`${id}-title`}>
      <div ref={ref} className="chapter-copy reveal" data-scene={scene} id={`${id}-copy`}>
        <p className="chapter-label"><span>{mark}</span>{label}</p>
        <h2 className="chapter-statement" id={`${id}-title`}>{statement.map((l, i) => <Line key={i}>{l} </Line>)}</h2>
        {children}
        {foot && <p className="chapter-foot">{foot}</p>}
      </div>
    </article>
  )
}

const INDEX = [
  ['top', 'Opening'], ['the-filing', 'The filing'], ['the-connection', 'The connection'],
  ['the-discovery', 'The discovery'], ['handoff', 'Investigate'],
]

export default function Landing({ go, stats, introDone, onReplay, reduced }) {
  const [solid, setSolid] = useState(false)
  const [scene, setScene] = useState(0)
  const handoff = useReveal()
  useEffect(() => {
    const on = () => setSolid(scrollY > 40)
    on(); addEventListener('scroll', on, { passive: true })
    return () => removeEventListener('scroll', on)
  }, [])
  const c = facts.candidate, p = facts.predicate, r = facts.recall, cit = facts.citation
  const gap = monthsBetween(r.initiated, c.decision_date)
  const yrs = Math.floor(gap / 12), mos = gap % 12
  const n = (x) => (x == null ? '—' : x.toLocaleString('en-US'))
  const quote = cit.quote.split(cit.dst)
  return (
    <div className="film" id="top">
      <FilmStage reduced={reduced} introDone={introDone} stats={stats} onScene={setScene} />
      <header className={'film-top' + (solid ? ' is-solid' : '')}>
        <a href="#/" aria-label="Forebear, start of film" onClick={(e) => { e.preventDefault(); scrollTo({ top: 0 }) }}><Wordmark size={26} /></a>
        <span className="spacer" />
        <nav aria-label="Product">
          <a href="#/check">Investigate</a>
          <a href="#/reach/88058,88071">Recall reach</a>
          <a href="#/watch">Watchlist</a>
          <a href="#/method">Method</a>
        </nav>
        <a className="btn btn-primary btn-sm" href="#/check" data-testid="open-workspace">Open workspace <span className="arr" aria-hidden="true">→</span></a>
      </header>

      <nav className="film-index" aria-label="Film chapters">
        {INDEX.map(([id, label], i) => (
          <a key={id} href={`#${id}`} className={scene === i ? 'on' : ''} aria-current={scene === i ? 'step' : undefined}
            onClick={(e) => { e.preventDefault(); document.getElementById(id === 'top' ? 'top' : `${id}-copy`)?.scrollIntoView({ block: 'center', behavior: reduced ? 'auto' : 'smooth' }) }}>
            <span>{label}</span><i />
          </a>
        ))}
      </nav>

      <main id="main">
        <section className="hero" data-scene="0" data-align="top" aria-labelledby="hero-title">
          <p className="eyebrow">510(k) predicate due diligence</p>
          <h1 id="hero-title" tabIndex={-1} style={{ outline: 'none' }}>Every clearance has <em>a past.</em></h1>
          <p className="hero-lede">
            Forebear reads the predicates out of FDA 510(k) summaries, stores the family tree in a <b>Relate graph</b> joined
            to FDA recall records, and shows in one query whether a predicate, or any of its ancestors, was recalled for a
            design problem, as far back as their summaries can be read: <b>with the page and quote behind every link.</b>
          </p>
          <div className="hero-actions">
            <a className="btn btn-primary" href={`#/check/${c.k}`} data-testid="hero-investigate"
              onClick={(e) => { e.preventDefault(); go('check', c.k, { transition: true }) }}>
              Investigate {c.k} <span className="arr" aria-hidden="true">→</span>
            </a>
            <a className="btn btn-line" href="#the-filing-copy"
              onClick={(e) => { e.preventDefault(); document.getElementById('the-filing-copy')?.scrollIntoView({ block: 'center', behavior: reduced ? 'auto' : 'smooth' }) }}>
              Follow one thread <span aria-hidden="true">↓</span>
            </a>
          </div>
          <div className="hero-proof" aria-label="What is in the shipped graph">
            <div><b>{n(stats?.nodes?.Device)}</b><span>clearances in the graph</span></div>
            <div><b>{n(stats?.citations_by_kind?.predicate)}</b><span>predicate links, each with a page</span></div>
            <div><b>{n(stats?.nodes?.Recall)}</b><span>FDA recall records joined</span></div>
          </div>
          <div className="scroll-cue" aria-hidden="true">Scroll<i /></div>
        </section>

        <Chapter id="the-filing" scene={1} mark="01" label="The filing" place="left"
          statement={['One document', 'tells one step.']}
          foot="A 510(k) summary names its predicate. It does not tell you what became of it.">
          <p className="chapter-body">
            {c.name} (<span className="k">{c.k}</span>) was cleared on {fmtDate(c.decision_date)}. Its 510(k) summary names a
            single predicate, on page {cit.page}:
          </p>
          <figure className="doc" aria-label={`Quote from page ${cit.page} of the ${c.k} summary`}>
            <div className="doc-meta"><span>{c.k} · 510(k) summary</span><span>page {cit.page}</span></div>
            <blockquote style={{ margin: 0 }}>“…{quote[0]}<mark>{cit.dst}</mark>{quote[1]}”</blockquote>
            <div style={{ marginTop: 10 }}><a href={pdfAt(c.summary_url, cit.page)} target="_blank" rel="noreferrer">Open the FDA PDF at page {cit.page} ↗</a></div>
          </figure>
        </Chapter>

        <Chapter id="the-connection" scene={2} mark="02" label="The connection" place="right"
          statement={['Follow the thread', 'back in time.']}
          foot="Each thread is an edge in the graph, stored with its page, quote and source PDF.">
          <p className="chapter-body">
            <span className="k">{c.k}</span> → <span className="k">{p.k}</span>: the <b>{p.name}</b>, cleared to {p.applicant} on {fmtDate(p.decision_date)}.
            And {p.k} cites predicates of its own: {facts.grand_predicates.map((g, i) => (
              <React.Fragment key={g.k}>{i ? (i === facts.grand_predicates.length - 1 ? ' and ' : ', ') : ''}<span className="k">{g.k}</span></React.Fragment>))}.
            FDA's databases answer one hop at a time. Relate walks them all in one variable-length query.
          </p>
        </Chapter>

        <Chapter id="the-discovery" scene={3} mark="03" label="The discovery" place="left"
          statement={['FDA recalls name', <em key="e">the predicate.</em>]}
          foot="A recall on a predicate is not a finding about the new device. It is a question the predicate rationale should answer.">
          <p className="chapter-body">
            On {fmtDate(r.initiated)} a <b>{r.classification}</b> recall of the BiPAP A30 began, root cause <b>{r.root_cause}</b>:
            “{r.reason}…” (event {r.event}, records {r.ids.join(' and ')}).
          </p>
          <div className="fact-row">
            <div className="fact amber"><b>{yrs} yr {mos} mo</b><span>between recall start and {c.k}'s clearance</span></div>
            <div className="fact"><b>Review lineage</b><span>deterministic verdict for {c.k}</span></div>
          </div>
          <p className="chapter-body" style={{ fontSize: 14 }}>
            FDA's 2023 draft guidance recommends predicates not subject to design-related recalls.
          </p>
        </Chapter>

        <section id="handoff" className="handoff" aria-labelledby="handoff-title">
          <div ref={handoff} className="reveal" data-scene="4" id="handoff-copy">
            <p className="lead" id="handoff-title"><Line>Every fact above is real evidence.</Line><Line><em>Now work with it.</em></Line></p>
            <a className="btn btn-primary" href={`#/check/${c.k}`} data-testid="handoff-investigate"
              onClick={(e) => { e.preventDefault(); go('check', c.k, { transition: true }) }}>
              Open the investigation <span className="arr" aria-hidden="true">→</span>
            </a>
            <p className="sub">Every node, date and quote above is read from the shipped Relate store; the background field is illustrative.</p>
          </div>
        </section>

        <section className="paths" aria-labelledby="paths-title">
          <h2 id="paths-title">Or start somewhere else</h2>
          <div className="path-grid">
            <a className="path-card" href="#/reach/88058,88071"><span className="k">Recall 88058 + 88071</span><h3>Recall reach</h3><p>From the June 2021 Philips foam recall: which later clearances descend from it?</p></a>
            <a className="path-card" href="#/watch"><span className="k">Watchlist</span><h3>Cited after a recall</h3><p>Clearances whose predicate was already under a design-related recall.</p></a>
            <a className="path-card" href="#/compare/K200480 K113053 K233643 K143677"><span className="k">Compare</span><h3>Choose a predicate</h3><p>Candidate predicates side by side, with their own and inherited recalls.</p></a>
            <a className="path-card" href="#/check/K251770"><span className="k">K251770</span><h3>SleepRes PAP System</h3><p>Another 2025 clearance, another lineage.</p></a>
          </div>
        </section>
      </main>

      <footer className="film-foot">
        <p>Public FDA data: openFDA 510(k), recall and enforcement records and 510(k) summary PDFs. Forebear reports documented
          lineage and recall history; it does not judge device safety. Not regulatory advice.</p>
        <p style={{ display: 'flex', gap: 14, alignItems: 'center' }}>
          <Mark size={18} />
          {!reduced && <button className="btn btn-quiet btn-sm" onClick={onReplay} data-testid="replay">Replay opening</button>}
        </p>
      </footer>
    </div>
  )
}
