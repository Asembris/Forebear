import React, { useEffect, useState } from 'react'
import { api } from './api.js'

const VCLS = { DESIGN_RECALL_ON_FILE: 'v-avoid', REVIEW_LINEAGE: 'v-review', INSUFFICIENT_LINEAGE: 'v-unknown', NO_DESIGN_RECALL_SIGNAL: 'v-clear' }

export function CompareView({ initial, go }) {
  const [text, setText] = useState(initial ? initial : 'K200480 K113053 K233643 K143677')
  const [rows, setRows] = useState(null)
  const [err, setErr] = useState(null)
  const run = () => {
    const ks = [...new Set(text.toUpperCase().match(/K\d{6}/g) || [])].slice(0, 8)
    if (!ks.length) { setErr('Enter one or more K-numbers'); return }
    setErr(null); setRows(null)
    api.compare(ks).then(setRows).catch((e) => setErr(e.message))
  }
  useEffect(() => { run() }, [])
  return (
    <div>
      <section className="card">
        <h2>Compare candidate predicates</h2>
        <p className="hint">FDA's draft guidance suggests documenting, for each candidate predicate, how it meets the
          selection best practices. This table covers the recall practice: each candidate's own recalls and those in its
          ancestry, computed live from the graph.</p>
        <div className="row-in">
          <input value={text} onChange={(e) => setText(e.target.value)} onKeyDown={(e) => e.key === 'Enter' && run()} />
          <button onClick={run}>Compare</button>
        </div>
        {err && <div className="err">{err}</div>}
      </section>
      {rows && (
        <section className="card">
          <table className="tbl">
            <thead><tr><th>Candidate</th><th>Cleared</th><th>Verdict</th><th>Own recalls<br /><small>(design)</small></th>
              <th>Flagged ancestors<br /><small>gen 1-2, design</small></th><th>Ancestors<br /><small>(unread)</small></th><th>Top signal</th></tr></thead>
            <tbody>{rows.map((r) => r.found ? (
              <tr key={r.k} onClick={() => go('check', r.k)} className="click">
                <td><b>{r.k}</b><div className="muted">{r.name}</div><div className="muted">{r.applicant}</div></td>
                <td>{r.decision_date}</td>
                <td><span className={'pill ' + VCLS[r.verdict]}>{r.verdict.replaceAll('_', ' ')}</span></td>
                <td>{r.own_recalls} <small>({r.own_design_recalls})</small></td>
                <td>{r.flagged_ancestors_gen12}</td>
                <td>{r.ancestors} <small>({r.lineage_unknown})</small></td>
                <td className="small">{r.top_signal || '—'}</td>
              </tr>) : (
              <tr key={r.k}><td><b>{r.k}</b></td><td colSpan={6} className="muted">Not in the graph. <a onClick={() => go('ingest', r.k)}>Ingest it →</a></td></tr>))}
            </tbody>
          </table>
        </section>
      )}
    </div>
  )
}

export function ReachView({ initial, go }) {
  const [ev, setEv] = useState(initial || '88058,88071')
  const [data, setData] = useState(null)
  const [err, setErr] = useState(null)
  const run = (e = ev) => { setErr(null); setData(null); api.recallEvent(e).then(setData).catch((x) => setErr(x.message)) }
  useEffect(() => { run(initial || '88058,88071') }, [initial])
  const after = data?.descendants.filter((d) => d.after_recall) || []
  const before = data?.descendants.filter((d) => !d.after_recall) || []
  return (
    <div>
      <section className="card">
        <h2>Recall reach</h2>
        <p className="hint">Pick an FDA recall event (or several). Forebear finds every device it covers, then every later clearance that cites one
          of them as a predicate, up to three generations, and splits them by whether they were cleared after the recall began.</p>
        <div className="row-in">
          <input value={ev} onChange={(e) => setEv(e.target.value)} onKeyDown={(e) => e.key === 'Enter' && run()} />
          <button onClick={() => run()}>Trace</button>
        </div>
        <div className="muted small">Examples: 88058,88071 (Philips PE-PUR foam recall, June 2021, which openFDA files as two events) · 86646 · 84406. Separate several events with commas.</div>
        {err && <div className="err">{err}</div>}
      </section>
      {data && (
        <>
          <section className="card">
            <div className="bigstats">
              <div><b>{data.recalled.length}</b><span>clearances named in recall event(s) {data.event}</span></div>
              <div><b>{data.descendants.length}</b><span>later devices descending from them</span></div>
              <div className="hot"><b>{after.length}</b><span>cleared <i>after</i> the recall began ({data.initiated})</span></div>
            </div>
            <div className="chips">{data.recalled.map((r) => <button key={r.k} className="chip" onClick={() => go('check', r.k)}>{r.k} · {r.name}</button>)}</div>
          </section>
          <section className="card">
            <h2>Descendants cleared after the recall began</h2>
            <DescTable rows={after} go={go} />
            <h2 style={{ marginTop: 18 }}>Descendants cleared before</h2>
            <DescTable rows={before} go={go} />
          </section>
        </>
      )}
    </div>
  )
}

