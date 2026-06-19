import { useState } from 'react'

// Read a POST SSE stream (EventSource only supports GET) and dispatch each event.
async function streamSSE(url, body, onEvent) {
  const res = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  const reader = res.body.getReader()
  const decoder = new TextDecoder()
  let buf = ''
  for (;;) {
    const { done, value } = await reader.read()
    if (done) break
    buf += decoder.decode(value, { stream: true })
    const parts = buf.split('\n\n')
    buf = parts.pop()
    for (const part of parts) {
      let event = null
      let data = ''
      for (const line of part.split('\n')) {
        if (line.startsWith('event:')) event = line.slice(6).trim()
        else if (line.startsWith('data:')) data += line.slice(5).trim()
      }
      if (event) onEvent(event, data ? JSON.parse(data) : {})
    }
  }
}

const NODE_LABELS = {
  triage: 'Triage',
  investigate_services: 'Investigate: services',
  investigate_metrics: 'Investigate: metrics',
  investigate_logs: 'Investigate: logs',
  diagnose: 'Diagnose (RAG)',
  propose: 'Propose fix',
  gate: 'Approval gate',
  execute: 'Execute',
  verify: 'Verify',
}

function EventCard({ event, data }) {
  if (event === 'triage')
    return (
      <Card title="Triage" tone="step">
        <b>{data.incident_type}</b> on <code>{data.target_service}</code> ({data.severity})
      </Card>
    )
  if (event.startsWith('investigate_')) {
    const f = (data.findings || [])[0] || {}
    return (
      <Card title={NODE_LABELS[event]} tone="step">
        <pre>{(f.summary || '').slice(0, 600)}</pre>
      </Card>
    )
  }
  if (event === 'diagnose')
    return (
      <Card title="Diagnose (RAG grounded)" tone="diag">
        <pre>{data.diagnosis}</pre>
        {data.runbooks?.length > 0 && (
          <div className="chips">
            {data.runbooks.map((r) => (
              <span className="chip" key={r}>{r}</span>
            ))}
          </div>
        )}
      </Card>
    )
  if (event === 'propose')
    return (
      <Card title="Proposed fix (not executed)" tone="step">
        <pre>{data.proposed_fix}</pre>
      </Card>
    )
  if (event === 'execute')
    return (
      <Card title="Execute" tone="exec">
        <b>{data.execution?.status}</b> {data.execution?.action} <pre>{data.execution?.result}</pre>
      </Card>
    )
  if (event === 'verify') {
    const v = data.verification || {}
    return (
      <Card title="Verify" tone={v.recovered ? 'ok' : 'warn'}>
        {v.recovered ? '✓ Recovered' : '✗ Not recovered'} &middot; MTTR {v.mttr_seconds}s
      </Card>
    )
  }
  if (event === 'error')
    return <Card title="Error" tone="warn">{data.message}</Card>
  return null
}

function Card({ title, tone, children }) {
  return (
    <div className={`card ${tone}`}>
      <div className="card-title">{title}</div>
      <div className="card-body">{children}</div>
    </div>
  )
}

export default function App() {
  const [trigger, setTrigger] = useState('demoapp service is down, connection refused on 8090')
  const [events, setEvents] = useState([])
  const [incidentId, setIncidentId] = useState(null)
  const [awaiting, setAwaiting] = useState(null)
  const [cost, setCost] = useState(null)
  const [running, setRunning] = useState(false)

  const handle = (event, data) => {
    if (event === 'incident') setIncidentId(data.incident_id)
    else if (event === 'awaiting_approval') setAwaiting(data)
    else if (event === 'cost') setCost(data)
    else if (event === 'done') setRunning(false)
    setEvents((prev) => [...prev, { event, data }])
  }

  const start = async () => {
    setEvents([])
    setAwaiting(null)
    setCost(null)
    setIncidentId(null)
    setRunning(true)
    try {
      await streamSSE('/api/incidents', { trigger }, handle)
    } catch (e) {
      handle('error', { message: String(e) })
      setRunning(false)
    }
  }

  const decide = async (approved) => {
    setAwaiting(null)
    setRunning(true)
    try {
      await streamSSE(`/api/incidents/${incidentId}/approve`, { approved, approver: 'operator' }, handle)
    } catch (e) {
      handle('error', { message: String(e) })
      setRunning(false)
    }
  }

  return (
    <div className="app">
      <header>
        <h1>Agentic SRE Copilot</h1>
        <span className="sub">multi-agent incident diagnosis and remediation</span>
      </header>

      <div className="controls">
        <input value={trigger} onChange={(e) => setTrigger(e.target.value)} placeholder="Describe the alert" />
        <button onClick={start} disabled={running}>
          {running ? 'Running…' : 'Trigger incident'}
        </button>
        {cost && <span className="cost">${cost.usd?.toFixed?.(5)} &middot; {cost.input_tokens}/{cost.output_tokens} tok</span>}
      </div>

      {awaiting && (
        <div className="approval">
          <div className="card-title">Human approval required</div>
          <pre>{awaiting.proposed_fix}</pre>
          <div className="row">
            <button className="approve" onClick={() => decide(true)}>Approve</button>
            <button className="reject" onClick={() => decide(false)}>Reject</button>
          </div>
        </div>
      )}

      <div className="timeline">
        {events.map((e, i) => (
          <EventCard key={i} event={e.event} data={e.data} />
        ))}
      </div>
    </div>
  )
}
