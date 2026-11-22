/*
  The evidence field, on the GPU. One WebGL2 context draws, in order:
    nebula   a full-screen pass: slow-moving light, an amber bloom where a recall is, film grain, vignette
    links    the network: each clearance-point joined to its nearest neighbours
    points   the store's clearances (bright) and a fine dust (dim), drifting through a flow field
    signals  sparks travelling along the links, so the network visibly carries information
  Every motion is a pure function of uniforms (time, camera, pointer, shock), so the CPU uploads
  nothing per frame. Illustrative: the bright-point count is the store's device count; positions mean nothing.
*/
import { rng } from './motion.js'

const COMMON = `#version 300 es
precision highp float;
uniform float uT;
uniform vec3 uCam;      // world centre x, y, zoom
uniform vec2 uScr;      // where the world centre sits on screen (px)
uniform vec2 uRes;      // viewport (css px)
uniform float uDpr;
uniform float uField;   // overall field visibility
uniform vec3 uPtr;      // pointer x, y (px), lamp 0..1
uniform vec4 uShock;    // shock centre x, y (px), radius (px), strength
uniform float uBloom;   // 0..1 opening bloom from uOrigin
uniform vec2 uOrigin;
uniform float uAmber;   // amber wash 0..1 (the discovery)

vec2 flow(vec2 b, float z, float ph) {
  vec2 q = b * 0.0024;
  vec2 f = vec2(sin(q.y * 1.7 + uT * 0.16 + ph) + 0.55 * sin(q.x * 3.1 - uT * 0.11 + ph * 2.0),
                cos(q.x * 1.9 + uT * 0.13 + ph * 1.3) + 0.55 * cos(q.y * 2.7 + uT * 0.17));
  return b + f * (28.0 + 34.0 * z);
}
vec2 toScreen(vec2 p, float z) {
  float par = 0.5 + 0.5 * z;
  return (p - uCam.xy * par) * uCam.z * par + uScr;
}
vec2 bloomed(vec2 s, float ph) {
  float b = clamp((uBloom - fract(ph * 7.13) * 0.45) / 0.55, 0.0, 1.0);
  b = 1.0 - pow(1.0 - b, 3.0);
  return mix(uOrigin, s, b);
}
float lampAt(vec2 s) { return uPtr.z * clamp(1.0 - length(s - uPtr.xy) / 200.0, 0.0, 1.0); }
float ringAt(vec2 s) {
  float d = length(s - uShock.xy);
  return uShock.w * exp(-pow((d - uShock.z) / 46.0, 2.0));
}
vec4 clip(vec2 s) { vec2 c = s / uRes * 2.0 - 1.0; return vec4(c.x, -c.y, 0.0, 1.0); }
const vec3 IVORY = vec3(0.93, 0.90, 0.85);
const vec3 BLUE = vec3(0.50, 0.64, 1.0);
const vec3 AMBER = vec3(0.91, 0.66, 0.28);
`

const POINT_VS = COMMON + `
in vec2 aPos; in float aZ; in float aPh; in float aKind;
out vec4 vCol;
void main() {
  vec2 s = bloomed(toScreen(flow(aPos, aZ, aPh), aZ), aPh);
  float lamp = lampAt(s);
  float ring = ringAt(s);
  vec2 away = s - uShock.xy;
  s += (length(away) > 0.5 ? normalize(away) : vec2(0.0)) * ring * 16.0;
  float tw = 0.62 + 0.38 * sin(uT * (0.7 + fract(aPh) * 0.9) + aPh * 9.0);
  bool dev = aKind > 0.5;
  float base = dev ? (0.30 + 0.50 * aZ) : (0.07 + 0.18 * aZ);
  float a = base * tw * uField * (1.0 + lamp * 2.6) + ring * (dev ? 0.9 : 0.45);
  vec3 c = mix(IVORY, BLUE, clamp(lamp * 1.3 + (dev ? 0.0 : 0.45), 0.0, 1.0));
  c = mix(c, AMBER, clamp(ring * 1.6, 0.0, 1.0));
  vCol = vec4(c * a, a);
  gl_PointSize = (dev ? (1.7 + 2.8 * aZ) : (0.9 + 1.4 * aZ)) * (1.0 + lamp * 1.3 + ring * 1.2) * uDpr;
  gl_Position = clip(s);
}`
const POINT_FS = `#version 300 es
precision mediump float;
in vec4 vCol; out vec4 o;
void main() { float d = length(gl_PointCoord - 0.5); o = vCol * smoothstep(0.5, 0.0, d); }`