function DescTable({ rows, go }) {
  if (!rows.length) return <p className="muted">None.</p>
  return (
    <table className="tbl">
      <thead><tr><th>Device</th><th>Applicant</th><th>Cleared</th><th>Recall began<br /><small>on its lineage</small></th><th>Generations</th><th>Descends from</th></tr></thead>
      <tbody>{rows.map((d) => (
        <tr key={d.k} className="click" onClick={() => go('check', d.k)}>
          <td><b>{d.k}</b> <span className="muted">{d.name}</span></td><td>{d.applicant}</td><td>{d.decision_date}</td><td>{d.recall_started}</td>
          <td>{d.gen === 1 ? 'direct predicate' : `${d.gen} generations`}</td><td className="small">{d.via.join(', ')}</td>
        </tr>))}</tbody>
    </table>
  )
}

export function WatchlistView({ go }) {
  const [data, setData] = useState(null)
  const [err, setErr] = useState(null)
  const [direct, setDirect] = useState(false)
  useEffect(() => { api.watchlist().then(setData).catch((e) => setErr(e.message)) }, [])
  const rows = (data?.rows || []).filter((r) => !direct || r.min_gen === 1)
  return (
    <div>
      <section className="card">
        <h2>Watchlist: clearances that cited an already-recalled lineage</h2>
        <p className="hint">Devices cleared <b>after</b> a design-related recall had already started on their predicate or
          grand-predicate (by clearance date; the received date is shown too, because predicates are chosen
          when the submission is prepared). This is close to, but not the same as, the JAMA study's measure (Class I predicate recalls, any cause). It is a question to ask, not a finding: the recall may
          have been fixed, or limited to lots or software versions.</p>
        {err && <div className="err">{err}</div>}
        {data && <div className="bigstats">
          <div><b>{data.count}</b><span>clearances in the dataset match</span></div>
          <div className="hot"><b>{data.direct}</b><span>cite a directly recalled predicate</span></div>
          <div><label><input type="checkbox" checked={direct} onChange={(e) => setDirect(e.target.checked)} /> show direct only</label></div>
        </div>}
      </section>
      {data && <section className="card">
        <table className="tbl">
          <thead><tr><th>Cleared device</th><th>Received / cleared</th><th>Recalled ancestor</th><th>Recall examples</th></tr></thead>
          <tbody>{rows.map((r) => (
            <tr key={r.k} className="click" onClick={() => go('check', r.k)}>
              <td><b>{r.k}</b><div className="muted">{r.name}</div><div className="muted">{r.applicant}</div></td>
              <td>{r.received_date || '?'}<div className="muted">{r.decision_date}</div></td>
              <td>{r.ancestors.join(', ')}<div className="muted">{r.min_gen === 1 ? 'direct predicate' : 'grand-predicate'}</div></td>
              <td className="small">{r.recalls.slice(0, 2).map((x) => <div key={x.recall_id}>{x.recall_id} · {x.classification} · {x.root_cause} · {x.initiated}</div>)}</td>
            </tr>))}</tbody>
        </table>
      </section>}
    </div>
  )
}

