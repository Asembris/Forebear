import React from 'react'

/*
  The Forebear mark: an "F" drawn as a lineage graph. The stem is a chain of generations
  (newest at the top, oldest at the foot); the two arms are citations. The foot node is the
  one ancestor that carries a past - restrained amber - because every clearance has one.
  Geometry is shared with the opening so the assembled mark and the resting mark are identical.
*/
export const MARK = {
  nodes: [
    { id: 'a', x: 11, y: 7, r: 3.6 },   // newest clearance
    { id: 'b', x: 27, y: 7, r: 2.8 },   // top arm
    { id: 'c', x: 11, y: 19, r: 3.0 },  // predicate
    { id: 'd', x: 23, y: 19, r: 2.6 },  // middle arm
    { id: 'e', x: 11, y: 31, r: 3.4, past: true }, // grand-predicate: the past
  ],
  threads: [['a', 'b'], ['a', 'c'], ['c', 'd'], ['c', 'e']],
}

const byId = Object.fromEntries(MARK.nodes.map((n) => [n.id, n]))

export function Mark({ size = 28, className = '', title }) {
  return (
    <svg className={'mark ' + className} width={size} height={size} viewBox="0 0 38 38"
      role={title ? 'img' : undefined} aria-hidden={title ? undefined : true} aria-label={title}>
      {MARK.threads.map(([p, q], i) => (
        <line key={i} className={`mark-thread t${i}`} x1={byId[p].x} y1={byId[p].y} x2={byId[q].x} y2={byId[q].y}
          pathLength="1" />
      ))}
      {MARK.nodes.map((n, i) => (
        <circle key={n.id} className={`mark-node n${i}${n.past ? ' past' : ''}`} cx={n.x} cy={n.y} r={n.r} />
      ))}
    </svg>
  )
}

export function Wordmark({ size = 28, className = '' }) {
  return (
    <span className={'wordmark ' + className}>
      <Mark size={size} />
      <span className="wordmark-name">Forebear</span>
    </span>
  )
}
