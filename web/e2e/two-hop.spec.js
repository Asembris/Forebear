import { test, expect } from '@playwright/test'
import facts from '../src/story/two-hop.json' with { type: 'json' }
import { depthContrast, excerpt } from '../src/workspace/depth.js'

/*
  The two-hop showcase: K251770's direct predicate has no recall on file, so a one-generation query reports no
  design-recall signal; one more hop reaches two REMstar clearances on Class I design recall Z-1974-2021.
  Values come from src/story/two-hop.json, which tests/test_two_hop_story.py checks against the shipped store.
*/
const c = facts.candidate, p = facts.predicate, r = facts.recall

test.describe('two-hop discovery', () => {
  test('landing to the depth-1 vs depth-2 contrast in under 15 seconds', async ({ page }) => {
    const t0 = Date.now()
    await page.goto('/')
    await page.keyboard.press('Escape')                       // the opening film is skippable
    await page.getByTestId('hero-two-hop').click()
    await expect(page).toHaveURL(new RegExp(`#/check/${c.k}$`))
    const panel = page.getByTestId('depth-contrast')
    await expect(panel).toBeVisible()
    await expect(panel.getByTestId('depth-1')).toContainText('No design-recall signal · provisional')
    await expect(panel.getByTestId('depth-2')).toContainText('Review lineage')
    await expect(panel.getByTestId('depth-2')).toContainText(`${r.classification} · ${r.root_cause}`)
    expect(Date.now() - t0).toBeLessThan(15_000)
    await page.screenshot({ path: `test-results/shots/${test.info().project.name}-two-hop.png` })
  })

  test('every claim links to the original FDA evidence', async ({ page }) => {
    await page.goto(`/#/check/${c.k}`)
    const panel = page.getByTestId('depth-contrast')
    await expect(panel).toBeVisible()
    await expect(panel.getByTestId('depth-1')).toContainText(`no recall for ${p.k}`)
    for (const h of facts.hops) {
      const src = h.src === c.k ? c : p
      await expect(panel.locator(`a[href="${src.summary_url}#page=${h.page}"]`).first()).toBeVisible()
      await expect(panel.locator('.dc-route')).toContainText(`${h.src} → ${h.dst}`)
    }
    const rec = panel.locator(`a[href="${r.url}"]`)
    await expect(rec).toHaveCount(2)                          // in the depth-2 sentence and on the recall step
    await expect(panel.locator('.dc-route .is-recall')).toContainText(`not ${p.k}`)

    // the provenance drawer opens on the second hop with its page-anchored PDF link
    await panel.locator('.dc-route li').filter({ hasText: `${p.k} → ${facts.hops[2].dst}` }).getByRole('button', { name: 'Provenance' }).click()
    const drawer = page.getByTestId('provenance')
    await expect(drawer).toBeVisible()
    await expect(drawer.getByTestId('pdf-page-link')).toHaveAttribute('href', `${p.summary_url}#page=${facts.hops[2].page}`)
  })

  test('a case whose direct predicate already carries the recall shows no contrast', async ({ page }) => {
    const shallow = []
    page.on('request', (req) => { if (/\/api\/assess\/K252078\?depth=[12]$/.test(req.url())) shallow.push(req.url()) })
    await page.goto('/#/check/K252078')
    await expect(page.getByTestId('verdict')).toContainText('Review lineage')
    await page.waitForTimeout(500)
    await expect(page.getByTestId('depth-contrast')).toHaveCount(0)
    expect(shallow).toEqual([])                               // depth 1 already finds this signal: no extra queries
  })

  test('rejecting one REMstar path refreshes the contrast to the remaining supported path', async ({ page }) => {
    const [kept, dropped] = facts.recall.holders.includes('K130077') ? ['K130077', 'K131982'] : facts.recall.holders
    await page.goto(`/#/check/${c.k}`)
    const panel = page.getByTestId('depth-contrast')
    const route = panel.locator('.dc-route')
    await expect(route).toContainText(`${p.k} → ${dropped}`)
    await expect(panel.getByTestId('depth-2')).toContainText(`${p.k} itself cites ${kept} and ${dropped}`)
    try {
      await route.locator('li').filter({ hasText: `${p.k} → ${dropped}` }).getByRole('button', { name: 'Provenance' }).click()
      const drawer = page.getByTestId('provenance')
      await drawer.getByRole('button', { name: 'Reject citation' }).click()
      await expect(drawer.getByRole('status')).toContainText('Recorded: rejected')
      // no reload: the panel re-queries both depths from the updated graph
      await expect(panel.getByTestId('depth-2')).toContainText(`${p.k} itself cites ${kept}.`)
      await expect(panel.getByTestId('depth-2')).toContainText(`FDA lists it on ${r.id}`)
      await expect(panel.getByTestId('depth-2')).toContainText('Review lineage')
      await expect(panel.getByTestId('depth-1')).toContainText('No design-recall signal · provisional')
      await expect(route.locator('.dc-n')).toHaveText([`${c.k} → ${p.k}`, `${p.k} → ${kept}`, r.id])
      await expect(route.locator('.is-recall')).toContainText(`FDA's record lists ${kept}, not ${p.k}`)
    } finally {
      const res = await page.request.post('/api/citation/review', { data: { src: p.k, dst: dropped, status: '' } })
      expect(res.ok()).toBeTruthy()
    }
  })

  test('the workspace home offers the case', async ({ page }) => {
    await page.goto('/#/check')
    await page.getByRole('button', { name: new RegExp(c.k) }).click()
    await expect(page.getByTestId('depth-contrast')).toBeVisible()
  })
})

