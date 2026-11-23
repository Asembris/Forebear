import React, { useEffect, useMemo, useState } from 'react'
import { api } from '../api.js'
import { ATTRIBUTION, EVIDENCE_REASON_TEXT, EVIDENCE_TONE, TIMING_TEXT, fmtDate, verdictView } from '../evidence.js'

const Head = ({ eyebrow, title, children }) => (
  <div className="page-head"><p className="eyebrow">{eyebrow}</p><h1>{title}</h1>{children && <p>{children}</p>}</div>
)
const rowKey = (fn) => (e) => { if (e.key === 'Enter') fn() }

/* ---------------------------------------------------------------- compare */
export function CompareView({ initial, go }) {
  const [text, setText] = useState(initial || 'K200480 K113053 K233643 K143677')
  const [rows, setRows] = useState(null)
  const [err, setErr] = useState(null)
  const [busy, setBusy] = useState(false)
  const run = (t = text) => {
    const ks = [...new Set(t.toUpperCase().match(/K\d{6}/g) || [])].slice(0, 8)
    if (!ks.length) { setErr('Enter one or more K-numbers'); return }
    setErr(null); setBusy(true)
    api.compare(ks).then(setRows).catch((e) => setErr(e.message)).finally(() => setBusy(false))
  }
  useEffect(() => { run(initial || text) }, [initial])
  return (
    <div>
      <Head eyebrow="Investigate" title="Compare candidate predicates">
        FDA's draft guidance suggests documenting how each candidate predicate meets the selection best practices. This table
        covers the recall practice: each candidate's own recalls and those in its ancestry, computed live from the graph.
      </Head>
      <section className="panel">
        <form className="row-in" onSubmit={(e) => { e.preventDefault(); run() }}>
          <input className="field" value={text} onChange={(e) => setText(e.target.value)} aria-label="K-numbers to compare (up to 8)" />
          <button className="btn btn-primary" disabled={busy}>{busy ? 'Comparing…' : 'Compare'}</button>
        </form>
        {err && <p className="err">{err}</p>}
      </section>
      {rows && (
        <section className="panel">
          <div className="tbl-wrap">
            <table className="tbl">
              <thead><tr><th>Candidate</th><th>Cleared</th><th>Verdict</th><th>Evidence<br />(verdict window)</th><th>Own recalls<br />(design)</th>
                <th>Flagged ancestors<br />gen 1–2</th><th>Ancestors<br />(unread)</th><th>Top signal</th></tr></thead>
              <tbody>{rows.map((r) => {
                if (!r.found) return (
                  <tr key={r.k}><td><span className="k mono">{r.k}</span></td><td colSpan={7} className="sub">Not in the graph. <a href={`#/ingest/${r.k}`}>Read it from FDA →</a></td></tr>)
                const vv = verdictView(r.verdict, r.evidence)
                return (
                <tr key={r.k} className="click" tabIndex={0} data-k={r.k} data-evidence={r.evidence} onClick={() => go('check', r.k)} onKeyDown={rowKey(() => go('check', r.k))}>
                  <td><span className="k mono">{r.k}</span><div className="sub">{r.name}</div><div className="sub">{r.applicant}</div></td>
                  <td className="num">{fmtDate(r.decision_date)}</td>
                  <td><span className={`chip tone-${vv.tone}`} data-testid="compare-verdict">{vv.label}</span>
                    {r.conditional && <div><span className="chip tone-violet">conditional</span></div>}
                    <div className="sub" style={{ maxWidth: 320 }} data-testid="compare-reason">{r.verdict_reason}</div></td>
                  <td><span className={`chip tone-${EVIDENCE_TONE[r.evidence] || 'muted'}`} data-testid="compare-evidence">{r.evidence}</span>
                    {(r.evidence_reasons || []).map((c) => <div key={c} className="sub">{EVIDENCE_REASON_TEXT[c] || c}</div>)}</td>
                  <td className="num">{r.own_recalls} <span className="sub">({r.own_design_recalls})</span></td>
                  <td className="num">{r.flagged_ancestors_gen12}</td>
                  <td className="num">{r.ancestors} <span className="sub">({r.lineage_unknown})</span></td>
                  <td className="sub" style={{ maxWidth: 360 }}>{r.top_signal || '—'}</td>
                </tr>)
              })}
              </tbody>
            </table>
          </div>
          <p className="graph-hint">Verdicts are deterministic documentation signals; a lower count is not a statement that a device is safer.
            A verdict on partial or uncertain evidence is provisional: equal verdicts on unequal evidence are not equivalent.</p>
        </section>
      )}
    </div>
  )
}

