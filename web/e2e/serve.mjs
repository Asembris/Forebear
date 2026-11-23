// Starts the real FastAPI app on a throwaway copy of the shipped store, so end-to-end writes
// (reviews, saved assessments) never touch the committed data/forebear.rl.
import { copyFileSync, mkdirSync } from 'node:fs'
import { spawn, spawnSync } from 'node:child_process'
import { resolve } from 'node:path'

const root = resolve(import.meta.dirname, '..', '..')
const live = resolve(root, 'data', 'live')
mkdirSync(live, { recursive: true })
const db = resolve(live, 'e2e.rl')
copyFileSync(resolve(root, 'data', 'forebear.rl'), db)
const py = process.platform === 'win32' ? resolve(root, '.venv', 'Scripts', 'python.exe') : resolve(root, '.venv', 'bin', 'python')
// one genuinely outdated review (a person's review of an earlier PDF), for the provenance review-state tests
const seeded = spawnSync(py, [resolve(root, 'web', 'e2e', 'seed_outdated_review.py'), db], { cwd: root, stdio: 'inherit' })
if (seeded.status !== 0) process.exit(seeded.status ?? 1)
const port = process.env.E2E_PORT || '8767'
const child = spawn(py, ['-m', 'uvicorn', 'forebear.api:app', '--port', port], {
  cwd: root, stdio: 'inherit', env: { ...process.env, FOREBEAR_DB: db },
})
const stop = () => child.kill()
process.on('SIGINT', stop); process.on('SIGTERM', stop); process.on('exit', stop)
child.on('exit', (code) => process.exit(code ?? 0))