test.describe('two-hop pure rules', () => {
  const sig = (chain, rec) => ({ code: 'ANCESTOR_RECALL', severity: 'medium', conditional: false, chain, gen: chain.length - 1,
    evidence: [{ type: 'recall', ...rec }] })
  const rec = { id: 'Z-1', classification: 'Class I', root_cause: 'Device Design', design_related: true, initiated: '2021-01-01' }
  const deep = {
    k: 'K3', depth: 2, verdict: 'REVIEW_LINEAGE', device: { decision_date: '2025-01-01' },
    signals: [sig(['K3', 'K2', 'K1'], rec)],
    ancestors: [{ k: 'K2', gen: 1, recalls: [], hops: [{ src: 'K3', dst: 'K2', page: 5 }] },
      { k: 'K1', gen: 2, recalls: [rec], hops: [{ src: 'K3', dst: 'K2' }, { src: 'K2', dst: 'K1', page: 4 }] }],
  }
  const shallow = { k: 'K3', depth: 1, verdict: 'NO_DESIGN_RECALL_SIGNAL', signals: [] }

  test('depth matters only when the verdict changes through a deeper route', () => {
    const x = depthContrast(shallow, deep)
    expect(x.recall.id).toBe('Z-1')
    expect(x.fanout.map((f) => f.device.k)).toEqual(['K1'])
    expect(x.predicateOnRecall).toBe(false)
    expect(x.timing.relation).toBe('before')
    expect(depthContrast({ ...shallow, verdict: 'REVIEW_LINEAGE' }, deep)).toBeNull()
    expect(depthContrast(shallow, { ...deep, signals: [...deep.signals, sig(['K3', 'K2'], rec)] })).toBeNull()
    expect(depthContrast({ ...shallow, depth: 2 }, deep)).toBeNull()
  })

  test('excerpts centre on the cited K-number', () => {
    const x = excerpt('Classification BZD Predicate Device: Philips DreamStation 2 - K200480 Common/Usual Name: CPAP and much more text', 'K200480')
    expect(x.k).toBe('K200480')
    expect(x.head).toContain('Predicate Device: Philips DreamStation 2 - ')
    expect(excerpt('no number here', 'K1').k).toBe('')
  })
})

test.describe('two-hop responsive @responsive', () => {
  test('the contrast fits the viewport', async ({ page }) => {
    await page.goto(`/#/check/${c.k}`)
    const panel = page.getByTestId('depth-contrast')
    await expect(panel).toBeVisible()
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)
    expect(overflow).toBeLessThanOrEqual(1)
    await panel.scrollIntoViewIfNeeded()
    await page.screenshot({ path: `test-results/shots/${test.info().project.name}-two-hop-panel.png` })
  })
})