/* ---------------------------------------------------------------- recall reach */
export function ReachView({ initial, go }) {
  const [ev, setEv] = useState(initial || '88058,88071')
  const [data, setData] = useState(null)
  const [err, setErr] = useState(null)
  const run = (e = ev) => { setErr(null); setData(null); api.recallEvent(e.replace(/\s/g, '')).then(setData).catch((x) => setErr(x.message)) }
  useEffect(() => { setEv(initial || '88058,88071'); run(initial || '88058,88071') }, [initial])
  const desc = data?.descendants || []
  const c = data?.counts || {}
  // [id, title, rows, hint, always shown]
  const groups = [
    ['after-supported', 'Cleared after the recall began · supported route', desc.filter((d) => d.timing === 'after' && d.evidence === 'supported'),
      '"After it began", not after it was resolved. A descendant is not recalled because of its ancestor.', true],
    ['after-conditional', 'Cleared after the recall began · conditional route only', desc.filter((d) => d.timing === 'after' && d.evidence === 'conditional'),
      'Every route to the recalled clearance runs through a citation the audit could not resolve.', false],
    ['same-day', 'Cleared the day the recall began', desc.filter((d) => d.timing === 'same_day'),
      'Same calendar day: the dates cannot order them, so these count as neither before nor after.', false],
    ['unknown', 'Timing unknown', desc.filter((d) => d.timing === 'unknown'), 'A clearance date or recall start is missing.', false],
    ['before', 'Cleared before the recall began', desc.filter((d) => d.timing === 'before'), null, true],
  ]
  return (
    <div>
      <Head eyebrow="Recall evidence" title="Recall reach">
        Start from an FDA recall event. Forebear finds every clearance FDA lists on it, then every later clearance that cites one of them,
        up to three generations, and compares each clearance date with the recall start on its own supported route.
      </Head>
      <section className="panel">
        <form className="row-in" onSubmit={(e) => { e.preventDefault(); run() }}>
          <input className="field" value={ev} onChange={(e) => setEv(e.target.value)} aria-label="Recall event numbers, comma-separated" />
          <button className="btn btn-primary">Trace</button>
        </form>
        <p className="muted small" style={{ marginBottom: 0 }}>Examples: <button className="tag-btn" onClick={() => { setEv('88058,88071'); run('88058,88071') }}>88058,88071</button> Philips PE-PUR foam recall, June 2021 (openFDA files it as two events) ·{' '}
          <button className="tag-btn" onClick={() => { setEv('86646'); run('86646') }}>86646</button>{' '}
          <button className="tag-btn" onClick={() => { setEv('84406'); run('84406') }}>84406</button></p>
        {err && <p className="err">{err}</p>}
      </section>
      {!data && !err && <div className="loading-thread"><i />Tracing descendants in Relate…</div>}
      {data && (
        <>
          <section className="panel" data-testid="reach-stats">
            <div className="bigstats">
              <div><b>{data.recalled.length}</b><span>clearances FDA lists on recall event(s) {data.event}</span></div>
              <div><b>{desc.length}</b><span>later clearances descend from them</span></div>
              <div className="amber" data-testid="reach-count-after"><b>{c.after_supported ?? 0}</b><span>cleared after the recall on a supported route began{data.initiated ? ` (earliest ${fmtDate(data.initiated)})` : ''}</span></div>
              <div className="violet" data-testid="reach-count-conditional"><b>{c.conditional ?? 0}</b><span>reached only through an unresolved citation (conditional){c.after_conditional ? `, ${c.after_conditional} of them cleared after` : ''}</span></div>
              {(c.same_day > 0 || c.unknown > 0) && (
                <div data-testid="reach-count-undetermined"><b>{(c.same_day || 0) + (c.unknown || 0)}</b><span>timing not determinable ({c.same_day || 0} same day, {c.unknown || 0} missing a date)</span></div>)}
            </div>
            <div className="tags" style={{ marginTop: 14 }}>{data.recalled.map((r) => (
              <button key={r.k} className="tag-btn" onClick={() => go('check', r.k)} title={ATTRIBUTION[r.attribution]?.text}>
                <span className="k">{r.k}</span> {r.name} <span className="muted">· {ATTRIBUTION[r.attribution]?.short}</span></button>))}</div>
            <p className="muted small" style={{ marginBottom: 0 }}>FDA lists these clearances on the recall record. That is an association: it does not by itself
              mean the listed model, as cleared, is the recalled product.</p>
          </section>
          <section className="panel">
            {groups.filter(([, , rows, , always]) => always || rows.length).map(([id, title, rows, hint], i) => (
              <div key={id} data-testid={`reach-${id}`}>
                <div className="panel-head" style={i ? { marginTop: 22 } : undefined}><h2>{title} <span className="count">{rows.length}</span></h2>
                  {hint && <p className="hint">{hint}</p>}</div>
                <DescTable rows={rows} go={go} />
              </div>))}
          </section>
        </>
      )}
    </div>
  )
}