const LINE_VS = COMMON + `
in vec2 aPos; in float aZ; in float aPh;
out vec4 vCol;
void main() {
  vec2 s = bloomed(toScreen(flow(aPos, aZ, aPh), aZ), aPh);
  float lamp = lampAt(s), ring = ringAt(s);
  float a = (0.075 + 0.05 * aZ) * uField * (1.0 + lamp * 6.0) + ring * 0.25;
  vec3 c = mix(BLUE, AMBER, clamp(ring * 1.6, 0.0, 1.0));
  vCol = vec4(c * a, a);
  gl_Position = clip(s);
}`
const FLAT_FS = `#version 300 es
precision mediump float;
in vec4 vCol; out vec4 o;
void main() { o = vCol; }`

const SIGNAL_VS = COMMON + `
in vec2 aA; in float aZa; in float aPa; in vec2 aB; in float aZb; in float aPb; in vec2 aSO;
out vec4 vCol;
void main() {
  float u = fract(uT * aSO.x + aSO.y);
  vec2 sa = bloomed(toScreen(flow(aA, aZa, aPa), aZa), aPa);
  vec2 sb = bloomed(toScreen(flow(aB, aZb, aPb), aZb), aPb);
  vec2 s = mix(sa, sb, u);
  float lamp = lampAt(s), ring = ringAt(s);
  float a = sin(3.14159 * u) * (0.55 + 0.45 * aZa) * uField * (1.0 + lamp * 2.0) + ring * 0.8;
  vec3 c = mix(BLUE, AMBER, clamp(ring * 1.8 + uAmber * 0.35, 0.0, 1.0));
  vCol = vec4(c * a, a);
  gl_PointSize = (2.4 + 2.2 * aZa) * (1.0 + ring) * uDpr;
  gl_Position = clip(s);
}`

const NEBULA_VS = `#version 300 es
const vec2 P[3] = vec2[3](vec2(-1.0, -1.0), vec2(3.0, -1.0), vec2(-1.0, 3.0));
void main() { gl_Position = vec4(P[gl_VertexID], 0.0, 1.0); }`
const NEBULA_FS = `#version 300 es
precision highp float;
uniform vec2 uRes; uniform float uT; uniform float uAmber; uniform vec2 uAmberPos; uniform float uField;
out vec4 o;
float hash(vec2 p) { return fract(sin(dot(p, vec2(127.1, 311.7))) * 43758.5453); }
float blob(vec2 uv, vec2 c, float r) { vec2 d = (uv - c) * vec2(uRes.x / uRes.y, 1.0); return exp(-dot(d, d) / (r * r)); }
void main() {
  vec2 uv = gl_FragCoord.xy / uRes; uv.y = 1.0 - uv.y;
  vec3 col = vec3(0.027, 0.045, 0.088);
  col += vec3(0.08, 0.14, 0.30) * blob(uv, vec2(0.72 + 0.09 * sin(uT * 0.05), 0.26 + 0.07 * cos(uT * 0.07)), 0.55) * (0.7 + 0.3 * uField);
  col += vec3(0.09, 0.06, 0.19) * blob(uv, vec2(0.18 + 0.08 * cos(uT * 0.04), 0.82 + 0.06 * sin(uT * 0.06)), 0.5);
  col += vec3(0.03, 0.07, 0.12) * blob(uv, vec2(0.45 + 0.2 * sin(uT * 0.03 + 1.0), 0.55), 0.7);
  vec2 ap = uAmberPos / uRes;
  col += vec3(0.30, 0.17, 0.04) * blob(uv, ap, 0.28) * uAmber;
  float v = smoothstep(1.25, 0.35, length((uv - 0.5) * vec2(1.1, 1.0)));
  col *= 0.55 + 0.45 * v;
  col += (hash(gl_FragCoord.xy + floor(uT * 24.0)) - 0.5) * 0.022;
  o = vec4(col, 1.0);
}`

