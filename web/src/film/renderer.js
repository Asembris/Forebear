/*
  The film's single renderer: one fixed Canvas2D behind the landing page, lazy-loaded.
  No Three.js: the story is a graph of documents and threads, which 2D draws more crisply and
  far more cheaply, and the same visual grammar then continues in the workspace's SVG graph.

  Scene time t (0..4) is anchored to where each chapter's words actually sit in the document,
  followed by a critically damped spring so wheel notches never pulse. One rAF loop reads
  scroll once, then draws. Scroll is never hijacked.

    0  the field      the store's clearances as faint points; the pointer is a lamp
    1  the filing     one summary PDF names one predicate, on one page
    2  the connection the thread K252078 -> K113053, then the predicate's own predicates
    3  the discovery  a Class I design recall lights the predicate, before the clearance date
    4  the handoff    the lineage settles into the workspace's generation columns

  Lineage nodes and dates come from web/src/story/facts.json, which tests/test_story_facts.py checks
  against the shipped Relate store. The background field is illustrative: its point count is the
  store's device count, but its positions mean nothing.
*/
import { clamp, keyed, lerp, mapAnchors, rng, smooth, easeOut, stepSpring } from './motion.js'

const C = {
  night: '#070c17', ivory: '#f1ebdd', ink: 'rgba(236,230,216,', blue: '127,162,255', amber: '231,169,72',
  neutral: '#9aa7c2',
}

const yearOf = (d) => {
  const [y, m, dd] = d.split('-').map(Number)
  return y + (m - 1) / 12 + (dd - 1) / 365
}
const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
const monYear = (d) => `${MONTHS[Number(d.slice(5, 7)) - 1]} ${d.slice(0, 4)}`

function buildWorld(facts) {
  const X = (d) => (yearOf(d) - 2007.5) * 62
  const cand = { k: facts.candidate.k, name: facts.candidate.name, date: facts.candidate.decision_date,
    x: X(facts.candidate.decision_date), y: 0, tone: 'self' }
  const pred = { k: facts.predicate.k, name: 'BiPAP A30', date: facts.predicate.decision_date,
    x: X(facts.predicate.decision_date), y: 92, tone: 'design' }
  const gpY = { K092818: -34, K082660: 196, K103167: 286 }
  const gpTone = { K092818: 'design', K082660: 'design', K103167: 'clean' }
  const gps = facts.grand_predicates.map((g) => ({ k: g.k, name: g.name, date: g.decision_date,
    x: X(g.decision_date), y: gpY[g.k] ?? 120, tone: gpTone[g.k] || 'clean' }))
  const recall = { x: X(facts.recall.initiated), y: pred.y, date: facts.recall.initiated,
    label: `${facts.recall.classification} · ${facts.recall.root_cause} · ${monYear(facts.recall.initiated)}` }
  // final layout: the workspace's generation columns (newest right), so the handoff is a settle, not a cut
  const col = { 0: 1060, 1: 760, 2: 460 }
  cand.fx = col[0]; cand.fy = 70
  pred.fx = col[1]; pred.fy = 70
  gps.forEach((g, i) => { g.fx = col[2]; g.fy = -12 + i * 82 })
  return { cand, pred, gps, recall, X, rulerY: 380 }
}