export function IngestView({ initial, go, onChanged }) {
  const [k, setK] = useState(initial || '')
  const [busy, setBusy] = useState(false)
  const [res, setRes] = useState(null)
  const [err, setErr] = useState(null)
  const run = async () => {
    setBusy(true); setErr(null); setRes(null)
    try { const r = await api.ingest(k); setRes(r); onChanged && onChanged() } catch (e) { setErr(e.message) } finally { setBusy(false) }
  }
  const delta = (a, b) => Object.keys({ ...a, ...b }).map((key) => [key, (b[key] || 0) - (a[key] || 0)]).filter(([, d]) => d)
  return (
    <div>
      <section className="card">
        <h2>Add a clearance (incremental update)</h2>
        <p className="hint">Enter any 510(k) number. Forebear fetches its openFDA record and its 510(k) summary PDF live, extracts the
          predicates it cites, validates them against openFDA, links recalls, and MERGEs everything into the Relate store.
          Use it for a new clearance, or on an ancestor whose summary was not read, to extend a lineage by one generation.</p>
        <div className="row-in">
          <input value={k} placeholder="K-number, e.g. K241135" onChange={(e) => setK(e.target.value)} onKeyDown={(e) => e.key === 'Enter' && run()} />
          <button disabled={busy} onClick={run}>{busy ? 'Fetching from FDA…' : 'Ingest'}</button>
        </div>
        {err && <div className="err">{err}</div>}
      </section>
      {res && (
        <section className="card">
          <h2>{res.k}: {res.was_present ? (res.lineage_was_known ? 're-read' : 'lineage extended') : 'added to the graph'}</h2>
          <p>Summary: <b>{res.summary_status}</b>{res.summary_url && <> · <a href={res.summary_url} target="_blank" rel="noreferrer">PDF ↗</a></>}</p>
          <p>Graph change: {delta(res.graph_before, res.graph_after).concat(delta(res.rels_before, res.rels_after))
            .map(([key, d]) => `${d > 0 ? '+' : ''}${d} ${key}`).join(' · ') || 'no new nodes or relationships (already up to date)'}</p>
          <h3>Citations read from the summary</h3>
          {res.citations_added.length === 0 ? <p className="muted">None found{res.summary_status !== 'ok' ? ' (summary not machine-readable)' : ''}.</p> :
            res.citations_added.map((c) => (
              <div key={c.dst} className="cit"><div className="cit-h"><b>{c.dst}</b> <span className={'pill ' + c.kind}>{c.kind}</span> p.{c.page}</div><q>{c.snippet}</q></div>))}
          <p className="muted">{res.recalls_linked.length} recall record(s) linked · extraction {JSON.stringify(res.extraction)}</p>
          <button onClick={() => go('check', res.k)}>Run predicate check on {res.k} →</button>
        </section>
      )}
    </div>
  )
}

export function AboutView({ stats }) {
  return (
    <div className="about">
      <section className="card">
        <h2>How Forebear uses Relate</h2>
        <ol>
          <li><b>Ingest.</b> openFDA 510(k) records, recall and enforcement records, and the text of each 510(k) summary PDF.
            Predicate K-numbers are extracted with page-level evidence and validated (they must exist and pre-date the citing device).</li>
          <li><b>Store.</b> One Relate single-file store (<code>data/forebear.rl</code>): <code>(:Device)-[:CITES]-&gt;(:Device)</code>,
            <code>(:Device)-[:SUBJECT_OF]-&gt;(:Recall)</code>, product codes, companies, and saved <code>(:Assessment)</code> nodes.</li>
          <li><b>Query.</b> Variable-length Cypher walks the predicate family tree in both directions, joins recalls on every
            ancestor, and compares recall dates with clearance dates.</li>
          <li><b>Update.</b> Ingest a clearance live, confirm or reject an extracted citation, let an LLM label an ambiguous mention,
            save an assessment. All of these are graph writes that change the next query's answer.</li>
          <li><b>Agents.</b> The same store is exposed to coding/analysis agents via MCP (see README).</li>
        </ol>
        {stats && <pre className="pre">{JSON.stringify(stats, null, 1)}</pre>}
      </section>
      <section className="card">
        <h2>What the verdict means</h2>
        <ul>
          <li><span className="pill v-avoid">DESIGN RECALL ON FILE</span> the candidate has a design-related recall of its own.</li>
          <li><span className="pill v-review">REVIEW LINEAGE</span> a direct or grand-predicate has a design-related recall (Class I/II or
            not yet classified), the direct predicate has a Class I recall, or the candidate has a Class I recall.</li>
          <li><span className="pill v-unknown">INSUFFICIENT LINEAGE</span> the candidate's own predicates could not be read, so nothing was checked.</li>
          <li><span className="pill v-clear">NO DESIGN-RECALL SIGNAL</span> none of the above in the readable ancestry; lower-severity
            signals are still listed. Not a safety finding.</li>
        </ul>
        <p className="muted">"Design-related" = openFDA root cause containing "design" but not "process": Device Design, Software
          design, Software Design Change, Component design/selection, Labeling design. Excluded: Process design, Software design
          (manufacturing process). This is coarse. Lineage is limited to summaries that are
          online and machine-readable; gaps are reported, never filled in.</p>
      </section>
    </div>
  )
}
