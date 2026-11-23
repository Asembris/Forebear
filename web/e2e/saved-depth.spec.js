import { test, expect } from '@playwright/test'
import { startIsolatedApi } from './server.mjs'

/*
  A saved assessment keeps the query depth it was computed at, and history rechecks it at that depth.
  K251770 (the two-hop showcase) reports no design-recall signal at depth 1 and REVIEW_LINEAGE from depth 2, so a
  depth-1 assessment rechecked at the old default of 4 would be called stale on an unchanged graph.
  K113068 -> K091319 leaves a generation-3 ancestor: a change to it matters at depth 4, not at depth 1 or 2.
  K251770 -> K200480 is the direct predicate: rejecting it changes the evidence at every depth.
  e2e/seed_legacy_assessment.py adds A-e2elegacy1, saved at depth 1 before depth was stored on the node.
  Saves and reviews consume the store, so every attempt runs against its own freshly seeded API.
*/
const K = 'K251770', LEGACY = 'A-e2elegacy1'

const withStore = test.extend({
  api: async ({}, use) => {
    const api = await startIsolatedApi({ seed: 'seed_legacy_assessment.py' })
    try { await use(api.url) } finally { await api.stop() }
  },
})

async function saveFromUi(page, depth) {
  const select = page.getByLabel('Generations traversed by the query')
  if (await select.inputValue() !== String(depth)) {
    await Promise.all([
      page.waitForResponse((r) => r.url().includes(`/api/assess/${K}?depth=${depth}`)),
      select.selectOption(String(depth)),
    ])
  }
  await expect(page.getByRole('button', { name: 'Save assessment to graph' })).toBeVisible()
  await page.getByRole('button', { name: 'Save assessment to graph' }).click()
  const [req, res] = await Promise.all([
    page.waitForRequest((r) => r.url().endsWith('/api/assessments') && r.method() === 'POST'),
    page.waitForResponse((r) => r.url().endsWith('/api/assessments') && r.request().method() === 'POST'),
    page.getByRole('button', { name: 'Save to Relate' }).click(),
  ])
  expect(req.postDataJSON().depth).toBe(depth)
  const saved = await res.json()
  expect(saved.depth).toBe(depth)
  await expect(page.locator('.memo').getByRole('status')).toContainText(`Saved ${saved.id} at ${depth} gen`)
  return saved
}

const row = (page, id) => page.locator('tr', { has: page.getByText(id, { exact: true }) })

async function expectRow(page, id, depthText, state) {
  const r = row(page, id)
  await expect(r.getByTestId('saved-depth')).toHaveText(depthText)
  await expect(r.locator('td').nth(4)).toHaveText(state)
}

withStore('saved assessments keep their depth and go stale only on evidence that depth reads', async ({ page, request, api }) => {
  await page.goto(`${api}/#/check/${K}`)
  const d1 = await saveFromUi(page, 1)
  const d2 = await saveFromUi(page, 2)
  const d4 = await saveFromUi(page, 4)
  expect([d1.verdict, d2.verdict, d4.verdict]).toEqual(['NO_DESIGN_RECALL_SIGNAL', 'REVIEW_LINEAGE', 'REVIEW_LINEAGE'])

  // the investigation's own history lists each save with its depth, none stale on the unchanged graph
  await page.reload()
  for (const [s, label] of [[d1, '1 gen'], [d2, '2 gen'], [d4, '4 gen']]) {
    const hist = page.locator('.hist', { has: page.getByText(s.id, { exact: true }) })
    await expect(hist.getByTestId('saved-depth')).toHaveText(label)
  }
  await expect(page.locator('.hist .stale')).toHaveCount(0)

  await page.goto(`${api}/#/history`)
  await expectRow(page, d1.id, '1 gen', 'Current')
  await expectRow(page, d2.id, '2 gen', 'Current')
  await expectRow(page, d4.id, '4 gen', 'Current')
  await expectRow(page, LEGACY, '1 gen · legacy', 'Current')

  // a review in generation 3 is evidence for the depth-4 assessment only
  expect((await request.post(`${api}/api/citation/review`, { data: { src: 'K113068', dst: 'K091319', status: 'confirmed' } })).ok()).toBe(true)
  await page.reload()
  await expectRow(page, d4.id, '4 gen', 'Stale')
  await expectRow(page, d2.id, '2 gen', 'Current')
  await expectRow(page, d1.id, '1 gen', 'Current')
  await expectRow(page, LEGACY, '1 gen · legacy', 'Current')

  // rejecting the direct predicate changes the evidence at every depth, and the verdict where it was a signal
  expect((await request.post(`${api}/api/citation/review`, { data: { src: K, dst: 'K200480', status: 'rejected' } })).ok()).toBe(true)
  await page.reload()
  await expectRow(page, d4.id, '4 gen', /^Stale · now /)
  await expectRow(page, d2.id, '2 gen', /^Stale · now /)
  await expectRow(page, d1.id, '1 gen', /^Stale/)
  await expectRow(page, LEGACY, '1 gen · legacy', /^Stale/)
})

