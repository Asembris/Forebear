/*
  The film. Two fixed canvases behind the landing page, lazy-loaded with it:
    field  WebGL2 (field-gl.js): the living network of clearances, nebula, signals, recall shockwave.
           Canvas2D fallback when the GPU is weak or WebGL2 is missing.
    story  Canvas2D: the one real lineage, its thread, the recall, labels set at a constant screen size.

  Scene time t (0..4) is anchored to where each chapter's words sit in the document and follows a
  critically damped spring, so wheel notches never pulse. One rAF loop reads scroll once, then draws.
  Scroll is never hijacked.

    0  the field       the store's clearances, alive; one of them is K252078
    1  the filing      one summary PDF names one predicate, on one page
    2  the connection  the thread runs back in time to K113053, then to its own predicates
    3  the discovery   a Class I design recall lights the predicate; the gap to the clearance is measured
    4  the handoff     the lineage settles into the workspace's generation columns

  Every scene is framed into the space its copy leaves free (measured, not guessed), so picture and
  words never collide at any viewport. Lineage facts come from story/facts.json, which
  tests/test_story_facts.py checks against the shipped Relate store.
*/
import { clamp, keyed, lerp, mapAnchors, rng, smooth, easeOut, stepSpring } from './motion.js'
import { capableGL, createField } from './field-gl.js'

const BLUE = '127,162,255', AMBER = '231,169,72', IVORY = '#f1ebdd', NEUTRAL = '#9aa7c2', NIGHT = '#070c17'
const MONO = 'Cascadia Mono, ui-monospace, Consolas, monospace'
const SANS = 'Inter Variable, Inter, system-ui, sans-serif'
const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
const monYear = (d) => `${MONTHS[Number(d.slice(5, 7)) - 1]} ${d.slice(0, 4)}`
const yearOf = (d) => { const [y, m, dd] = d.split('-').map(Number); return y + (m - 1) / 12 + (dd - 1) / 365 }

function monthsBetween(a, b) {
  const [ya, ma, da] = a.split('-').map(Number), [yb, mb, db] = b.split('-').map(Number)
  return (yb - ya) * 12 + (mb - ma) - (db < da ? 1 : 0)
}

function buildWorld(facts, compact) {
  const X = (d) => (yearOf(d) - 2007.5) * 62
  const cand = { k: facts.candidate.k, name: facts.candidate.name, date: facts.candidate.decision_date,
    x: X(facts.candidate.decision_date), y: 0, tone: 'self' }
  const pred = { k: facts.predicate.k, name: 'BiPAP A30', date: facts.predicate.decision_date,
    x: X(facts.predicate.decision_date), y: 96, tone: 'design' }
  const gpY = { K092818: -40, K082660: 200, K103167: 300 }
  const gpTone = { K092818: 'design', K082660: 'design', K103167: 'clean' }
  const gps = facts.grand_predicates.map((g) => ({ k: g.k, name: g.name, date: g.decision_date,
    x: X(g.decision_date), y: gpY[g.k] ?? 120, tone: gpTone[g.k] || 'clean' }))
  const gap = monthsBetween(facts.recall.initiated, facts.candidate.decision_date)
  const recall = { x: X(facts.recall.initiated), y: pred.y, date: facts.recall.initiated,
    label: `${facts.recall.classification} · ${facts.recall.root_cause} · ${monYear(facts.recall.initiated)}`,
    gap: `${Math.floor(gap / 12)} yr ${gap % 12} mo before clearance` }
  // the workspace's generation columns (newest right): the handoff settles into them
  cand.fx = 900; cand.fy = 90
  pred.fx = 600; pred.fy = 90
  gps.forEach((g, i) => { g.fx = 300; g.fy = -10 + i * 100 })
  if (compact) {
    // portrait: a vertical schematic, newest at the top. Dates are labelled; no compressed ruler pretends to scale.
    Object.assign(cand, { x: 0, y: 0, fx: 0, fy: 0 })
    Object.assign(pred, { x: 0, y: 210, fx: 0, fy: 210 })
    Object.assign(recall, { x: -96, y: 92 })
    gps.forEach((g, i) => Object.assign(g, { x: 46, y: 330 + i * 72, fx: 46, fy: 330 + i * 72 }))
  }
  return { cand, pred, gps, recall, X, rulerY: 400, page: facts.citation.page, compact }
}

