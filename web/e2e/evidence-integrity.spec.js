import { test, expect } from '@playwright/test'

// Regression tests for the evidence-integrity fixes. The real store covers compare coverage, supported/conditional
// reach and the watchlist; synthetic API responses cover the mixed-confidence and date-boundary cases the shipped
// data does not contain.

test.describe('compare keeps evidence coverage', () => {
  test('K012323 (partial) and K014074 (complete) no longer look the same', async ({ page }) => {
    await page.goto('/#/compare/K012323 K014074')
    const partial = page.locator('tr[data-k="K012323"]')
    const complete = page.locator('tr[data-k="K014074"]')
    await expect(partial).toHaveAttribute('data-evidence', 'partial')
    await expect(complete).toHaveAttribute('data-evidence', 'complete')
    await expect(partial.getByTestId('compare-verdict')).toHaveText('No design-recall signal · provisional')
    await expect(partial.getByTestId('compare-verdict')).not.toHaveClass(/tone-calm/)
    await expect(partial.getByTestId('compare-reason')).toContainText('Provisional:')
    await expect(partial).toContainText('design-related recalls in the product code name no 510(k)')
    await expect(complete.getByTestId('compare-verdict')).toHaveText('No design-recall signal')
    await expect(complete.getByTestId('compare-verdict')).toHaveClass(/tone-calm/)
    await expect(complete.getByTestId('compare-reason')).not.toContainText('Provisional')
  })

  test('the investigation header shows the provisional state and its reason', async ({ page }) => {
    await page.goto('/#/check/K012323')
    await expect(page.getByTestId('verdict')).toContainText('provisional')
    await expect(page.getByTestId('evidence-reason').first()).toBeVisible()
  })
})

test.describe('recall reach timing', () => {
  test('supported after-recall rows are separate from conditional and before rows', async ({ page }) => {
    await page.goto('/#/reach/88058,88071')
    await expect(page.getByTestId('reach-count-after')).toContainText('8')
    await expect(page.getByTestId('reach-count-conditional')).toContainText('4')
    const after = page.getByTestId('reach-after-supported').locator('tbody tr')
    await expect(after).toHaveCount(8)
    for (const row of await after.all()) {
      await expect(row).toHaveAttribute('data-timing', 'after')
      await expect(row).toHaveAttribute('data-evidence', 'supported')
    }
    const before = page.getByTestId('reach-before').locator('tbody tr')
    for (const row of await before.all()) await expect(row).toHaveAttribute('data-timing', 'before')
    await expect(page.getByTestId('reach-before').locator('tr[data-k="K183226"]')).toHaveClass(/is-conditional/)
    await expect(page.getByTestId('reach-stats')).toContainText('FDA lists')
  })

  test('mixed-confidence routes and date boundaries are never misfiled', async ({ page }) => {
    const d = (k, decided, timing, evidence, extra = {}) => ({
      k, name: `Device ${k}`, applicant: 'Acme', decision_date: decided, gen: 1, supported_gen: evidence === 'supported' ? 1 : null,
      via: ['K100001'], supported_via: evidence === 'supported' ? ['K100001'] : [], conditional_via: evidence === 'supported' ? [] : ['K100001'],
      evidence, recall_started: '2020-01-01', timing, after_recall: timing === 'after', conditional_recall_started: null, conditional_timing: null, ...extra,
    })
    const body = {
      event: '1', initiated: '2010-01-01',
      recalled: [{ k: 'K100001', name: 'A', decision_date: '2005-01-01', initiated: '2020-01-01', records: 1, attribution: 'name_token_absent', linked_before_clearance: false },
        { k: 'K100002', name: 'B', decision_date: '2012-01-01', initiated: '2010-01-01', records: 1, attribution: 'name_token_match', linked_before_clearance: true }],
      counts: { after_supported: 1, after_conditional: 1, before: 1, same_day: 1, unknown: 1, conditional: 1, mixed: 1 },
      descendants: [
        d('K200001', '2021-01-01', 'after', 'supported'),
        d('K200002', '2021-01-01', 'after', 'conditional'),
        d('K200003', '2020-01-01', 'same_day', 'supported'),
        d('K200004', null, 'unknown', 'supported'),
        d('K200005', '2015-01-01', 'before', 'supported', {
          via: ['K100001', 'K100002'], conditional_via: ['K100002'], conditional_recall_started: '2010-01-01', conditional_timing: 'after' }),
      ],
    }
    await page.route('**/api/recall-event/**', (r) => r.fulfill({ json: body }))
    await page.goto('/#/reach/1')
    const section = (id) => page.getByTestId(`reach-${id}`)
    await expect(section('after-supported').locator('tbody tr')).toHaveCount(1)
    await expect(section('after-conditional').locator('tr[data-k="K200002"]')).toHaveClass(/is-conditional/)
    await expect(section('same-day').locator('tr[data-k="K200003"]')).toContainText('order unknown')
    await expect(section('unknown').locator('tr[data-k="K200004"]')).toContainText('a date is missing')
    const mixed = section('before').locator('tr[data-k="K200005"]')
    await expect(section('before').locator('tbody tr')).toHaveCount(1)
    await expect(mixed).toContainText('mixed routes')
    await expect(mixed).toContainText('Conditional route only')
    await expect(page.getByTestId('reach-count-undetermined')).toContainText('1 same day, 1 missing a date')
    const holders = page.getByTestId('reach-holder')
    await expect(holders.nth(0)).toContainText('name not found (heuristic)')
    await expect(holders.nth(1)).toContainText('name match (heuristic)')
    await expect(holders.nth(1)).toContainText('recall began before this clearance')
    await expect(holders.nth(1)).toHaveAttribute('title', /does not verify that the recall names this exact model/)
    await expect(holders.nth(1)).toHaveAttribute('title', /dates alone do not establish whether this cleared model was affected/)
    await expect(page.getByTestId('reach-stats')).toContainText('not verified model identity')
  })
})

