import { test, expect } from '@playwright/test'

const shot = (page, name) => page.screenshot({ path: `test-results/shots/${test.info().project.name}-${name}.png` })

test.describe('opening and film', () => {
  test('intro plays once per session, can be skipped, and never repeats on reload', async ({ page }) => {
    await page.goto('/')
    const intro = page.getByTestId('intro')
    await expect(intro).toBeVisible()
    await expect(intro.locator('.intro-tag')).toContainText('Every clearance has a past.')
    await page.getByRole('button', { name: /Skip intro/ }).click()
    await expect(intro).toBeHidden({ timeout: 2000 })
    await page.reload()
    await page.waitForTimeout(300)
    await expect(page.getByTestId('intro')).toHaveCount(0)
  })

  test('intro ends by itself in about three seconds', async ({ page }) => {
    await page.goto('/')
    const t0 = Date.now()
    await expect(page.getByTestId('intro')).toBeHidden({ timeout: 5000 })
    expect(Date.now() - t0).toBeLessThan(4200)
  })

  test('Escape skips the intro', async ({ page }) => {
    await page.goto('/')
    await expect(page.getByTestId('intro')).toBeVisible()
    await page.keyboard.press('Escape')
    await expect(page.getByTestId('intro')).toBeHidden({ timeout: 2000 })
  })

  test('deep links skip the intro and the film entirely', async ({ page }) => {
    await page.goto('/#/check/K252078')
    await expect(page.getByTestId('verdict')).toContainText('Review lineage')
    await expect(page.getByTestId('intro')).toHaveCount(0)
    await expect(page.getByTestId('film-canvas')).toHaveCount(0)
  })

  test('the film renders on one canvas and scroll advances the chapters', async ({ page }) => {
    await page.addInitScript(() => sessionStorage.setItem('forebear:intro', 'seen'))
    await page.goto('/')
    const canvas = page.getByTestId('film-canvas')
    await expect(canvas).toHaveAttribute('data-renderer', 'canvas2d')
    expect(await page.locator('canvas').count()).toBe(1)
    await shot(page, 'film-0-hero')
    for (const [id, label, n] of [['the-filing', 'The filing', 1], ['the-connection', 'The connection', 2], ['the-discovery', 'The discovery', 3]]) {
      await page.locator(`#${id}-copy`).scrollIntoViewIfNeeded()
      await page.evaluate((i) => document.getElementById(`${i}-copy`).scrollIntoView({ block: 'center' }), id)
      await expect(page.locator('.film-index a.on')).toContainText(label, { timeout: 4000 })
      await page.waitForTimeout(900)
      await shot(page, `film-${n}-${id}`)
    }
    // the film's claims come from the shipped store
    await expect(page.locator('#the-filing-copy')).toContainText('page 6')
    await expect(page.locator('#the-discovery-copy')).toContainText('14 Jun 2021')
    await expect(page.locator('#the-discovery-copy')).toContainText('Z-1957-2021')
  })

  test('the handoff opens the real investigation', async ({ page }) => {
    await page.addInitScript(() => sessionStorage.setItem('forebear:intro', 'seen'))
    await page.goto('/')
    await page.locator('#handoff-copy').waitFor({ state: 'attached' })
    await page.evaluate(() => document.getElementById('handoff-copy').scrollIntoView({ block: 'center' }))
    await page.waitForTimeout(1200)
    await shot(page, 'film-4-handoff')
    await page.getByTestId('handoff-investigate').click()
    await expect(page).toHaveURL(/#\/check\/K252078$/)
    await expect(page.getByTestId('finding-sentence')).toContainText('K113053')
  })

  test('reduced motion: no intro, no canvas film, every word readable', async ({ browser }) => {
    const ctx = await browser.newContext({ reducedMotion: 'reduce', viewport: { width: 1280, height: 860 } })
    const page = await ctx.newPage()
    await page.goto('/')
    await expect(page.getByTestId('intro')).toHaveCount(0)
    await expect(page.locator('html')).toHaveAttribute('data-film', 'off')
    const statement = page.locator('#the-discovery-copy .ln > span').first()
    await statement.scrollIntoViewIfNeeded()
    const transform = await statement.evaluate((el) => getComputedStyle(el).transform)
    expect(['none', 'matrix(1, 0, 0, 1, 0, 0)']).toContain(transform)
    await page.screenshot({ path: 'test-results/shots/reduced-motion.png' })
    await ctx.close()
  })

  test('replay brings the opening back', async ({ page }) => {
    await page.addInitScript(() => sessionStorage.setItem('forebear:intro', 'seen'))
    await page.goto('/#/watch')
    await page.getByRole('button', { name: 'Replay the film' }).click()
    await expect(page.getByTestId('intro')).toBeVisible()
  })
})

test.describe('investigation workspace', () => {
  test('finding, critical chain and authority are immediate', async ({ page }) => {
    await page.goto('/#/check/K252078')
    await expect(page.getByTestId('verdict')).toContainText('Deterministic assessment')
    const sentence = page.getByTestId('finding-sentence')
    await expect(sentence).toContainText('page 6')
    await expect(sentence).toContainText('Class I Device Design')
    await expect(sentence).toContainText('before K252078 was cleared')
    await expect(page.getByTestId('critical-chain')).toContainText('K113053')
    await shot(page, 'investigation-top')
  })

  test('keyboard reaches a thread and opens its provenance with the PDF page', async ({ page }) => {
    await page.goto('/#/check/K252078')
    const edge = page.locator('[aria-label^="Citation: K252078 cites K113053"]')
    await edge.focus()
    await page.keyboard.press('Enter')
    const drawer = page.getByTestId('provenance')
    await expect(drawer).toBeVisible()
    await expect(drawer).toContainText('Machine-extracted')
    await expect(drawer.getByTestId('pdf-page-link')).toHaveAttribute('href', /K252078\.pdf#page=6$/)
    await expect(drawer).toContainText('PDF text layer')
    await shot(page, 'provenance')
    await page.keyboard.press('Escape')
    await expect(drawer).toHaveCount(0)
  })

  test('a node opens its recall records', async ({ page }) => {
    await page.goto('/#/check/K252078')
    await page.locator('.g-node[data-k="K113053"]').click()
    const drawer = page.getByTestId('provenance')
    await expect(drawer).toContainText('Direct predicate')
    await expect(drawer).toContainText('Z-1957-2021')
    await expect(drawer).toContainText('began before K252078 was cleared')
  })

  test('progressive disclosure expands deeper generations', async ({ page }) => {
    await page.goto('/#/check/K252078')
    const before = await page.locator('.g-node').count()
    await page.locator('.g-more').click()
    await expect.poll(() => page.locator('.g-node').count()).toBeGreaterThan(before)
  })

  test('review write: rejecting the predicate changes the verdict, restoring brings it back', async ({ page }) => {
    await page.goto('/#/check/K252078')
    await expect(page.getByTestId('verdict')).toContainText('Review lineage')
    const cit = page.locator('.cit').filter({ hasText: 'K113053' })
    await cit.getByRole('button', { name: 'Reject' }).click()
    await expect(page.getByTestId('verdict')).not.toContainText('Review lineage', { timeout: 10000 })
    await page.locator('.cit').filter({ hasText: 'K113053' }).getByRole('button', { name: 'Restore' }).click()
    await expect(page.getByTestId('verdict')).toContainText('Review lineage', { timeout: 10000 })
  })

  test('saving an assessment records it in history', async ({ page }) => {
    await page.goto('/#/check/K252078')
    await page.getByRole('button', { name: 'Save assessment to graph' }).click()
    await page.getByLabel(/Optional analyst note/).fill('e2e check')
    await page.getByRole('button', { name: 'Save to Relate' }).click()
    await expect(page.getByRole('status').filter({ hasText: /Saved A-/ })).toBeVisible()
    await page.goto('/#/history')
    await expect(page.locator('.tbl').first()).toContainText('K252078')
  })

  test('a conditional route is never called a predicate', async ({ page }) => {
    await page.goto('/#/check/K120562')
    const sentence = page.getByTestId('finding-sentence')
    await expect(sentence).toContainText('could not resolve')
    await expect(sentence).toContainText('conditional')
    await expect(sentence).not.toContainText('That predicate')
    await expect(page.getByTestId('critical-chain')).toContainText('citation unresolved')
  })

  test('search finds a device by name and opens it', async ({ page }) => {
    await page.goto('/#/check')
    await expect(page.getByRole('heading', { name: /Check a predicate/ })).toBeVisible()
    await page.keyboard.press('/')
    await expect(page.getByRole('combobox')).toBeFocused()
    await page.keyboard.type('BreathePal')
    await expect(page.locator('#search-results')).toContainText('K252078')
    await page.keyboard.press('Enter')
    await expect(page).toHaveURL(/#\/check\/K252078$/)
  })
})

test.describe('recall evidence views', () => {
  test('recall reach separates after-recall and conditional descendants', async ({ page }) => {
    await page.goto('/#/reach/88058,88071')
    const stats = page.getByTestId('reach-stats')
    await expect(stats).toContainText('14')
    await expect(stats).toContainText('conditional')
    await shot(page, 'reach')
  })

  test('watchlist marks and filters conditional rows', async ({ page }) => {
    await page.goto('/#/watch')
    await expect(page.locator('.bigstats')).toContainText('conditional')
    await page.getByRole('button', { name: 'Conditional only' }).click()
    const rows = page.locator('.tbl tbody tr')
    const n = await rows.count()
    for (let i = 0; i < n; i++) await expect(rows.nth(i)).toHaveClass(/is-conditional/)
    await shot(page, 'watchlist')
  })

  test('compare shows a row per candidate', async ({ page }) => {
    await page.goto('/#/compare/K200480 K113053')
    await expect(page.locator('.tbl tbody tr')).toHaveCount(2)
  })
})

test.describe('responsive @responsive', () => {
  for (const [name, path] of [['landing', '/'], ['investigation', '/#/check/K252078'], ['watchlist', '/#/watch'], ['reach', '/#/reach/88058,88071']]) {
    test(`${name} has no horizontal page overflow`, async ({ page }) => {
      await page.addInitScript(() => sessionStorage.setItem('forebear:intro', 'seen'))
      await page.goto(path)
      await page.waitForLoadState('networkidle')
      await page.waitForTimeout(600)
      const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)
      expect(overflow).toBeLessThanOrEqual(1)
      await shot(page, `responsive-${name}`)
    })
  }

  test('the film chapters stay readable on small screens', async ({ page }) => {
    await page.addInitScript(() => sessionStorage.setItem('forebear:intro', 'seen'))
    await page.goto('/')
    await page.locator('#the-discovery-copy').waitFor({ state: 'attached' })
    await page.evaluate(() => document.getElementById('the-discovery-copy').scrollIntoView({ block: 'center' }))
    await page.waitForTimeout(1200)
    await expect(page.locator('#the-discovery-copy')).toBeInViewport()
    await shot(page, 'responsive-film-discovery')
  })
})