function compile(gl, type, src) {
  const s = gl.createShader(type)
  gl.shaderSource(s, src); gl.compileShader(s)
  if (!gl.getShaderParameter(s, gl.COMPILE_STATUS)) throw new Error(gl.getShaderInfoLog(s))
  return s
}
function program(gl, vs, fs) {
  const p = gl.createProgram()
  gl.attachShader(p, compile(gl, gl.VERTEX_SHADER, vs)); gl.attachShader(p, compile(gl, gl.FRAGMENT_SHADER, fs))
  gl.linkProgram(p)
  if (!gl.getProgramParameter(p, gl.LINK_STATUS)) throw new Error(gl.getProgramInfoLog(p))
  return p
}

/* Software WebGL would drag input down with it: decide before building anything. */
export function capableGL(force = false) {
  try {
    const c = document.createElement('canvas')
    const gl = c.getContext('webgl2', { failIfMajorPerformanceCaveat: !force })
    if (!gl) return false
    const info = gl.getExtension('WEBGL_debug_renderer_info')
    const name = info ? String(gl.getParameter(info.UNMASKED_RENDERER_WEBGL)) : ''
    gl.getExtension('WEBGL_lose_context')?.loseContext()
    return force || !/swiftshader|llvmpipe|softpipe|software|basic render/i.test(name)
  } catch { return false }
}