/* Fallback field (no WebGL2): the same network on Canvas2D, lighter. */
function buildField2D(n) {
  const r = rng(1187), pts = []
  for (let i = 0; i < n; i++) pts.push({ x: -1500 + r() * 4300, y: -1300 + r() * 2900, z: 0.3 + r() * 0.7, ph: r() * 6.28 })
  const cell = 170, grid = new Map(), links = []
  pts.forEach((p, i) => { const k = `${Math.floor(p.x / cell)},${Math.floor(p.y / cell)}`; (grid.get(k) || grid.set(k, []).get(k)).push(i) })
  pts.forEach((p, i) => {
    const gx = Math.floor(p.x / cell), gy = Math.floor(p.y / cell), near = []
    for (let a = -1; a <= 1; a++) for (let b = -1; b <= 1; b++) for (const j of grid.get(`${gx + a},${gy + b}`) || []) {
      if (j <= i) continue
      const q = pts[j], d = (p.x - q.x) ** 2 + (p.y - q.y) ** 2
      if (d < 190 * 190 && Math.abs(p.z - q.z) < 0.3) near.push([d, j])
    }
    near.sort((u, v) => u[0] - v[0]).slice(0, 2).forEach(([, j]) => links.push([i, j, 0.08 + r() * 0.2, r()]))
  })
  return { pts, links }
}

