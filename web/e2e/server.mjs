// Starting the real FastAPI app for the browser suite, always on a throwaway copy of the shipped store, so
// end-to-end writes (reviews, saved assessments) never touch the committed data/forebear.rl.
import { copyFileSync, mkdirSync, rmSync } from 'node:fs'
import { spawn, spawnSync } from 'node:child_process'
import { once } from 'node:events'
import { createServer } from 'node:net'
import { resolve } from 'node:path'

export const root = resolve(import.meta.dirname, '..', '..')
const live = resolve(root, 'data', 'live')
const py = process.platform === 'win32' ? resolve(root, '.venv', 'Scripts', 'python.exe') : resolve(root, '.venv', 'bin', 'python')

/** Copy the shipped store to data/live/<name> (gitignored) and return its path. */
export function freshStore(name) {
  mkdirSync(live, { recursive: true })
  const db = resolve(live, name)
  copyFileSync(resolve(root, 'data', 'forebear.rl'), db)
  return db
}

/** Run the API on `db`. The API is the store's only writer, so a store is seeded before this, never during. */
export function spawnApi(db, port, extra = []) {
  return spawn(py, ['-m', 'uvicorn', 'forebear.api:app', '--port', String(port), ...extra], {
    cwd: root, stdio: 'inherit', env: { ...process.env, FOREBEAR_DB: db },
  })
}

async function freePort() {
  const s = createServer().listen(0, '127.0.0.1')
  await once(s, 'listening')
  const { port } = s.address()
  s.close()
  await once(s, 'close')
  return port
}

/** A private API on a fresh copy of the store, for a test whose starting state its own steps consume.
    `seed` names a script in this folder that prepares the copy before the API opens it. */
export async function startIsolatedApi({ seed } = {}) {
  const db = freshStore(`e2e-isolated-${process.pid}-${Date.now()}.rl`)
  const stop = async (child) => {
    if (child && child.exitCode === null) { child.kill(); await once(child, 'exit') }
    rmSync(db, { force: true })
  }
  if (seed) {
    const r = spawnSync(py, [resolve(import.meta.dirname, seed), db], { cwd: root, stdio: 'inherit' })
    if (r.status !== 0) { await stop(null); throw new Error(`seed ${seed} failed with status ${r.status}`) }
  }
  const port = await freePort()
  const child = spawnApi(db, port, ['--log-level', 'warning'])
  const url = `http://127.0.0.1:${port}`
  for (let i = 0; i < 200; i++) {
    if (child.exitCode !== null) break
    try { if ((await fetch(`${url}/api/health`)).ok) return { url, stop: () => stop(child) } } catch { /* not up yet */ }
    await new Promise((r) => setTimeout(r, 100))
  }
  await stop(child)
  throw new Error(`isolated API on ${url} did not become healthy`)
}