function DescTable({ rows, go }) {
  if (!rows.length) return <p className="muted">None.</p>
  return (
    <div className="tbl-wrap">
      <table className="tbl">
        <thead><tr><th>Device</th><th>Applicant</th><th>Cleared</th><th>Recall began<br />on its route</th><th>Distance</th><th>Descends from</th></tr></thead>
        <tbody>{rows.map((d) => {
          const cond = d.evidence === 'conditional'
          const mixed = !cond && d.conditional_via?.length > 0
          const gen = d.supported_gen ?? d.gen
          return (
            <tr key={d.k} className={'click' + (cond ? ' is-conditional' : '')} tabIndex={0} data-k={d.k} data-timing={d.timing} data-evidence={d.evidence}
              onClick={() => go('check', d.k)} onKeyDown={rowKey(() => go('check', d.k))}>
              <td><span className="k mono">{d.k}</span> {cond && <span className="chip tone-violet">conditional</span>}
                {mixed && <span className="chip tone-muted" title="Some routes are supported, others rest on an unresolved citation">mixed routes</span>}
                <div className="sub">{d.name}</div></td>
              <td className="sub">{d.applicant}</td>
              <td className="num">{fmtDate(d.decision_date)}</td>
              <td className="num">{fmtDate(d.recall_started)}<div className="sub">{TIMING_TEXT[d.timing]}</div>
                {mixed && d.conditional_timing && d.conditional_timing !== d.timing && (
                  <div className="sub" style={{ color: 'var(--violet)' }}>Conditional route only: recall began {fmtDate(d.conditional_recall_started)}, {TIMING_TEXT[d.conditional_timing]}</div>)}</td>
              <td>{gen === 1 ? 'direct predicate' : `${gen} generations`}</td>
              <td className="sub">{d.via.map((v) => (
                <span key={v} style={d.conditional_via?.includes(v) ? { color: 'var(--violet)' } : undefined}
                  title={d.conditional_via?.includes(v) ? 'Reached only through an unresolved citation' : 'Reached through a supported citation'}>{v} </span>))}</td>
            </tr>
          )
        })}</tbody>
      </table>
    </div>
  )
}

