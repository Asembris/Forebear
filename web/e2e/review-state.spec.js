import { test, expect } from '@playwright/test'
import { startIsolatedApi } from './server.mjs'

/*
  After a review the provenance drawer shows the citation exactly as the graph now stores it: the review, the
  reviewer and the PDF version the review was made on. The review buttons and status follow that record, never a
  locally patched copy of the old one.
  K200480 -> K131982 and K200480 -> K130077 are machine-extracted, never-reviewed predicate links in K251770's
  lineage (the two-hop showcase); each test uses its own, because clearing a review still records the PDF version.
  K251889 -> K251661 is seeded by e2e/seed_outdated_review.py: a person confirmed it on an earlier PDF version.
  Re-reviewing it makes the review current, and nothing in the API can make a review outdated again, so that test
  runs against its own API on a freshly seeded store copy: every attempt, retry or repeat starts from the same state.
*/
const SRC = 'K200480', DST = 'K131982', DST2 = 'K130077'

async function openHop(page, dst = DST) {
  await page.goto('/#/check/K251770')
  const row = page.getByTestId('depth-contrast').locator('.dc-route li').filter({ hasText: `${SRC} → ${dst}` })
  await row.getByRole('button', { name: 'Provenance' }).click()
  const drawer = page.getByTestId('provenance')
  await expect(drawer).toBeVisible()
  await expect(drawer.getByTestId('edge-review')).toHaveText('not reviewed by a person')
  await expect(drawer.getByTestId('edge-trust')).toHaveText('Machine-extracted')
  return drawer
}

test.describe('provenance review state', () => {
  // clear only the edge a test reviewed: clearing records the PDF version too, so it must not touch the others
  const touched = new Set()
  test.afterEach(async ({ request }) => {
    for (const dst of touched) await request.post('/api/citation/review', { data: { src: SRC, dst, status: '' } })
    touched.clear()
  })

  test('reject then restore follows the graph', async ({ page }) => {
    touched.add(DST)
    const drawer = await openHop(page)
    const panel = page.getByTestId('depth-contrast')

    await drawer.getByRole('button', { name: 'Reject citation' }).click()
    await expect(drawer.getByRole('status')).toContainText('Recorded: rejected')
    await expect(drawer.getByTestId('edge-review')).toHaveText('rejected by user')
    await expect(drawer.getByTestId('edge-trust')).toHaveText('Rejected by a person')
    await expect(drawer.getByRole('button', { name: 'Restore citation' })).toBeVisible()
    await expect(drawer.getByRole('button', { name: 'Reject citation' })).toHaveCount(0)
    await expect(drawer).not.toContainText('earlier version')
    await expect(panel.locator('.dc-route .dc-n', { hasText: `${SRC} → ${DST}` })).toHaveCount(0)

    await drawer.getByRole('button', { name: 'Restore citation' }).click()
    await expect(drawer.getByRole('status')).toContainText('Review cleared')
    await expect(drawer.getByTestId('edge-review')).toHaveText('not reviewed by a person')
    await expect(drawer.getByTestId('edge-trust')).toHaveText('Machine-extracted')
    await expect(drawer.getByRole('button', { name: 'Reject citation' })).toBeVisible()
    await expect(panel.locator('.dc-route')).toContainText(`${SRC} → ${DST}`)   // the depth contrast follows too
  })

  test('confirm then unconfirm follows the graph', async ({ page }) => {
    touched.add(DST2)
    const drawer = await openHop(page, DST2)

    await drawer.getByRole('button', { name: 'Confirm citation' }).click()
    await expect(drawer.getByRole('status')).toContainText('Recorded: confirmed')
    await expect(drawer.getByTestId('edge-review')).toHaveText('confirmed by user')
    await expect(drawer.getByTestId('edge-trust')).toHaveText('Confirmed by a person')
    await expect(drawer.getByRole('button', { name: 'Clear confirmation' })).toBeVisible()
    await expect(drawer).not.toContainText('earlier version')

    await drawer.getByRole('button', { name: 'Clear confirmation' }).click()
    await expect(drawer.getByRole('status')).toContainText('Review cleared')
    await expect(drawer.getByTestId('edge-review')).toHaveText('not reviewed by a person')
    await expect(drawer.getByTestId('edge-trust')).toHaveText('Machine-extracted')
    await expect(drawer.getByRole('button', { name: 'Confirm citation' })).toBeVisible()
  })

  test('the review response carries the authoritative edge, with both PDF versions', async ({ request }) => {
    touched.add(DST)
    const r = await (await request.post('/api/citation/review', { data: { src: SRC, dst: DST, status: 'rejected' } })).json()
    const c = r.citation
    expect([c.src, c.dst, c.review, c.reviewer, c.trust, c.in_lineage]).toEqual([SRC, DST, 'rejected', 'user', null, false])
    expect(c.source_sha256).toMatch(/^[0-9a-f]{64}$/)
    expect(c.reviewed_source_sha256).toBe(c.source_sha256)
    expect(c.page).toBe(4)
  })
})

const withOutdatedReview = test.extend({
  // test-scoped: started before and torn down after each attempt, so a retry never sees a consumed seed
  outdatedApi: async ({}, use) => {
    const api = await startIsolatedApi({ seed: 'seed_outdated_review.py' })
    try { await use(api.url) } finally { await api.stop() }
  },
})

withOutdatedReview('a review made on an earlier PDF is shown as outdated until a person reviews it again', async ({ page, outdatedApi }) => {
  await page.goto(`${outdatedApi}/#/check/K251889`)
  const cit = page.locator('.cit', { has: page.getByTestId('cit-status-K251661') })
  await cit.getByRole('button', { name: /Provenance/ }).click()
  const drawer = page.getByTestId('provenance')
  await expect(drawer.getByTestId('edge-review')).toHaveText('confirmed by user on an earlier version of the summary; needs re-review')
  await expect(drawer).toContainText('A person reviewed an earlier version of the FDA summary; it needs re-review')
  await expect(drawer.getByTestId('edge-trust')).not.toHaveText('Confirmed by a person')
  // an outdated confirmation is not a current one: the drawer offers to confirm, not to clear
  await expect(drawer.getByRole('button', { name: 'Confirm citation' })).toBeVisible()
  await expect(drawer.getByRole('button', { name: 'Clear confirmation' })).toHaveCount(0)

  await drawer.getByRole('button', { name: 'Confirm citation' }).click()
  await expect(drawer.getByRole('status')).toContainText('Recorded: confirmed')
  await expect(drawer.getByTestId('edge-review')).toHaveText('confirmed by user')
  await expect(drawer.getByTestId('edge-trust')).toHaveText('Confirmed by a person')
  await expect(drawer).not.toContainText('earlier version')
  await expect(drawer.getByRole('button', { name: 'Clear confirmation' })).toBeVisible()
  await expect(page.getByTestId('cit-status-K251661')).toHaveText('Confirmed')
})
