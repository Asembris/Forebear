// The shared API for the browser suite (playwright.config.js webServer), on a throwaway copy of the shipped store.
import { freshStore, spawnApi } from './server.mjs'

const child = spawnApi(freshStore('e2e.rl'), process.env.E2E_PORT || '8767')
const stop = () => child.kill()
process.on('SIGINT', stop); process.on('SIGTERM', stop); process.on('exit', stop)
child.on('exit', (code) => process.exit(code ?? 0))