/* ---------------------------------------------------------------- watchlist */
export function WatchlistView({ go }) {
  const [data, setData] = useState(null)
  const [err, setErr] = useState(null)
  const [filter, setFilter] = useState('all')
  useEffect(() => { api.watchlist().then(setData).catch((e) => setErr(e.message)) }, [])
  // conditional and supported_min_gen are computed by the API over every recall route, not the six it lists
  const rows = data?.rows || []
  const shown = rows.filter((r) => filter === 'all' || (filter === 'direct' && r.supported_min_gen === 1) || (filter === 'supported' && !r.conditional) || (filter === 'conditional' && r.conditional))
  const nCond = data?.conditional ?? rows.filter((r) => r.conditional).length
  return (
    <div>
      <Head eyebrow="Recall evidence" title="Watchlist: cited after a recall began">
        Clearances cleared after a design-related recall had already started on their predicate or grand-predicate. Close to, but not
        the same as, the JAMA study's measure (Class I predicate recalls, any cause). A question to ask, not a finding: the recall may
        have been fixed, or limited to lots or software versions.
      </Head>
      {err && <p className="err">{err}</p>}
      {!data && !err && <div className="loading-thread"><i />Querying the graph…</div>}
      {data && (
        <section className="panel">
          <div className="bigstats">
            <div><b>{data.count}</b><span>clearances in the dataset match</span></div>
            <div className="amber"><b>{data.direct_supported ?? data.direct}</b><span>cite a directly recalled predicate through a supported citation</span></div>
            <div className="violet"><b>{nCond}</b><span>conditional: every route runs through an unresolved citation</span></div>
          </div>
          <div className="seg" role="group" aria-label="Filter" style={{ marginTop: 14 }}>
            {[['all', 'All'], ['direct', 'Direct predicate'], ['supported', 'Supported routes'], ['conditional', 'Conditional only']].map(([id, l]) => (
              <button key={id} aria-pressed={filter === id} onClick={() => setFilter(id)}>{l}</button>))}
          </div>
        </section>
      )}
      {data && (
        <section className="panel">
          <div className="tbl-wrap">
            <table className="tbl">
              <thead><tr><th>Cleared device</th><th>Received / cleared</th><th>Recalled ancestor</th><th>Recall records</th></tr></thead>
              <tbody>{shown.map((r) => (
                <tr key={r.k} className={'click' + (r.conditional ? ' is-conditional' : '')} tabIndex={0} onClick={() => go('check', r.k)} onKeyDown={rowKey(() => go('check', r.k))}>
                  <td><span className="k mono">{r.k}</span> {r.conditional && <span className="chip tone-violet">conditional</span>}<div className="sub">{r.name}</div><div className="sub">{r.applicant}</div></td>
                  <td className="num">{fmtDate(r.received_date)}<div className="sub">{fmtDate(r.decision_date)}</div></td>
                  <td><span className="mono">{r.ancestors.join(', ')}</span><div className="sub">{r.conditional ? 'cited device · citation unresolved' : r.supported_min_gen === 1 ? 'direct predicate' : 'grand-predicate'}</div></td>
                  <td className="sub">{r.recall_count > 2 && <div className="muted">{r.recall_count} recall routes; first two:</div>}{r.recalls.slice(0, 2).map((x) => (
                    <div key={x.recall_id + x.ancestor}>{x.recall_id} · {x.classification || 'unclassified'} · {x.root_cause} · {fmtDate(x.initiated)}
                      {x.conditional && <span style={{ color: 'var(--violet)' }}> · conditional</span>}</div>))}</td>
                </tr>))}</tbody>
            </table>
          </div>
        </section>
      )}
    </div>
  )
}

/* ---------------------------------------------------------------- ingest */
export function IngestView({ initial, go, onChanged }) {
  const [k, setK] = useState(initial || '')
  const [busy, setBusy] = useState(false)
  const [res, setRes] = useState(null)
  const [err, setErr] = useState(null)
  useEffect(() => { if (initial) setK(initial) }, [initial])
  const run = async () => {
    setBusy(true); setErr(null); setRes(null)
    try { const r = await api.ingest(k); setRes(r); onChanged && onChanged() } catch (e) { setErr(e.message) } finally { setBusy(false) }
  }
  const delta = (a, b) => Object.keys({ ...a, ...b }).map((key) => [key, (b[key] || 0) - (a[key] || 0)]).filter(([, d]) => d)
  return (
    <div>
      <Head eyebrow="Graph" title="Add a clearance">
        Enter any 510(k) number. Forebear fetches its openFDA record and summary PDF live, extracts the predicates it cites,
        validates them against openFDA, links recalls, and MERGEs everything into the Relate store. Use it on an ancestor whose
        summary was not read to extend a lineage by one generation. Needs internet.
      </Head>
      <section className="panel">
        <form className="row-in" onSubmit={(e) => { e.preventDefault(); run() }}>
          <input className="field" value={k} placeholder="K-number, e.g. K241135" onChange={(e) => setK(e.target.value)} aria-label="K-number to read from FDA" />
          <button className="btn btn-primary" disabled={busy || !k}>{busy ? 'Reading from FDA…' : 'Read and add'}</button>
        </form>
        {busy && <div className="loading-thread"><i />Downloading the summary PDF and extracting citations…</div>}
        {err && <p className="err" role="alert">{err}</p>}
      </section>
      {res && (
        <section className="panel">
          <div className="panel-head"><h2>{res.k}: {res.was_present ? (res.lineage_was_known ? 're-read' : 'lineage extended') : 'added to the graph'}</h2></div>
          <p>Summary: <b>{res.summary_status}</b>{res.summary_url && <> · <a href={res.summary_url} target="_blank" rel="noreferrer">PDF ↗</a></>}</p>
          <p className="muted">Graph change: {delta(res.graph_before, res.graph_after).concat(delta(res.rels_before, res.rels_after))
            .map(([key, d]) => `${d > 0 ? '+' : ''}${d} ${key}`).join(' · ') || 'no new nodes or relationships (already up to date)'}</p>
          <h3 style={{ fontSize: 13 }}>Citations read from the summary</h3>
          {res.citations_added.length === 0 ? <p className="muted">None found{res.summary_status !== 'ok' ? ' (summary not machine-readable)' : ''}.</p> :
            res.citations_added.map((c) => (
              <div key={c.dst} className="cit"><div className="cit-h"><span className="k mono">{c.dst}</span> <span className="chip">{c.kind}</span> <span className="muted">p.{c.page}</span></div>
                <blockquote className="quote">“{c.snippet}”</blockquote></div>))}
          <p className="muted small">{res.recalls_linked.length} recall record(s) linked.</p>
          <button className="btn btn-primary" onClick={() => go('check', res.k)}>Investigate {res.k} <span className="arr">→</span></button>
        </section>
      )}
    </div>
  )
}