export function createField(canvas, { devices = 1187, compact = false, onLost }) {
  const gl = canvas.getContext('webgl2', { antialias: false, alpha: false, premultipliedAlpha: true, powerPreference: 'high-performance' })
  if (!gl) throw new Error('no webgl2')
  const r = rng(1187)
  const nDust = compact ? 1500 : 4600
  const nDev = compact ? Math.min(devices, 700) : devices
  // points: x, y, z, phase, kind
  const pts = new Float32Array((nDev + nDust) * 5)
  const dev = []
  for (let i = 0; i < nDev + nDust; i++) {
    const kind = i < nDev ? 1 : 0
    const x = -1500 + r() * 4300, y = -1300 + r() * 2900, z = 0.3 + r() * 0.7, ph = r() * 6.2831
    pts.set([x, y, z, ph, kind], i * 5)
    if (kind) dev.push([x, y, z, ph])
  }
  // links between nearby clearance-points (grid lookup, two nearest each)
  const cell = 170, grid = new Map()
  dev.forEach((p, i) => { const k = `${Math.floor(p[0] / cell)},${Math.floor(p[1] / cell)}`; (grid.get(k) || grid.set(k, []).get(k)).push(i) })
  const pairs = []
  dev.forEach((p, i) => {
    const gx = Math.floor(p[0] / cell), gy = Math.floor(p[1] / cell), near = []
    for (let a = -1; a <= 1; a++) for (let b = -1; b <= 1; b++) for (const j of grid.get(`${gx + a},${gy + b}`) || []) {
      if (j <= i) continue
      const q = dev[j], d = (p[0] - q[0]) ** 2 + (p[1] - q[1]) ** 2
      if (d < 190 * 190 && Math.abs(p[2] - q[2]) < 0.3) near.push([d, j])
    }
    near.sort((u, v) => u[0] - v[0]).slice(0, 2).forEach(([, j]) => pairs.push([i, j]))
  })
  const lines = new Float32Array(pairs.length * 2 * 4)
  pairs.forEach(([i, j], n) => { lines.set(dev[i], n * 8); lines.set(dev[j], n * 8 + 4) })
  const nSig = Math.min(pairs.length, compact ? 260 : 900)
  const sig = new Float32Array(nSig * 10)
  for (let n = 0; n < nSig; n++) {
    const [i, j] = pairs[Math.floor(r() * pairs.length)]
    const [a, b] = r() < 0.5 ? [dev[i], dev[j]] : [dev[j], dev[i]]
    sig.set([a[0], a[1], a[2], a[3], b[0], b[1], b[2], b[3], 0.08 + r() * 0.22, r()], n * 10)
  }

  const progs = {
    nebula: program(gl, NEBULA_VS, NEBULA_FS),
    points: program(gl, POINT_VS, POINT_FS),
    lines: program(gl, LINE_VS, FLAT_FS),
    signals: program(gl, SIGNAL_VS, POINT_FS),
  }
  const vao = (prog, data, layout, stride) => {
    const v = gl.createVertexArray(); gl.bindVertexArray(v)
    const b = gl.createBuffer(); gl.bindBuffer(gl.ARRAY_BUFFER, b); gl.bufferData(gl.ARRAY_BUFFER, data, gl.STATIC_DRAW)
    let off = 0
    for (const [name, size] of layout) {
      const loc = gl.getAttribLocation(prog, name)
      if (loc >= 0) { gl.enableVertexAttribArray(loc); gl.vertexAttribPointer(loc, size, gl.FLOAT, false, stride * 4, off * 4) }
      off += size
    }
    gl.bindVertexArray(null)
    return { v, b }
  }
  const vPts = vao(progs.points, pts, [['aPos', 2], ['aZ', 1], ['aPh', 1], ['aKind', 1]], 5)
  const vLines = vao(progs.lines, lines, [['aPos', 2], ['aZ', 1], ['aPh', 1]], 4)
  const vSig = vao(progs.signals, sig, [['aA', 2], ['aZa', 1], ['aPa', 1], ['aB', 2], ['aZb', 1], ['aPb', 1], ['aSO', 2]], 10)
  const uni = {}
  for (const [k, p] of Object.entries(progs)) {
    uni[k] = {}
    const n = gl.getProgramParameter(p, gl.ACTIVE_UNIFORMS)
    for (let i = 0; i < n; i++) { const name = gl.getActiveUniform(p, i).name; uni[k][name] = gl.getUniformLocation(p, name) }
  }
  let lost = false
  const onLose = (e) => { e.preventDefault(); lost = true; onLost && onLost() }
  canvas.addEventListener('webglcontextlost', onLose)
  let W = 1, H = 1, dpr = 1
  // nothing compiles or uploads on first use: draw one frame now
  return {
    resize(w, h, d) {
      W = w; H = h; dpr = d
      canvas.width = Math.round(w * d); canvas.height = Math.round(h * d)
    },
    render(s) {
      if (lost) return
      gl.viewport(0, 0, canvas.width, canvas.height)
      gl.disable(gl.BLEND)
      const set = (k) => {
        const u = uni[k]
        gl.useProgram(progs[k])
        u.uT && gl.uniform1f(u.uT, s.time)
        u.uRes && gl.uniform2f(u.uRes, k === 'nebula' ? canvas.width : W, k === 'nebula' ? canvas.height : H)
        u.uField && gl.uniform1f(u.uField, s.field)
        u.uAmber && gl.uniform1f(u.uAmber, s.amber)
        if (k === 'nebula') { u.uAmberPos && gl.uniform2f(u.uAmberPos, s.amberPos[0] * dpr, s.amberPos[1] * dpr); return }
        gl.uniform3f(u.uCam, s.cx, s.cy, s.zoom)
        gl.uniform2f(u.uScr, s.sx, s.sy)
        gl.uniform1f(u.uDpr, dpr)
        gl.uniform3f(u.uPtr, s.ptr[0], s.ptr[1], s.lamp)
        gl.uniform4f(u.uShock, s.shock[0], s.shock[1], s.shock[2], s.shock[3])
        gl.uniform1f(u.uBloom, s.bloom)
        gl.uniform2f(u.uOrigin, s.origin[0], s.origin[1])
      }
      set('nebula'); gl.drawArrays(gl.TRIANGLES, 0, 3)
      gl.enable(gl.BLEND); gl.blendFunc(gl.ONE, gl.ONE)
      set('lines'); gl.bindVertexArray(vLines.v); gl.drawArrays(gl.LINES, 0, pairs.length * 2)
      set('points'); gl.bindVertexArray(vPts.v); gl.drawArrays(gl.POINTS, 0, nDev + nDust)
      set('signals'); gl.bindVertexArray(vSig.v); gl.drawArrays(gl.POINTS, 0, nSig)
      gl.bindVertexArray(null)
    },
    dispose() {
      canvas.removeEventListener('webglcontextlost', onLose)
      for (const x of [vPts, vLines, vSig]) { gl.deleteBuffer(x.b); gl.deleteVertexArray(x.v) }
      Object.values(progs).forEach((p) => gl.deleteProgram(p))
      gl.getExtension('WEBGL_lose_context')?.loseContext()
    },
  }
}
