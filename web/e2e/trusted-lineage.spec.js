import { test, expect } from '@playwright/test'

// Trusted lineage: a link suggested only by an automated source (LLM triage, or the MCP client) is advisory and
// never changes the verdict; a person's confirmation does. Runs on the throwaway copy of the shipped store.
// K203126 -> K133801 is a *reference* to a device with a design-related recall; K203126 is otherwise clean.

const SRC = 'K203126'
const DST = 'K133801'

test.describe('AI-only lineage is advisory', () => {
  test.afterEach(async ({ request }) => {
    await request.post('/api/citation/review', { data: { src: SRC, dst: DST, status: '', via: 'user' } })
  })

  test('an automated-client confirmation shows as advisory and leaves the verdict alone', async ({ page, request }) => {
    const r = await request.post('/api/citation/review', { data: { src: SRC, dst: DST, status: 'confirmed', note: 'agent', via: 'mcp-client' } })
    expect((await r.json()).advisory).toBe(true)
    await page.goto(`/#/check/${SRC}`)
    await expect(page.getByTestId('verdict')).toContainText('No design-recall signal · provisional')
    await expect(page.getByTestId(`cit-status-${DST}`)).toHaveText('Advisory')
    await expect(page.getByTestId('evidence-reason').first()).toBeVisible()
    await expect(page.getByTestId('review-queue')).toContainText('not used for the verdict')
  })

  test("a person's confirmation makes the link trusted and the verdict changes", async ({ page, request }) => {
    await request.post('/api/citation/review', { data: { src: SRC, dst: DST, status: 'confirmed', note: 'agent', via: 'mcp-client' } })
    await page.goto(`/#/check/${SRC}`)
    const cit = page.locator('.cit', { has: page.getByTestId(`cit-status-${DST}`) })
    await cit.getByRole('button', { name: 'Confirm', exact: true }).click()
    await expect(page.getByTestId(`cit-status-${DST}`)).toHaveText('Confirmed')
    await expect(page.getByTestId('verdict')).toContainText('Review lineage')
  })
})

test('re-ingest lists citations retired by the refreshed summary', async ({ page }) => {
  await page.route('**/api/ingest', (route) => route.fulfill({
    json: {
      k: 'K261000', was_present: true, lineage_was_known: true, summary_status: 'ok', summary_url: null,
      citations_added: [], citations_unresolved: [], new_devices: [], recalls_linked: [], extraction: {},
      graph_before: {}, graph_after: {}, rels_before: {}, rels_after: {},
      reconciliation: { ran: true, skipped_reason: null, new: [], restored: [],
        retired: [{ src: 'K261000', dst: 'K000003', review: 'confirmed', reviewer: 'user' }],
        retired_with_human_review: ['K000003'] },
    },
  }))
  await page.goto('/#/ingest/K261000')
  await page.getByRole('button', { name: 'Read and add' }).click()
  await expect(page.getByTestId('ingest-retired')).toContainText('K000003 (confirmed by user)')
  await expect(page.getByTestId('ingest-retired')).toContainText('kept with their reviews and provenance')
})

test('re-ingest can explicitly refresh the FDA summary and reports a changed PDF', async ({ page }) => {
  let body = null
  await page.route('**/api/ingest', (route) => {
    body = route.request().postDataJSON()
    return route.fulfill({
      json: {
        k: 'K261000', was_present: true, lineage_was_known: true, summary_status: 'ok', summary_url: null,
        summary_sha256: 'bbbbbbbbbbbbbbbb', refresh: { changed: true, previous_sha256: 'aaaaaaaaaaaaaaaa' },
        citations_added: [], citations_unresolved: [], new_devices: [], recalls_linked: [], extraction: {},
        graph_before: {}, graph_after: {}, rels_before: {}, rels_after: {},
        reconciliation: { ran: true, skipped_reason: null, new: [], restored: [], retired: [], retired_with_human_review: [] },
      },
    })
  })
  await page.goto('/#/ingest/K261000')
  await page.getByTestId('ingest-refresh').check()
  await page.getByRole('button', { name: 'Read and add' }).click()
  await expect(page.getByTestId('ingest-refresh-result')).toContainText('aaaaaaaaaaaa → bbbbbbbbbbbb')
  expect(body).toEqual({ k: 'K261000', refresh: true })
})