/* ---------------------------------------------------------------- method */
export function MethodView({ stats }) {
  return (
    <div className="method">
      <Head eyebrow="Method" title="How Forebear decides, and what it does not">
        Verdicts come from a small set of deterministic rules over Relate queries. They are documentation signals inside a stated
        scope, never safety findings.
      </Head>
      <section className="panel">
        <div className="panel-head"><h2>What the verdict means</h2></div>
        <ul>
          <li><span className="chip tone-alert">Design-related recall on file</span> the candidate has a design-related recall of its own.</li>
          <li><span className="chip tone-amber">Review lineage</span> a direct or grand-predicate has a design-related recall (Class I/II or not yet classified),
            the direct predicate has a Class I recall, or the candidate has a Class I recall.</li>
          <li><span className="chip tone-muted">Lineage not checkable</span> the candidate's own predicates could not be read, or every direct predicate link rests on
            uncertain evidence, so nothing was checked.</li>
          <li><span className="chip tone-calm">No design-recall signal</span> none of the above in the readable ancestry. Lower-severity signals are still listed. Not a safety finding.</li>
        </ul>
        <p className="muted small">"Design-related" means an openFDA root cause containing "design" but not "process". This is coarse. Lineage is limited
          to summaries that are online and machine-readable; gaps are reported, never filled in.</p>
      </section>
      <section className="panel">
        <div className="panel-head"><h2>How a thread is classified</h2></div>
        <ul>
          <li><span className="status status-confirmed"><span className="line" />Confirmed</span> a person confirmed the citation. Confirmations sent through the MCP client do not count.</li>
          <li><span className="status status-extracted"><span className="line" />Machine-extracted</span> read from the summary text, validated against openFDA, not yet reviewed.</li>
          <li><span className="status status-disputed"><span className="line" />Disputed</span> the cited device's FDA name is absent near the citation, it is in a different FDA panel,
            its K-number was corrected by the audit, or only an LLM labelled it a predicate.</li>
          <li><span className="status status-conditional"><span className="line" />Conditional</span> the extraction audit could not resolve the citation. Recalls reached only
            through it are marked conditional in assessments, the watchlist and recall reach.</li>
          <li><span className="status status-rejected"><span className="line" />Rejected</span> a reviewer removed it; it no longer counts in any lineage query.</li>
        </ul>
      </section>
      <section className="panel">
        <div className="panel-head"><h2>The optional agent</h2></div>
        <p className="lede" style={{ margin: 0 }}>An NVIDIA-hosted model can investigate a device by calling the same graph tools. Phase 3 evaluation found it unsuitable as the
          primary due-diligence workflow, so its findings appear only as history: never human-approved, never a verdict input, and unable to change lineage.</p>
      </section>
      <section className="panel">
        <div className="panel-head"><h2>How it uses Relate</h2></div>
        <ol>
          <li><b>Ingest.</b> openFDA 510(k), recall and enforcement records, and the text of each 510(k) summary PDF, with page-level evidence.</li>
          <li><b>Store.</b> One single-file store, <code>data/forebear.rl</code>: <code>(:Device)-[:CITES]-&gt;(:Device)</code>, <code>(:Device)-[:SUBJECT_OF]-&gt;(:Recall)</code>, saved <code>(:Assessment)</code> nodes.</li>
          <li><b>Query.</b> Variable-length Cypher walks the family tree both ways, joins recalls on every ancestor, compares dates.</li>
          <li><b>Update.</b> Ingest, review a citation, save an assessment: each is a graph write the next query reads.</li>
        </ol>
        {stats && <p className="muted small">Live: {stats.nodes.Device.toLocaleString('en-US')} devices, {stats.relationships.CITES.toLocaleString('en-US')} citation edges, {stats.nodes.Recall.toLocaleString('en-US')} recall records.</p>}
      </section>
    </div>
  )
}
