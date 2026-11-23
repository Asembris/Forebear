import { test, expect } from '@playwright/test'
import { dateOrder, recallTiming, recallTimingText } from '../src/evidence.js'

/*
  Recall timing is decided by comparing calendar dates, never by rounded month differences.
  A month difference rounds a recall that began earlier in the clearance month (or in the previous
  calendar month across a year boundary) down to zero, which earlier code reported as "after".
*/

test.describe('recall timing: pure rules', () => {
  test('dateOrder compares calendar days', () => {
    expect(dateOrder('2026-03-01', '2026-03-17')).toBe(-1)
    expect(dateOrder('2026-03-17', '2026-03-17')).toBe(0)
    expect(dateOrder('2026-03-17T00:00:00', '2026-03-17')).toBe(0)
    expect(dateOrder('2027-01-05', '2026-12-31')).toBe(1)
    expect(dateOrder(null, '2026-03-17')).toBeNull()
  })

  test('same month, recall first: before, under a month', () => {
    const t = recallTiming('2026-03-01', '2026-03-17')
    expect(t).toEqual({ relation: 'before', months: 0, duration: '<1 mo' })
    expect(recallTimingText(t, 'K1')).toBe('<1 mo before K1 was cleared')
    expect(recallTimingText(t, 'K1', 'chip')).toBe("Recall began <1 mo before K1's clearance")
  })

  test('same month, clearance first: after, under a month', () => {
    const t = recallTiming('2026-03-20', '2026-03-17')
    expect(t).toEqual({ relation: 'after', months: 0, duration: '<1 mo' })
    expect(recallTimingText(t, 'K1')).toBe('<1 mo after K1 was cleared')
  })

  test('same day: neither before nor after', () => {
    const t = recallTiming('2026-03-17', '2026-03-17')
    expect(t.relation).toBe('same-day')
    expect(recallTimingText(t, 'K1')).toBe('on the day K1 was cleared')
    expect(recallTimingText(t, 'K1', 'chip')).toBe("Recall began on the day of K1's clearance")
  })

  test('cross-year, recall first: before, even when months round to zero', () => {
    expect(recallTiming('2025-12-20', '2026-01-10')).toEqual({ relation: 'before', months: 0, duration: '<1 mo' })
    expect(recallTiming('2021-06-14', '2026-03-17')).toEqual({ relation: 'before', months: 57, duration: '4 yr 9 mo' })
  })

  test('cross-year, clearance first: after, measured forwards', () => {
    expect(recallTiming('2027-01-05', '2026-03-17')).toEqual({ relation: 'after', months: 9, duration: '9 mo' })
    expect(recallTiming('2026-01-02', '2025-12-30')).toEqual({ relation: 'after', months: 0, duration: '<1 mo' })
  })

  test('missing dates give no timing', () => {
    expect(recallTiming(null, '2026-03-17')).toBeNull()
    expect(recallTimingText(null, 'K1')).toBe('')
  })
})

/* Rewrite the shipped K252078 assessment so its key recall and clearance fall on chosen dates. */
async function withDates(page, initiated, clearance) {
  await page.route('**/api/assess/K252078*', async (route) => {
    const res = await route.fetch()
    const a = await res.json()
    a.device.decision_date = clearance
    for (const s of a.signals) for (const e of s.evidence) if (e.type === 'recall') e.initiated = initiated
    for (const x of a.ancestors) for (const r of x.recalls) r.initiated = initiated
    await route.fulfill({ response: res, json: a })
  })
  await page.goto('/#/check/K252078')
  await expect(page.getByTestId('finding-sentence')).toBeVisible()
}

test.describe('recall timing: finding sentence and critical chain', () => {
  test('same month, recall first, reads "before"', async ({ page }) => {
    await withDates(page, '2026-03-01', '2026-03-17')
    await expect(page.getByTestId('finding-sentence')).toContainText('<1 mo before K252078 was cleared')
    await expect(page.getByTestId('critical-chain')).toContainText("Recall began <1 mo before K252078's clearance")
    await expect(page.getByTestId('finding-sentence')).not.toContainText('after')
  })

  test('same day reads "on the day", never before or after', async ({ page }) => {
    await withDates(page, '2026-03-17', '2026-03-17')
    const sentence = page.getByTestId('finding-sentence')
    await expect(sentence).toContainText('on the day K252078 was cleared')
    await expect(sentence).not.toContainText(/before K252078|after K252078/)
    await expect(page.getByTestId('critical-chain')).toContainText("Recall began on the day of K252078's clearance")
  })

  test('cross-year, recall first by days, reads "before"', async ({ page }) => {
    await withDates(page, '2025-12-20', '2026-01-10')
    await expect(page.getByTestId('finding-sentence')).toContainText('<1 mo before K252078 was cleared')
    await expect(page.getByTestId('critical-chain')).toContainText("Recall began <1 mo before K252078's clearance")
  })

  test('cross-year, clearance first, reads "after" with a forward duration', async ({ page }) => {
    await withDates(page, '2027-01-05', '2026-03-17')
    await expect(page.getByTestId('finding-sentence')).toContainText('9 mo after K252078 was cleared')
    await expect(page.getByTestId('critical-chain')).toContainText("Recall began 9 mo after K252078's clearance")
  })

  test('the shipped case is unchanged', async ({ page }) => {
    await page.goto('/#/check/K252078')
    await expect(page.getByTestId('finding-sentence')).toContainText('4 yr 9 mo before K252078 was cleared')
    await expect(page.getByTestId('critical-chain')).toContainText("Recall began 4 yr 9 mo before K252078's clearance")
  })
})