export function createFilm(story, { glCanvas, facts, deviceCount = 1187, compact = false, forceGL = false, onScene, onRenderer }) {
  const ctx = story.getContext('2d')
  if (!ctx) throw new Error('no 2d context')
  const world = buildWorld(facts, compact)
  let field = null
  if (glCanvas && capableGL(forceGL)) {
    try { field = createField(glCanvas, { devices: deviceCount, compact, onLost: () => { field = null; glCanvas.style.display = 'none'; onRenderer && onRenderer('canvas2d') } }) }
    catch { field = null }
  }
  if (!field && glCanvas) glCanvas.style.display = 'none'
  const f2d = field ? null : buildField2D(compact ? 420 : Math.min(900, deviceCount))
  const scr2d = f2d ? new Float32Array(f2d.pts.length * 3) : null

  let W = 0, H = 0, dpr = 1
  let anchors = [[0, 0]]
  let zones = null
  let frames = []
  const spring = { value: 0, velocity: 0 }
  let pointer = { x: -9999, y: -9999, on: false }
  let lamp = 0, bloomAt = -1, raf = 0, last = 0, alive = true, lastScene = -1

  /* Fit a world box into a screen zone. Labels sit right of nodes at a constant size, so pad for them. */
  function fit(box, zone, zmin, zmax, pad = compact ? { l: 14, r: 118, t: 40, b: 50 } : { l: 24, r: 210, t: 46, b: 56 }) {
    const aw = Math.max(80, zone[2] - zone[0] - pad.l - pad.r), ah = Math.max(80, zone[3] - zone[1] - pad.t - pad.b)
    const bw = Math.max(1, box[2] - box[0]), bh = Math.max(1, box[3] - box[1])
    const z = clamp(Math.min(aw / bw, ah / bh), zmin, zmax)
    return { cx: (box[0] + box[2]) / 2, cy: (box[1] + box[3]) / 2, z, sx: zone[0] + pad.l + aw / 2, sy: zone[1] + pad.t + ah / 2 }
  }
  function layout() {
    const { cand, pred, gps, recall, rulerY } = world
    const all = [cand, pred, ...gps]
    const xs = all.map((n) => n.x), ys = all.map((n) => n.y)
    const story = compact ? [Math.min(...xs, recall.x), Math.min(...ys), Math.max(...xs), Math.max(...ys)]
      : [Math.min(...xs), Math.min(...ys), Math.max(...xs, recall.x), rulerY]
    const fxs = all.map((n) => n.fx), fys = all.map((n) => n.fy)
    const final = [Math.min(...fxs), Math.min(...fys), Math.max(...fxs), Math.max(...fys)]
    const z = zones || {}
    const free = (s, fallback) => z[s] || fallback
    const top = [0.04 * W, 0.09 * H, 0.96 * W, 0.53 * H]
    const zHero = compact ? [0.1 * W, 0.08 * H, 0.9 * W, 0.4 * H] : free(0, [0.56 * W, 0.2 * H, 0.94 * W, 0.8 * H])
    const z1 = compact ? top : free(1, [0.55 * W, 0.15 * H, 0.95 * W, 0.85 * H])
    const z2 = compact ? top : free(2, [0.03 * W, 0.12 * H, 0.6 * W, 0.9 * H])
    const z3 = compact ? top : free(3, [0.42 * W, 0.12 * H, 0.97 * W, 0.9 * H])
    const z4 = compact ? [0.04 * W, 0.12 * H, 0.96 * W, 0.46 * H] : free(4, [0.16 * W, 0.12 * H, 0.84 * W, 0.47 * H])
    const pt = (n) => [n.x, n.y, n.x, n.y]
    frames = [
      fit(pt(cand), zHero, 1, 1),
      fit(pt(cand), z1, 1.5, 1.5, compact ? { l: 110, r: 120, t: 120, b: 30 } : { l: 120, r: 210, t: 120, b: 40 }),
      fit(story, z2, 0.15, 1.2),
      fit(story, z3, 0.15, 1.2),
      fit(final, z4, 0.15, 1.25, compact ? { l: 14, r: 118, t: 60, b: 30 } : { l: 24, r: 220, t: 70, b: 40 }),
    ]
  }

  function resize() {
    dpr = Math.min(window.devicePixelRatio || 1, compact ? 1.5 : 1.75)
    W = story.clientWidth; H = story.clientHeight
    story.width = Math.round(W * dpr); story.height = Math.round(H * dpr)
    field?.resize(W, H, dpr)
    layout()
  }

  const cam = (t) => {
    const k = (key) => keyed(frames.map((f, i) => [i, f[key]]), t)
    return { cx: k('cx'), cy: k('cy'), z: k('z'), sx: k('sx'), sy: k('sy') }
  }

  function frame(now) {
    if (!alive) return
    const dt = last ? Math.min(1 / 30, (now - last) / 1000) : 0
    last = now
    if (dt > 0) stepSpring(spring, mapAnchors(anchors, window.scrollY), 7.5, dt)
    lamp += ((pointer.on ? 1 : 0) - lamp) * (1 - Math.exp(-6 * dt))
    const t = clamp(spring.value, 0, 4)
    const scene = Math.round(t)
    if (scene !== lastScene) { lastScene = scene; onScene && onScene(scene) }
    // past the last scene the picture scrolls away with the page, so the handoff copy never slides over it
    const over = Math.max(0, window.scrollY - anchors[anchors.length - 1][0])
    draw(t, now / 1000, over)
    raf = requestAnimationFrame(frame)
  }

  function chip(x, y, rows, { align = 'left', bg = 'rgba(7,12,23,0.72)', stroke = 'rgba(236,228,210,0.12)', pad = 7, alpha = 1 } = {}) {
    if (alpha <= 0.01) return
    ctx.save(); ctx.globalAlpha = alpha
    let w = 0, h = 0
    for (const r of rows) { ctx.font = r.font; w = Math.max(w, ctx.measureText(r.text).width); h += r.lh }
    const bx = align === 'center' ? x - w / 2 - pad : align === 'right' ? x - w - pad * 2 : x
    const by = y - h / 2 - pad / 1.4
    ctx.fillStyle = bg; ctx.strokeStyle = stroke; ctx.lineWidth = 1
    ctx.beginPath(); ctx.roundRect(bx, by, w + pad * 2, h + pad * 1.4, 6); ctx.fill(); ctx.stroke()
    let cy = by + pad / 1.4
    ctx.textAlign = 'left'; ctx.textBaseline = 'top'
    for (const r of rows) { ctx.font = r.font; ctx.fillStyle = r.color; ctx.fillText(r.text, bx + pad, cy + (r.lh - r.size) / 2 - 1); cy += r.lh }
    ctx.restore()
    return [bx, by, w + pad * 2, h + pad * 1.4]
  }
  const nodeLabel = (n) => compact
    ? [{ text: `${n.k} · ${n.date.slice(0, 4)}`, font: `600 11px ${MONO}`, color: IVORY, lh: 14, size: 11 }]
    : [{ text: n.k, font: `600 13px ${MONO}`, color: IVORY, lh: 17, size: 13 },
      { text: `${n.name} · ${n.date.slice(0, 4)}`, font: `500 11.5px ${SANS}`, color: 'rgba(236,230,216,0.72)', lh: 15, size: 11.5 }]

  function drawField2D(P, c, t, time, fieldA, bloom, shock) {
    const { pts, links } = f2d
    const ox = W / 2, oy = H * 0.44
    for (let i = 0; i < pts.length; i++) {
      const p = pts[i], par = 0.5 + 0.5 * p.z
      const fx = Math.sin(p.y * 0.0024 * 1.7 + time * 0.16 + p.ph) * (28 + 34 * p.z)
      const fy = Math.cos(p.x * 0.0024 * 1.9 + time * 0.13 + p.ph) * (28 + 34 * p.z)
      let sx = (p.x + fx - c.cx * par) * c.z * par + c.sx, sy = (p.y + fy - c.cy * par) * c.z * par + c.sy
      if (bloom < 1) { const b = easeOut(clamp((bloom - (p.ph % 1) * 0.45) / 0.55)); sx = lerp(ox, sx, b); sy = lerp(oy, sy, b) }
      scr2d[i * 3] = sx; scr2d[i * 3 + 1] = sy; scr2d[i * 3 + 2] = lamp * clamp(1 - Math.hypot(sx - pointer.x, sy - pointer.y) / 200)
    }
    ctx.lineWidth = 1; ctx.strokeStyle = `rgba(${BLUE},${0.09 * fieldA})`; ctx.beginPath()
    for (const [a, b] of links) { ctx.moveTo(scr2d[a * 3], scr2d[a * 3 + 1]); ctx.lineTo(scr2d[b * 3], scr2d[b * 3 + 1]) }
    ctx.stroke()
    ctx.fillStyle = `rgba(236,230,216,${0.45 * fieldA})`; ctx.beginPath()
    for (let i = 0; i < pts.length; i++) { const s = 1 + pts[i].z * 2 + scr2d[i * 3 + 2] * 3; ctx.rect(scr2d[i * 3] - s / 2, scr2d[i * 3 + 1] - s / 2, s, s) }
    ctx.fill()
    ctx.fillStyle = `rgba(${BLUE},${0.85 * fieldA})`; ctx.beginPath()
    for (let n = 0; n < links.length; n += 3) {
      const [a, b, spd, off] = links[n], u = (time * spd + off) % 1
      const x = lerp(scr2d[a * 3], scr2d[b * 3], u), y = lerp(scr2d[a * 3 + 1], scr2d[b * 3 + 1], u)
      ctx.moveTo(x + 1.8, y); ctx.arc(x, y, 1.8 * Math.sin(Math.PI * u) + 0.2, 0, 6.283)
    }
    ctx.fill()
    if (shock[3] > 0.01) {
      ctx.strokeStyle = `rgba(${AMBER},${0.5 * shock[3]})`; ctx.lineWidth = 2
      ctx.beginPath(); ctx.arc(shock[0], shock[1], shock[2], 0, 6.283); ctx.stroke()
    }
  }

  function draw(t, time, over = 0) {
    const c = cam(t)
    c.sy -= over
    const mix = smooth(3.35, 3.95, t)
    const { cand, pred, gps, recall, X, rulerY } = world
    const P = (x, y) => [(x - c.cx) * c.z + c.sx, (y - c.cy) * c.z + c.sy]
    const pos = (n) => P(lerp(n.x, n.fx, mix), lerp(n.y, n.fy, mix))
    const [cX, cY] = pos(cand), [pX, pY] = pos(pred)
    const [rX, rY] = P(recall.x, recall.y)

    const fieldA = keyed([[0, 1], [1, 0.78], [2, 0.66], [3, 0.62], [4, 0.5]], t)
    const bloom = bloomAt < 0 ? 1 : clamp((time - bloomAt) / 1.7)
    const recallA = smooth(2.42, 2.82, t)
    const sweep = clamp((t - 2.45) / 0.85)
    const ambient = (time % 3.2) / 3.2
    const shockR = sweep < 1 ? easeOut(sweep) * Math.max(W, H) * 0.7 : 30 + ambient * 220
    const shockS = sweep < 1 ? recallA * (1 - sweep * 0.7) : recallA * 0.5 * (1 - ambient) * (1 - mix)
    const shock = [rX, rY, shockR, t > 2.42 ? shockS : 0]

    if (field) {
      field.render({ time, cx: c.cx, cy: c.cy, zoom: c.z, sx: c.sx, sy: c.sy, field: fieldA, ptr: [pointer.x, pointer.y], lamp,
        shock, bloom, origin: [W / 2, H * 0.44], amber: smooth(2.5, 2.95, t) * (1 - mix * 0.5), amberPos: [rX, rY] })
    }
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
    if (field) ctx.clearRect(0, 0, W, H)
    else {
      ctx.fillStyle = NIGHT; ctx.fillRect(0, 0, W, H)
      const g = ctx.createRadialGradient(W * 0.72, H * 0.26, 0, W * 0.72, H * 0.26, Math.max(W, H) * 0.8)
      g.addColorStop(0, 'rgba(24,40,74,0.6)'); g.addColorStop(1, 'rgba(7,12,23,0)')
      ctx.fillStyle = g; ctx.fillRect(0, 0, W, H)
      drawField2D(P, c, t, time, fieldA, bloom, shock)
    }
    if (bloom < 0.35) return

    const docA = smooth(0.4, 0.85, t) * (1 - smooth(1.5, 1.95, t))
    const threadP = smooth(1.05, 1.75, t)
    const predA = smooth(1.35, 1.7, t)
    const gpA = smooth(1.55, 2.0, t)
    const out = 1 - smooth(3.3, 3.6, t)           // story furniture leaves before the settle
    const rulerA = smooth(1.45, 1.95, t) * out
    const flow = smooth(2.62, 3.2, t)
    const gpAmber = smooth(2.95, 3.35, t)
    const gapA = smooth(2.75, 3.1, t) * out

    // ruler and clearance line
    if (rulerA > 0.01 && !compact) {
      const [r0x, ry] = P(X('2008-01-01'), rulerY), [r1x] = P(X('2027-01-01'), rulerY)
      ctx.globalAlpha = rulerA
      ctx.strokeStyle = 'rgba(236,230,216,0.28)'; ctx.lineWidth = 1
      ctx.beginPath(); ctx.moveTo(r0x, ry); ctx.lineTo(r1x, ry); ctx.stroke()
      ctx.font = `500 11px ${MONO}`; ctx.textAlign = 'center'; ctx.textBaseline = 'alphabetic'
      for (let y = 2008; y <= 2026; y++) {
        const [tx] = P(X(`${y}-01-01`), rulerY), major = y % 2 === 0
        ctx.fillStyle = `rgba(236,230,216,${major ? 0.6 : 0.3})`
        ctx.fillRect(tx - 0.5, ry - (major ? 5 : 3), 1, major ? 10 : 6)
        if (major) ctx.fillText(String(y), tx, ry + 22)
      }
      ctx.setLineDash([3, 5]); ctx.strokeStyle = `rgba(${BLUE},0.65)`
      ctx.beginPath(); ctx.moveTo(cX, cY + 16); ctx.lineTo(cX, ry); ctx.stroke(); ctx.setLineDash([])
      ctx.globalAlpha = 1
      chip(cX, ry - 16, [{ text: `cleared ${monYear(cand.date)}`, font: `600 11.5px ${SANS}`, color: `rgb(${BLUE})`, lh: 14, size: 11.5 }], { align: 'center', alpha: rulerA })
    }
    // the measured gap: recall start -> clearance, on the ruler
    if (gapA > 0.01 && compact) {
      chip(W / 2, (zones ? 0 : 0) + H * 0.09 + 14, [{ text: recall.gap, font: `700 12.5px ${SANS}`, color: `rgb(${AMBER})`, lh: 15, size: 12.5 }],
        { align: 'center', alpha: gapA, stroke: `rgba(${AMBER},0.45)` })
    }
    if (gapA > 0.01 && !compact) {
      const [, ry] = P(0, rulerY), y = ry - 44, x0 = rX, x1 = cX
      const grow = easeOut(gapA)
      ctx.strokeStyle = `rgba(${AMBER},${0.9 * gapA})`; ctx.fillStyle = `rgba(${AMBER},${0.12 * gapA})`; ctx.lineWidth = 1.5
      ctx.fillRect(x0, y - 8, (x1 - x0) * grow, 16)
      ctx.beginPath(); ctx.moveTo(x0, y - 10); ctx.lineTo(x0, y + 10); ctx.moveTo(x0, y); ctx.lineTo(x0 + (x1 - x0) * grow, y)
      if (grow > 0.98) { ctx.moveTo(x1, y - 10); ctx.lineTo(x1, y + 10) }
      ctx.stroke()
      ctx.setLineDash([2, 4]); ctx.beginPath(); ctx.moveTo(x0, rY + 12); ctx.lineTo(x0, ry); ctx.stroke(); ctx.setLineDash([])
      chip((x0 + x1) / 2, y - 24, [{ text: recall.gap, font: `700 13px ${SANS}`, color: `rgb(${AMBER})`, lh: 16, size: 13 }],
        { align: 'center', alpha: gapA, stroke: `rgba(${AMBER},0.45)` })
    }

    // curves
    const curve = compact
      ? (ax, ay, bx, by) => { const my = (ay + by) / 2; return [ax, ay, ax, my, bx, my, bx, by] }
      : (ax, ay, bx, by) => { const mx = (ax + bx) / 2; return [ax, ay, mx, ay, mx, by, bx, by] }
    const bez = (q, u) => { const v = 1 - u; return [v * v * v * q[0] + 3 * v * v * u * q[2] + 3 * v * u * u * q[4] + u * u * u * q[6], v * v * v * q[1] + 3 * v * v * u * q[3] + 3 * v * u * u * q[5] + u * u * u * q[7]] }
    const stroke = (q, from, to, style, width) => {
      if (to <= from) return
      ctx.strokeStyle = style; ctx.lineWidth = width; ctx.lineCap = 'round'; ctx.beginPath()
      for (let i = 0; i <= 56; i++) { const [x, y] = bez(q, from + (to - from) * (i / 56)); i ? ctx.lineTo(x, y) : ctx.moveTo(x, y) }
      ctx.stroke()
    }
    const comets = (q, color, n, speed, a, reverse = false) => {
      for (let i = 0; i < n; i++) {
        const u0 = (time * speed + i / n) % 1
        for (let k = 0; k < 7; k++) {
          const u = clamp(reverse ? 1 - u0 + k * 0.012 : u0 - k * 0.012)
          const [x, y] = bez(q, u)
          ctx.fillStyle = `rgba(${color},${a * (1 - k / 7) * Math.sin(Math.PI * u0)})`
          ctx.beginPath(); ctx.arc(x, y, 3.2 - k * 0.35, 0, 6.283); ctx.fill()
        }
      }
    }

    // grand-predicate threads
    gps.forEach((gp, i) => {
      const a = clamp(gpA * 1.6 - i * 0.25)
      if (a <= 0) return
      const [gX, gY] = pos(gp), q = curve(pX, pY, gX, gY)
      stroke(q, 0, a, `rgba(${BLUE},0.5)`, 1.4)
      if (gp.tone === 'design' && gpAmber > 0) { stroke(q, 0, gpAmber, `rgba(${AMBER},0.22)`, 6); stroke(q, 0, gpAmber, `rgba(${AMBER},0.8)`, 1.8) }
    })

    // the document, born at the candidate; the thread starts at its highlighted line
    let sx = cX, sy = cY
    if (docA > 0.01) {
      const w = 76, h = 98, dx = cX - w - 34, dy = cY - h - 26
      ctx.save(); ctx.globalAlpha = docA
      ctx.shadowColor = 'rgba(0,0,0,0.5)'; ctx.shadowBlur = 24; ctx.shadowOffsetY = 8
      ctx.fillStyle = '#f6f1e5'; ctx.beginPath(); ctx.roundRect(dx, dy, w, h, 3); ctx.fill()
      ctx.shadowColor = 'transparent'
      ctx.fillStyle = '#d6cdb9'
      for (let i = 0; i < 10; i++) if (i !== 6) ctx.fillRect(dx + 9, dy + 12 + i * 7.6, w - (i % 3 === 2 ? 30 : 18), 2.4)
      const hy = dy + 12 + 6 * 7.6
      ctx.fillStyle = `rgba(91,130,240,${0.6 + 0.4 * Math.sin(time * 3)})`; ctx.fillRect(dx + 8, hy - 1, w - 15, 4.4)
      ctx.fillStyle = '#6c6656'; ctx.font = `700 9px ${SANS}`; ctx.textAlign = 'left'; ctx.textBaseline = 'alphabetic'
      ctx.fillText(`p. ${world.page}`, dx + 8, dy + h - 7)
      ctx.restore()
      const hx = dx + w - 7
      const k = smooth(1.5, 1.95, t)
      sx = lerp(hx, cX, k); sy = lerp(hy + 1, cY, k)
      ctx.strokeStyle = `rgba(${BLUE},${0.7 * docA})`; ctx.lineWidth = 1.2
      ctx.beginPath(); ctx.moveTo(hx, hy + 1); ctx.quadraticCurveTo(cX - 8, hy, cX - 7, cY - 6); ctx.stroke()
    }

    // the thread: candidate -> predicate, travelling back in time
    const main = curve(sx, sy, pX, pY)
    stroke(main, 0, threadP, `rgba(${BLUE},0.22)`, 7)
    stroke(main, 0, threadP, `rgba(${BLUE},0.95)`, 2)
    if (threadP > 0.02 && threadP < 0.985) {
      const [hx, hy] = bez(main, threadP)
      const glow = ctx.createRadialGradient(hx, hy, 0, hx, hy, 22)
      glow.addColorStop(0, `rgba(${BLUE},0.9)`); glow.addColorStop(1, `rgba(${BLUE},0)`)
      ctx.fillStyle = glow; ctx.beginPath(); ctx.arc(hx, hy, 22, 0, 6.283); ctx.fill()
      const yr = Math.round(lerp(yearOf(cand.date), yearOf(pred.date), threadP))
      chip(hx + 14, hy - 22, [{ text: `← ${yr}`, font: `600 12px ${MONO}`, color: `rgb(${BLUE})`, lh: 15, size: 12 }], { stroke: `rgba(${BLUE},0.4)` })
    }
    if (threadP >= 0.985 && flow < 0.05) comets(main, BLUE, 3, 0.32, 0.9 * (1 - mix))
    if (threadP > 0.5 && mix < 0.6) {
      const [lx, ly] = bez(main, 0.42)
      chip(lx, ly - 22, [{ text: `cites · page ${world.page}`, font: `600 11.5px ${SANS}`, color: 'rgba(236,230,216,0.9)', lh: 14, size: 11.5 }],
        { align: 'center', alpha: smooth(0.5, 0.85, threadP) * (1 - mix / 0.6) })
    }
    if (flow > 0) {
      stroke(main, 1 - flow, 1, `rgba(${AMBER},0.25)`, 9)
      stroke(main, 1 - flow, 1, `rgba(${AMBER},1)`, 2.4)
      if (flow > 0.98) comets(main, AMBER, 3, 0.28, 0.95, true)
    }

    // the recall, on the predicate's life line
    if (recallA > 0.01 && out > 0.01) {
      const a = recallA * out
      ctx.setLineDash([2, 5]); ctx.strokeStyle = `rgba(${AMBER},${0.8 * a})`; ctx.lineWidth = 1.4
      ctx.beginPath(); ctx.moveTo(pX + 12, pY); ctx.lineTo(rX - 10, rY); ctx.stroke(); ctx.setLineDash([])
      for (let i = 0; i < 2; i++) {
        const u = ((time + i * 1.3) % 2.6) / 2.6
        ctx.strokeStyle = `rgba(${AMBER},${(1 - u) * 0.6 * a})`; ctx.lineWidth = 1.2
        ctx.beginPath(); ctx.arc(rX, rY, 10 + u * 46, 0, 6.283); ctx.stroke()
      }
      const s = 10 * (0.5 + 0.5 * easeOut(recallA))
      const g = ctx.createRadialGradient(rX, rY, 0, rX, rY, 36)
      g.addColorStop(0, `rgba(${AMBER},${0.55 * a})`); g.addColorStop(1, `rgba(${AMBER},0)`)
      ctx.fillStyle = g; ctx.beginPath(); ctx.arc(rX, rY, 36, 0, 6.283); ctx.fill()
      ctx.fillStyle = `rgba(${AMBER},${a})`
      ctx.beginPath(); ctx.moveTo(rX, rY - s); ctx.lineTo(rX + s, rY); ctx.lineTo(rX, rY + s); ctx.lineTo(rX - s, rY); ctx.closePath(); ctx.fill()
      if (compact) {
        const [cls, cause, when] = recall.label.split(' · ')
        chip(Math.max(8, rX - 60), rY + s + 40, [
          { text: `${cls} recall`, font: `700 11.5px ${SANS}`, color: `rgb(${AMBER})`, lh: 14, size: 11.5 },
          { text: cause, font: `600 11px ${SANS}`, color: `rgb(${AMBER})`, lh: 14, size: 11 },
          { text: `began ${when}`, font: `500 11px ${SANS}`, color: 'rgba(236,230,216,0.8)', lh: 14, size: 11 },
        ], { alpha: a, stroke: `rgba(${AMBER},0.5)` })
      } else chip(rX, rY + s + 26, [
        { text: 'RECALL BEGINS', font: `700 10px ${SANS}`, color: 'rgba(236,230,216,0.75)', lh: 13, size: 10 },
        { text: recall.label, font: `700 12.5px ${SANS}`, color: `rgb(${AMBER})`, lh: 16, size: 12.5 },
      ], { align: 'center', alpha: a, stroke: `rgba(${AMBER},0.5)` })
    }

    // nodes and their labels
    const node = (n, alpha, amberAmt) => {
      if (alpha <= 0.01) return
      const [x, y] = pos(n), self = n.tone === 'self'
      const r = self ? 10 : 7.5
      ctx.save(); ctx.globalAlpha = alpha
      if (amberAmt > 0) {
        const g = ctx.createRadialGradient(x, y, 0, x, y, r * 4.5)
        g.addColorStop(0, `rgba(${AMBER},${0.45 * amberAmt})`); g.addColorStop(1, `rgba(${AMBER},0)`)
        ctx.fillStyle = g; ctx.beginPath(); ctx.arc(x, y, r * 4.5, 0, 6.283); ctx.fill()
      }
      if (self) {
        ctx.strokeStyle = `rgba(${BLUE},0.55)`; ctx.lineWidth = 1.2; ctx.setLineDash([3, 4]); ctx.lineDashOffset = -time * 8
        ctx.beginPath(); ctx.arc(x, y, r + 8 + Math.sin(time * 2) * 1.5, 0, 6.283); ctx.stroke(); ctx.setLineDash([])
      }
      ctx.fillStyle = self ? IVORY : amberAmt > 0.5 ? `rgb(${AMBER})` : NEUTRAL
      ctx.strokeStyle = self ? `rgb(${BLUE})` : NIGHT; ctx.lineWidth = self ? 3 : 2.2
      ctx.beginPath(); ctx.arc(x, y, r, 0, 6.283); ctx.fill(); ctx.stroke()
      ctx.restore()
      chip(x + r + 12, y, nodeLabel(n), { alpha })
    }
    gps.forEach((gp, i) => node(gp, clamp(gpA * 1.6 - i * 0.25), gp.tone === 'design' ? gpAmber : 0))
    node(pred, predA, smooth(2.5, 2.85, t))
    node(cand, 1, 0)

    // hero: which point this is
    const heroA = 1 - smooth(0.25, 0.6, t)
    if (heroA > 0.01) {
      chip(cX, cY + 52, [{ text: `one of ${deviceCount.toLocaleString('en-US')} clearances in the graph`, font: `500 11.5px ${SANS}`, color: 'rgba(236,230,216,0.8)', lh: 14, size: 11.5 }],
        { align: 'center', alpha: heroA })
    }
    // handoff: the workspace's own column headings
    if (mix > 0.4 && !compact) {
      const a = smooth(0.4, 1, mix)
      const head = (n, label) => { const [x] = pos(n); const [, y] = P(0, Math.min(...gps.map((g) => g.fy)) - 70); ctx.globalAlpha = a; ctx.font = `700 10.5px ${SANS}`; ctx.fillStyle = 'rgba(236,230,216,0.6)'; ctx.textAlign = 'center'; ctx.fillText(label, x, y); ctx.globalAlpha = 1 }
      head(gps[0], 'GRAND-PREDICATES'); head(pred, 'PREDICATE'); head(cand, 'CANDIDATE')
    }
  }

  resize()
  raf = requestAnimationFrame(frame)
  const onVis = () => {
    if (document.hidden) { cancelAnimationFrame(raf); raf = 0 }
    else if (!raf && alive) { last = 0; raf = requestAnimationFrame(frame) }   // never integrate the gap
  }
  document.addEventListener('visibilitychange', onVis)

  return {
    kind: field ? 'webgl' : 'canvas2d',
    setAnchors(a) { anchors = a.length ? a : [[0, 0]] },
    setZones(z) { zones = z; layout() },
    snap() { spring.value = mapAnchors(anchors, window.scrollY); spring.velocity = 0 },
    setPointer(x, y, on = true) { pointer = { x, y, on } },
    bloom() { bloomAt = performance.now() / 1000 },
    resize,
    dispose() { alive = false; cancelAnimationFrame(raf); document.removeEventListener('visibilitychange', onVis); field?.dispose() },
  }
}