function buildField(n, compact) {
  const r = rng(1187)
  const pts = []
  for (let i = 0; i < n; i++) {
    const z = 0.35 + r() * 0.65
    pts.push({ x: -700 + r() * 2500, y: -720 + r() * 1560, z, ph: r() * Math.PI * 2, d: r() * 0.55 })
  }
  // nearest-neighbour threads through a coarse grid: the field reads as a network, not dust
  const cell = 120, grid = new Map()
  pts.forEach((p, i) => {
    const key = `${Math.floor(p.x / cell)},${Math.floor(p.y / cell)}`
    if (!grid.has(key)) grid.set(key, [])
    grid.get(key).push(i)
  })
  const links = []
  const per = compact ? 1 : 2
  pts.forEach((p, i) => {
    const gx = Math.floor(p.x / cell), gy = Math.floor(p.y / cell)
    const near = []
    for (let a = -1; a <= 1; a++) for (let b = -1; b <= 1; b++) {
      for (const j of grid.get(`${gx + a},${gy + b}`) || []) {
        if (j <= i) continue
        const q = pts[j], dd = (p.x - q.x) ** 2 + (p.y - q.y) ** 2
        if (dd < 140 * 140 && Math.abs(p.z - q.z) < 0.25) near.push([dd, j])
      }
    }
    near.sort((u, v) => u[0] - v[0])
    for (const [, j] of near.slice(0, per)) links.push(i, j)
  })
  return { pts, links: Int32Array.from(links) }
}