test.describe('watchlist wording', () => {
  test('compares clearance dates, not citation timing', async ({ page }) => {
    await page.goto('/#/watch')
    const head = page.locator('.page-head')
    await expect(head).toContainText('cleared after a predicate recall began')
    await expect(head).toContainText('receipt')
    await expect(page.locator('body')).not.toContainText(/cited after/i)
    await expect(page.locator('thead')).not.toContainText('Received')
    const first = page.getByTestId('watch-dates').first()
    await expect(first).toContainText('Cleared')
    await expect(first).toContainText('recall began')
    await expect(page.getByTestId('watch-attribution').first()).toContainText('FDA-listed')
  })
})

test.describe('recall attribution', () => {
  test('a recall record says how FDA ties it to the clearance', async ({ page }) => {
    await page.goto('/#/check/K252078')
    await page.locator('.g-node[data-k="K113053"]').click()
    const drawer = page.getByTestId('provenance')
    await expect(drawer).toContainText('Recall records on which FDA lists this 510(k)')
    const card = drawer.locator('.recall[data-attribution]').first()
    await expect(card).toContainText('FDA-listed')
    await expect(card).toContainText(/name (match|not found) \(heuristic\)|name not checked/)
    await expect(drawer).not.toContainText(/model named|product family/i)
  })

  test('a recall that predates the clearance is a caveat, not a conclusion', async ({ page }) => {
    await page.route('**/api/assess/K252078*', async (route) => {
      const a = await (await route.fetch()).json()
      const holder = a.ancestors.find((x) => x.k === 'K113053')
      holder.recalls = holder.recalls.map((r, i) => (i === 0 ? { ...r, linked_before_clearance: true, link_name_check: 'match' } : r))
      await route.fulfill({ json: a })
    })
    await page.goto('/#/check/K252078')
    await page.locator('.g-node[data-k="K113053"]').click()
    const caveat = page.getByTestId('provenance').getByTestId('recall-predates').first()
    await expect(caveat).toContainText('Recall began before this clearance')
    await expect(caveat).toContainText('do not establish whether this cleared model was affected')
  })
})
