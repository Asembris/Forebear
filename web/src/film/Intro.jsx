import React, { useEffect, useRef, useState } from 'react'
import { Mark } from '../brand/Mark.jsx'

export const INTRO_KEY = 'forebear:intro'
const OPENING_MS = 3000
const LEAVE_MS = 2450

export function introSeen() {
  try { return !!sessionStorage.getItem(INTRO_KEY) } catch { return true }
}
export function markIntroSeen() {
  try { sessionStorage.setItem(INTRO_KEY, 'seen') } catch { /* storage is optional */ }
}
export function forgetIntro() {
  try { sessionStorage.removeItem(INTRO_KEY) } catch { /* storage is optional */ }
}

/*
  About three seconds, once per tab session, only on the landing page. The mark assembles node by
  node and thread by thread, the line is set, then the lockup dissolves into the film's field.
  Presentation only: nothing is loading behind it, and Skip, Escape or any key ends it at once.
*/
export default function Intro({ onDone }) {
  const [leaving, setLeaving] = useState(false)
  const done = useRef(false)
  const skipRef = useRef(null)
  const finish = () => {
    if (done.current) return
    done.current = true
    markIntroSeen()
    setLeaving(true)
    onDone()
  }
  useEffect(() => {
    const leave = setTimeout(finish, LEAVE_MS)
    const key = (e) => { if (e.key === 'Escape' || e.key === 'Enter' || e.key === ' ') { e.preventDefault(); finish() } }
    addEventListener('keydown', key)
    skipRef.current?.focus({ preventScroll: true })
    return () => { clearTimeout(leave); removeEventListener('keydown', key) }
  }, [])
  const [gone, setGone] = useState(false)
  useEffect(() => {
    if (!leaving) return
    const t = setTimeout(() => setGone(true), OPENING_MS - LEAVE_MS + 100)
    return () => clearTimeout(t)
  }, [leaving])
  if (gone) return null
  const word = 'Forebear'.split('')
  return (
    <div className={'intro' + (leaving ? ' is-leaving' : '')} data-testid="intro" onClick={finish}>
      <div className="intro-lockup" aria-hidden="true">
        <Mark className="intro-mark" size={116} />
        <div className="intro-word">
          {word.map((c, i) => <span key={i} style={{ animationDelay: `${0.95 + i * 0.045}s` }}>{c}</span>)}
        </div>
        <p className="intro-tag"><span>Every clearance has <em>a past.</em></span></p>
      </div>
      <span className="sr-only" role="status">Forebear. Every clearance has a past.</span>
      <button ref={skipRef} className="btn btn-line btn-sm intro-skip" onClick={(e) => { e.stopPropagation(); finish() }}>
        Skip intro <span aria-hidden="true">→</span>
      </button>
    </div>
  )
}