withStore('a depth-1 query works through the verdict, graph, generation selector and saved history', async ({ page, api }) => {
  await page.goto(`${api}/#/check/${K}`)
  const query = page.getByLabel('Generations traversed by the query')
  const shown = page.getByLabel('Generations shown')
  await expect(query.locator('option')).toHaveText(['1 gen', '2 gen', '3 gen', '4 gen', '5 gen', '6 gen'])
  await expect(page.getByTestId('depth-contrast')).toBeVisible()          // the depth-4 query finds the two-hop recall

  await Promise.all([page.waitForResponse((r) => r.url().includes(`/api/assess/${K}?depth=1`)), query.selectOption('1')])
  await expect(page.getByTestId('verdict')).toContainText('No design-recall signal')
  // only the direct predicate is queried and drawn; the shown generations cannot exceed the query
  await expect(shown.locator('option')).toHaveText(['1 gen'])
  await expect(shown).toHaveValue('1')
  const graph = page.getByTestId('evidence-graph')
  await expect(graph.locator('svg')).toHaveAttribute('aria-label', `Predicate lineage graph for ${K}: 2 devices, 1 citations`)
  await expect(graph.locator('.lk', { hasText: 'K200480' })).toHaveCount(1)
  await expect(graph.locator('.lk', { hasText: 'K131982' })).toHaveCount(0)
  await expect(graph.locator('.g-more')).toHaveCount(0)
  await expect(page.getByTestId('depth-contrast')).toHaveCount(0)        // nothing deeper to contrast with
  await page.getByRole('button', { name: 'Timeline', exact: true }).click()
  await expect(page.getByText('K131982', { exact: true })).toHaveCount(0)
  await page.getByRole('button', { name: 'Graph', exact: true }).click()

  const saved = await saveFromUi(page, 1)
  expect([saved.depth, saved.verdict]).toEqual([1, 'NO_DESIGN_RECALL_SIGNAL'])
  const hist = page.locator('.hist', { has: page.getByText(saved.id, { exact: true }) })
  await expect(hist.getByTestId('saved-depth')).toHaveText('1 gen')
  await expect(hist).toContainText('No design-recall signal')
  await expect(hist.locator('.stale')).toHaveCount(0)

  // back to a deeper query: the verdict and generation choices follow, the depth-1 save stays current
  await Promise.all([page.waitForResponse((r) => r.url().includes(`/api/assess/${K}?depth=2`)), query.selectOption('2')])
  await expect(page.getByTestId('verdict')).toContainText('Review lineage')
  await expect(shown.locator('option')).toHaveText(['1 gen', '2 gen'])
  await expect(shown).toHaveValue('2')
  await expect(graph.locator('.lk', { hasText: 'K131982' })).toHaveCount(1)
  await page.goto(`${api}/#/history`)
  await expectRow(page, saved.id, '1 gen', 'Current')
})
