/* Pure motion primitives: no DOM, clock or renderer state, so all of it is reversible and testable. */
export const clamp = (v, lo = 0, hi = 1) => Math.max(lo, Math.min(hi, v))
export const lerp = (a, b, t) => a + (b - a) * t

export function smooth(a, b, v) {
  const t = clamp((v - a) / (b - a))
  return t * t * (3 - 2 * t)
}
export const easeOut = (t) => 1 - Math.pow(1 - clamp(t), 3)

/* Exact closed-form critically damped spring: velocity stays continuous when the target jumps
   (a wheel notch), and the step is identical at any refresh rate. */
export function stepSpring(s, target, omega, dt) {
  const off = s.value - target
  const slope = s.velocity + omega * off
  const decay = Math.exp(-omega * dt)
  s.value = target + (off + slope * dt) * decay
  s.velocity = (slope - omega * (off + slope * dt)) * decay
}

/* Monotonic piecewise-linear map from measured document offsets to scene time. */
export function mapAnchors(anchors, y) {
  if (!anchors.length) return 0
  if (y <= anchors[0][0]) return anchors[0][1]
  for (let i = 1; i < anchors.length; i++) {
    const [ay, v] = anchors[i]
    if (y <= ay) {
      const [py, pv] = anchors[i - 1]
      return lerp(pv, v, ay === py ? 1 : (y - py) / (ay - py))
    }
  }
  return anchors[anchors.length - 1][1]
}

/* Keyframed value at scene time t: [[t, value], ...] with smoothstep between keys. */
export function keyed(keys, t) {
  if (t <= keys[0][0]) return keys[0][1]
  for (let i = 1; i < keys.length; i++) {
    if (t <= keys[i][0]) {
      const [t0, v0] = keys[i - 1], [t1, v1] = keys[i]
      return lerp(v0, v1, smooth(t0, t1, t))
    }
  }
  return keys[keys.length - 1][1]
}

/* Deterministic PRNG so the field looks the same on every visit. */
export function rng(seed = 7) {
  let s = seed >>> 0
  return () => {
    s = (s + 0x6d2b79f5) >>> 0
    let t = s
    t = Math.imul(t ^ (t >>> 15), t | 1)
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61)
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296
  }
}