export function createFilm(canvas, { facts, deviceCount = 1187, compact = false, onScene }) {
  const ctx = canvas.getContext('2d', { alpha: false })
  if (!ctx) throw new Error('no 2d context')
  const world = buildWorld(facts)
  const field = buildField(compact ? Math.min(560, deviceCount) : deviceCount, compact)
  const scr = new Float32Array(field.pts.length * 3)   // per-frame screen x, y, lamp
  let W = 0, H = 0, dpr = 1, S = 1
  let anchors = [[0, 0]]
  const spring = { value: 0, velocity: 0 }
  let pointer = { x: -9999, y: -9999, on: false }
  let lamp = 0
  let bloomAt = -1
  let raf = 0, last = 0, alive = true
  let lastScene = -1

  function resize() {
    dpr = Math.min(window.devicePixelRatio || 1, compact ? 1.5 : 2)
    W = canvas.clientWidth; H = canvas.clientHeight
    canvas.width = Math.round(W * dpr); canvas.height = Math.round(H * dpr)
    S = compact ? Math.min(W / 760, H / 900) : Math.min(W / 1380, H / 820)
  }

  // camera keys: world centre, zoom, and where the subject sits on screen (clear of the words)
  const camKeys = compact
    ? { cx: [[0, 560], [1, world.cand.x - 40], [2, 620], [3, 620], [4, 760]],
        cy: [[0, 80], [1, -10], [2, 130], [3, 110], [4, 80]],
        z: [[0, 0.9], [1, 1.55], [2, 0.66], [3, 0.66], [4, 0.82]],
        fx: [[0, 0.5], [4, 0.5]], fy: [[0, 0.42], [1, 0.32], [2, 0.3], [3, 0.3], [4, 0.3]] }
    : { cx: [[0, world.cand.x - 230], [1, world.cand.x - 60], [2, 620], [3, 620], [4, 760]],
        cy: [[0, 10], [1, -10], [2, 130], [3, 110], [4, 70]],
        z: [[0, 0.95], [1, 1.75], [2, 0.62], [3, 0.6], [4, 1.0]],
        fx: [[0, 0.64], [1, 0.66], [2, 0.34], [3, 0.66], [4, 0.5]], fy: [[0, 0.5], [3, 0.5], [4, 0.22]] }

  function frame(now) {
    if (!alive) return
    const dt = last ? Math.min(0.05, (now - last) / 1000) : 0
    last = now
    const target = mapAnchors(anchors, window.scrollY)
    if (dt > 0) stepSpring(spring, target, 7.5, dt)
    lamp += ((pointer.on ? 1 : 0) - lamp) * (1 - Math.exp(-6 * dt))
    const t = clamp(spring.value, 0, 4)
    const scene = Math.round(t)
    if (scene !== lastScene) { lastScene = scene; onScene && onScene(scene) }
    draw(t, now / 1000)
    raf = requestAnimationFrame(frame)
  }

  function draw(t, time) {
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
    ctx.fillStyle = C.night
    ctx.fillRect(0, 0, W, H)
    const g = ctx.createRadialGradient(W * 0.7, H * 0.25, 0, W * 0.7, H * 0.25, Math.max(W, H) * 0.8)
    g.addColorStop(0, 'rgba(24,40,74,0.55)'); g.addColorStop(1, 'rgba(7,12,23,0)')
    ctx.fillStyle = g; ctx.fillRect(0, 0, W, H)

    const cx = keyed(camKeys.cx, t), cy = keyed(camKeys.cy, t), zoom = keyed(camKeys.z, t) * S
    const fx = keyed(camKeys.fx, t) * W, fy = keyed(camKeys.fy, t) * H
    const P = (x, y) => [(x - cx) * zoom + fx, (y - cy) * zoom + fy]

    // ---------------------------------------------------------------- field
    const fieldA = keyed([[0, 1], [1, 0.5], [2, 0.42], [3, 0.36], [3.6, 0.2], [4, 0.14]], t)
    const pts = field.pts
    const bloom = bloomAt < 0 ? 1 : clamp((time - bloomAt) / 1.6)
    const ox = W / 2, oy = H * 0.44
    for (let i = 0; i < pts.length; i++) {
      const p = pts[i]
      const par = 0.55 + 0.45 * p.z
      let sx = (p.x - cx * par) * zoom * par + fx + Math.sin(time * 0.18 + p.ph) * 3 * p.z
      let sy = (p.y - cy * par) * zoom * par + fy + Math.cos(time * 0.15 + p.ph) * 3 * p.z
      if (bloom < 1) {
        const b = easeOut(clamp((bloom - p.d * 0.4) / 0.6))
        sx = lerp(ox, sx, b); sy = lerp(oy, sy, b)
      }
      const dl = Math.hypot(sx - pointer.x, sy - pointer.y)
      scr[i * 3] = sx; scr[i * 3 + 1] = sy; scr[i * 3 + 2] = lamp * clamp(1 - dl / 170)
    }
    // threads
    const L = field.links
    ctx.lineWidth = 1
    ctx.strokeStyle = `rgba(${C.blue},${0.07 * fieldA * bloom})`
    ctx.beginPath()
    for (let k = 0; k < L.length; k += 2) {
      const a = L[k] * 3, b = L[k + 1] * 3
      ctx.moveTo(scr[a], scr[a + 1]); ctx.lineTo(scr[b], scr[b + 1])
    }
    ctx.stroke()
    if (lamp > 0.01) {
      ctx.strokeStyle = `rgba(${C.blue},${0.5 * fieldA})`
      ctx.beginPath()
      for (let k = 0; k < L.length; k += 2) {
        const a = L[k] * 3, b = L[k + 1] * 3
        if (scr[a + 2] > 0.15 && scr[b + 2] > 0.15) { ctx.moveTo(scr[a], scr[a + 1]); ctx.lineTo(scr[b], scr[b + 1]) }
      }
      ctx.stroke()
    }
    // points, batched by brightness
    for (let bucket = 0; bucket < 3; bucket++) {
      ctx.fillStyle = `rgba(236,230,216,${(0.14 + bucket * 0.13) * fieldA})`
      ctx.beginPath()
      for (let i = 0; i < pts.length; i++) {
        if (Math.min(2, Math.floor(pts[i].z * 3 - 0.0001)) !== bucket) continue
        const s = 0.8 + pts[i].z * 1.3
        ctx.rect(scr[i * 3] - s / 2, scr[i * 3 + 1] - s / 2, s, s)
      }
      ctx.fill()
    }
    if (lamp > 0.01) {
      ctx.fillStyle = `rgba(${C.blue},${0.9 * fieldA})`
      ctx.beginPath()
      for (let i = 0; i < pts.length; i++) {
        const l = scr[i * 3 + 2]
        if (l > 0.2) { const s = 1.5 + l * 2.2; ctx.rect(scr[i * 3] - s / 2, scr[i * 3 + 1] - s / 2, s, s) }
      }
      ctx.fill()
    }

    // ---------------------------------------------------------------- lineage
    const mix = smooth(3.35, 3.95, t)                              // time layout -> generation columns
    const pos = (n) => P(lerp(n.x, n.fx, mix), lerp(n.y, n.fy, mix))
    const { cand, pred, gps, recall, X, rulerY } = world
    const candA = compact ? smooth(0.3, 0.85, t) : 0.8 + 0.2 * smooth(0.3, 0.85, t)
    const docA = smooth(0.45, 0.95, t) * (1 - smooth(1.65, 2.15, t))
    const threadP = smooth(1.1, 1.7, t)
    const predA = smooth(1.45, 1.8, t)
    const gpA = smooth(1.85, 2.35, t)
    const rulerA = smooth(1.55, 2.1, t) * (1 - mix)
    const recallA = smooth(2.45, 2.85, t)
    const flow = smooth(2.7, 3.25, t)
    const gpAmber = smooth(3.0, 3.4, t)
    if (candA <= 0.001) return

    const [cX, cY] = pos(cand), [pX, pY] = pos(pred)
    const zr = Math.max(0.75, Math.min(1.5, zoom))

    // timeline ruler and the clearance rule
    if (rulerA > 0.01) {
      const [r0x, ry] = P(X('2008-01-01'), rulerY), [r1x] = P(X('2027-01-01'), rulerY)
      ctx.strokeStyle = `rgba(236,230,216,${0.18 * rulerA})`; ctx.lineWidth = 1
      ctx.beginPath(); ctx.moveTo(r0x, ry); ctx.lineTo(r1x, ry); ctx.stroke()
      ctx.font = `500 ${Math.round(10.5 * zr)}px Inter Variable, Inter, system-ui, sans-serif`
      ctx.textAlign = 'center'; ctx.fillStyle = `rgba(236,230,216,${0.4 * rulerA})`
      for (let y = 2008; y <= 2026; y += 2) {
        const [tx] = P(X(`${y}-01-01`), rulerY)
        ctx.fillRect(tx - 0.5, ry - 4, 1, 8)
        ctx.fillText(String(y), tx, ry + 18 * zr)
      }
      ctx.setLineDash([3, 4]); ctx.strokeStyle = `rgba(${C.blue},${0.5 * rulerA})`
      ctx.beginPath(); ctx.moveTo(cX, cY + 16); ctx.lineTo(cX, ry); ctx.stroke(); ctx.setLineDash([])
      ctx.fillStyle = `rgba(${C.blue},${0.85 * rulerA})`; ctx.textAlign = 'center'
      ctx.fillText(`cleared ${monYear(cand.date)}`, cX, ry - 10 * zr)
    }

    // the document: one summary, one page, one highlighted line
    let sx = cX, sy = cY
    if (docA > 0.01) {
      const w = 64 * zr, h = 82 * zr, dx = cX - w - 26 * zr, dy = cY - h - 18 * zr
      ctx.globalAlpha = docA
      ctx.fillStyle = 'rgba(0,0,0,0.35)'; ctx.fillRect(dx + 4, dy + 6, w, h)
      ctx.fillStyle = '#f6f1e5'; ctx.fillRect(dx, dy, w, h)
      ctx.fillStyle = '#d6cdb9'
      for (let i = 0; i < 9; i++) if (i !== 5) ctx.fillRect(dx + 8 * zr, dy + (12 + i * 7.2) * zr, w - (i % 3 === 2 ? 26 : 16) * zr, 2.2 * zr)
      ctx.fillStyle = 'rgba(91,130,240,0.9)'; ctx.fillRect(dx + 8 * zr, dy + (12 + 5 * 7.2) * zr - 0.6, w - 14 * zr, 3.4 * zr)
      ctx.fillStyle = '#6c6656'; ctx.font = `600 ${Math.round(7.5 * zr)}px Inter Variable, Inter, system-ui`
      ctx.textAlign = 'left'; ctx.fillText('p. 6', dx + 7 * zr, dy + h - 6 * zr)
      ctx.globalAlpha = 1
      // the thread is born at the highlighted line, then hands its origin to the node
      const hx = dx + w - 6 * zr, hy = dy + (12 + 5 * 7.2) * zr + 1
      const k = smooth(1.65, 2.15, t)
      sx = lerp(hx, cX, k); sy = lerp(hy, cY, k)
      ctx.strokeStyle = `rgba(${C.blue},${0.55 * docA})`; ctx.lineWidth = 1
      ctx.beginPath(); ctx.moveTo(hx, hy); ctx.quadraticCurveTo(cX - 10 * zr, hy, cX - 6, cY - 4); ctx.stroke()
    }

    const curve = (ax, ay, bx, by) => {
      const mx = (ax + bx) / 2
      return [ax, ay, mx, ay, mx, by, bx, by]
    }
    const bez = (c, u) => {
      const v = 1 - u
      return [v * v * v * c[0] + 3 * v * v * u * c[2] + 3 * v * u * u * c[4] + u * u * u * c[6],
        v * v * v * c[1] + 3 * v * v * u * c[3] + 3 * v * u * u * c[5] + u * u * u * c[7]]
    }
    const stroke = (c, from, to, style, width) => {
      if (to <= from) return
      ctx.strokeStyle = style; ctx.lineWidth = width; ctx.beginPath()
      const steps = 48
      for (let i = 0; i <= steps; i++) {
        const u = from + (to - from) * (i / steps), [x, y] = bez(c, u)
        i ? ctx.lineTo(x, y) : ctx.moveTo(x, y)
      }
      ctx.stroke()
    }

    // grand-predicate threads (predicate -> its predicates)
    gps.forEach((gp, i) => {
      const a = clamp(gpA * 1.6 - i * 0.3)
      if (a <= 0) return
      const [gX, gY] = pos(gp)
      const c = curve(pX, pY, gX, gY)
      stroke(c, 0, a, `rgba(${C.blue},${0.38})`, 1.2)
      if (gp.tone === 'design' && gpAmber > 0) stroke(c, 0, gpAmber, `rgba(${C.amber},${0.5 * gpAmber})`, 1.6)
    })
    // the thread: candidate -> predicate
    const main = curve(sx, sy, pX, pY)
    stroke(main, 0, threadP, `rgba(${C.blue},0.9)`, 1.8 * zr)
    if (flow > 0) {
      // amber travels from the recalled predicate back along the thread to the new clearance
      stroke(main, 1 - flow, 1, `rgba(${C.amber},0.22)`, 7 * zr)
      stroke(main, 1 - flow, 1, `rgba(${C.amber},0.95)`, 2 * zr)
    }
    if (threadP > 0.2 && threadP < 1) {
      const [hx, hy] = bez(main, threadP)
      ctx.fillStyle = `rgba(${C.blue},1)`; ctx.beginPath(); ctx.arc(hx, hy, 2.6 * zr, 0, Math.PI * 2); ctx.fill()
    }
    if (threadP > 0.5 && mix < 0.5) {
      const [lx, ly] = bez(main, 0.5)
      ctx.globalAlpha = smooth(0.5, 0.9, threadP) * (1 - mix * 2)
      ctx.font = `500 ${Math.round(10.5 * zr)}px Inter Variable, Inter, system-ui`
      ctx.textAlign = 'center'; ctx.fillStyle = 'rgba(236,230,216,0.7)'
      ctx.fillText('cites · page 6', lx, ly - 9 * zr)
      ctx.globalAlpha = 1
    }

    // recall: diamond on the predicate's life line, dated before the clearance
    if (recallA > 0.01 && mix < 1) {
      const [rX, rY] = P(recall.x, recall.y)
      const a = recallA * (1 - mix)
      ctx.setLineDash([2, 4]); ctx.strokeStyle = `rgba(${C.amber},${0.7 * a})`; ctx.lineWidth = 1.2
      ctx.beginPath(); ctx.moveTo(pX + 10, pY); ctx.lineTo(rX - 8, rY); ctx.stroke(); ctx.setLineDash([])
      const s = 8 * zr * (0.6 + 0.4 * easeOut(recallA))
      const pulse = (time % 2.6) / 2.6
      ctx.strokeStyle = `rgba(${C.amber},${(1 - pulse) * 0.5 * a})`; ctx.lineWidth = 1
      ctx.beginPath(); ctx.arc(rX, rY, s + pulse * 26 * zr, 0, Math.PI * 2); ctx.stroke()
      ctx.fillStyle = `rgba(${C.amber},${a})`
      ctx.beginPath(); ctx.moveTo(rX, rY - s); ctx.lineTo(rX + s, rY); ctx.lineTo(rX, rY + s); ctx.lineTo(rX - s, rY); ctx.closePath(); ctx.fill()
      ctx.font = `600 ${Math.round(11 * zr)}px Inter Variable, Inter, system-ui`; ctx.textAlign = 'center'
      ctx.fillText(recall.label, rX, rY + s + 18 * zr)
      ctx.font = `500 ${Math.round(10 * zr)}px Inter Variable, Inter, system-ui`
      ctx.fillStyle = `rgba(236,230,216,${0.6 * a})`
      ctx.fillText('recall begins', rX, rY - s - 10 * zr)
    }

    // nodes
    const node = (n, alpha, toneAmt) => {
      if (alpha <= 0.01) return
      const [x, y] = pos(n)
      const self = n.tone === 'self'
      const r = (self ? 9 : 6.5) * zr
      ctx.globalAlpha = alpha
      if (toneAmt > 0) {
        const glow = ctx.createRadialGradient(x, y, 0, x, y, r * 4)
        glow.addColorStop(0, `rgba(${C.amber},${0.35 * toneAmt})`); glow.addColorStop(1, `rgba(${C.amber},0)`)
        ctx.fillStyle = glow; ctx.beginPath(); ctx.arc(x, y, r * 4, 0, Math.PI * 2); ctx.fill()
      }
      ctx.fillStyle = self ? C.ivory : toneAmt > 0.5 ? `rgb(${C.amber})` : C.neutral
      ctx.strokeStyle = self ? `rgb(${C.blue})` : C.night; ctx.lineWidth = self ? 3 : 2
      ctx.beginPath(); ctx.arc(x, y, r, 0, Math.PI * 2); ctx.fill(); ctx.stroke()
      ctx.textAlign = 'left'
      ctx.font = `600 ${Math.round((self ? 13 : 11.5) * zr)}px Cascadia Mono, ui-monospace, Consolas, monospace`
      ctx.fillStyle = C.ivory
      const lx = x + r + 8 * zr
      ctx.fillText(n.k, lx, y - 1 * zr)
      ctx.font = `500 ${Math.round(10.5 * zr)}px Inter Variable, Inter, system-ui`
      ctx.fillStyle = 'rgba(236,230,216,0.55)'
      ctx.fillText(`${n.name} · ${n.date.slice(0, 4)}`, lx, y + 13 * zr)
      ctx.globalAlpha = 1
    }
    gps.forEach((gp, i) => node(gp, clamp(gpA * 1.6 - i * 0.3), gp.tone === 'design' ? gpAmber : 0))
    node(pred, predA, smooth(2.55, 2.9, t))
    node(cand, candA, 0)
  }

  resize()
  raf = requestAnimationFrame(frame)
  const onVis = () => {
    if (document.hidden) { cancelAnimationFrame(raf); raf = 0 }
    else if (!raf && alive) { last = 0; raf = requestAnimationFrame(frame) }   // never integrate the gap
  }
  document.addEventListener('visibilitychange', onVis)

  return {
    setAnchors(a) { anchors = a.length ? a : [[0, 0]] },
    snap() { spring.value = mapAnchors(anchors, window.scrollY); spring.velocity = 0 },
    setPointer(x, y, on = true) { pointer = { x, y, on } },
    bloom() { bloomAt = performance.now() / 1000 },
    resize,
    dispose() { alive = false; cancelAnimationFrame(raf); document.removeEventListener('visibilitychange', onVis) },
  }
}
