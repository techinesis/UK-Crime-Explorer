// AI chat panel (Phase 2). A collapsible fixed drawer on the right that talks to
// POST /api/chat over Server-Sent Events. The assistant can:
//   - Navigate: emit `set_filters` actions, applied here via the filter hook
//     (buffered and applied after the reply text has streamed in).
//   - Query / Explain: surface grounded numbers + methodology, with each tool
//     call shown as an audit badge under the message.
//
// Phase 2 adds: a stakeholder persona selector (Police / Examiner / Community,
// persisted to localStorage), per-persona starter prompts, real token streaming,
// and message polish (avatar, timestamps, copy, regenerate).
//
// Conversation/UI state is local component state (React useState); chat health
// lives in useChatHealth (TanStack Query). No extra state library.

import { useEffect, useRef, useState } from 'react'
import type { Level, MapRequest, Metric, SeverityBasis } from '../lib/types'
import type { FilterState } from '../hooks/useFilters'

// --- Wire types (mirror backend/api/chat.py) ------------------------------- //

type ChatActionPayload = Partial<MapRequest>

interface ChatAction {
  type: 'set_filters'
  payload: ChatActionPayload
}

interface ToolCallAudit {
  name: string
  args: Record<string, unknown>
  result_summary: string
}

/** SSE event shapes streamed by POST /api/chat. */
type StreamEvent =
  | { type: 'text'; text: string }
  | { type: 'tool_call'; name: string; args: Record<string, unknown>; result_summary: string }
  | { type: 'action'; action: ChatAction }
  | { type: 'done' }
  | { type: 'error'; error?: string }

interface ChatTurn {
  role: 'user' | 'assistant'
  content: string
  toolCalls?: ToolCallAudit[]
  ts: number
}

// --- Personas -------------------------------------------------------------- //

type Persona = 'police' | 'examiner' | 'community'

const PERSONAS: Array<{ id: Persona; label: string; blurb: string }> = [
  { id: 'police', label: 'Police', blurb: 'Operational, plain-language' },
  { id: 'examiner', label: 'Examiner', blurb: 'Rigorous, methodology-first' },
  { id: 'community', label: 'Community', blurb: 'Accessible, transparency-first' },
]

const STARTER_PROMPTS_BY_PERSONA: Record<Persona, string[]> = {
  police: [
    'Which five boroughs have the highest preventable harm?',
    'Where should we focus officers this month?',
    'How is preventability calculated?',
  ],
  examiner: [
    'Why use CCHI mean vs median severity?',
    'What is the preventability multiplier for Drugs, and why?',
    'How would the composite ranking change under median CCHI?',
  ],
  community: [
    'How does this affect my neighbourhood?',
    'Will this lead to over-policing?',
    'What does this tool not do?',
  ],
}

const PERSONA_STORAGE_KEY = 'crime-chat-persona'

function loadPersona(): Persona {
  try {
    const stored = localStorage.getItem(PERSONA_STORAGE_KEY)
    if (stored === 'police' || stored === 'examiner' || stored === 'community') return stored
  } catch {
    // localStorage unavailable (private mode etc.) — fall through to default
  }
  return 'police'
}

// --- Helpers --------------------------------------------------------------- //

/** Current dashboard FilterState → MapRequest (the API's snake_case shape). */
function toMapRequest(filters: FilterState): MapRequest {
  return {
    categories: filters.categories,
    tier: filters.tier,
    year: filters.year,
    months: filters.months,
    borough: filters.borough,
    level: filters.level,
    metric: filters.metric,
    severity_basis: filters.severityBasis,
  }
}

/**
 * set_filters action payload (Partial<MapRequest>, snake_case) → the filter-hook
 * patch (Partial<FilterState>, camelCase). Only the keys the assistant set are
 * carried through, so the rest of the user's selection is preserved.
 */
function actionToFilterPatch(payload: ChatActionPayload): Partial<FilterState> {
  const patch: Partial<FilterState> = {}
  if ('categories' in payload) patch.categories = payload.categories
  if ('tier' in payload) patch.tier = payload.tier
  if ('year' in payload) patch.year = payload.year ?? null
  if ('months' in payload) patch.months = payload.months
  if ('borough' in payload) patch.borough = payload.borough
  if ('level' in payload) patch.level = payload.level as Level
  if ('metric' in payload) patch.metric = payload.metric as Metric
  if ('severity_basis' in payload) patch.severityBasis = payload.severity_basis as SeverityBasis
  return patch
}

function formatTime(ts: number): string {
  return new Date(ts).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
}

// --- Component ------------------------------------------------------------- //

interface ChatPanelProps {
  open: boolean
  onClose: () => void
  filters: FilterState
  update: (patch: Partial<FilterState>) => void
}

export default function ChatPanel({ open, onClose, filters, update }: ChatPanelProps) {
  const [turns, setTurns] = useState<ChatTurn[]>([])
  const [input, setInput] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [isStreaming, setIsStreaming] = useState(false)
  const [persona, setPersona] = useState<Persona>(loadPersona)
  const scrollRef = useRef<HTMLDivElement>(null)

  // Persist persona choice across sessions.
  useEffect(() => {
    try {
      localStorage.setItem(PERSONA_STORAGE_KEY, persona)
    } catch {
      // ignore persistence failures
    }
  }, [persona])

  // Keep the latest message in view as text streams in.
  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: 'smooth' })
  }, [turns, isStreaming])

  /** Mutate the trailing assistant turn (the one currently streaming). */
  function updateStreamingTurn(updater: (turn: ChatTurn) => ChatTurn) {
    setTurns((prev) => {
      const next = [...prev]
      const last = next.length - 1
      if (last >= 0 && next[last].role === 'assistant') next[last] = updater(next[last])
      return next
    })
  }

  /** POST the conversation and consume the SSE stream into the trailing turn. */
  async function runStream(messages: Array<{ role: string; content: string }>) {
    setIsStreaming(true)
    setError(null)
    setTurns((prev) => [...prev, { role: 'assistant', content: '', toolCalls: [], ts: Date.now() }])

    const bufferedActions: ChatAction[] = []

    const handle = (event: StreamEvent) => {
      switch (event.type) {
        case 'text':
          updateStreamingTurn((t) => ({ ...t, content: t.content + event.text }))
          break
        case 'tool_call':
          updateStreamingTurn((t) => ({
            ...t,
            toolCalls: [
              ...(t.toolCalls ?? []),
              { name: event.name, args: event.args, result_summary: event.result_summary },
            ],
          }))
          break
        case 'action':
          if (event.action) bufferedActions.push(event.action)
          break
        case 'done':
          // Apply navigation actions only after the reply text has rendered.
          for (const action of bufferedActions) {
            if (action.type === 'set_filters') update(actionToFilterPatch(action.payload))
          }
          bufferedActions.length = 0
          break
        case 'error':
          setError(event.error || 'The assistant hit an error.')
          break
      }
    }

    try {
      const res = await fetch('/api/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ messages, filters: toMapRequest(filters), persona }),
      })

      if (!res.ok || !res.body) {
        // Pre-flight failure (503/400/502) arrives as plain JSON, not a stream.
        let message = `Chat failed: ${res.status}`
        try {
          const body = (await res.json()) as { error?: string }
          if (body.error) message = body.error
        } catch {
          // keep the status-code message
        }
        throw new Error(message)
      }

      const reader = res.body.getReader()
      const decoder = new TextDecoder()
      let buffer = ''

      for (;;) {
        const { done, value } = await reader.read()
        if (done) break
        buffer += decoder.decode(value, { stream: true })

        // SSE frames are separated by a blank line; keep any trailing partial.
        const frames = buffer.split('\n\n')
        buffer = frames.pop() ?? ''
        for (const frame of frames) {
          const line = frame.trim()
          if (!line.startsWith('data:')) continue
          const payload = line.slice(line.indexOf('data:') + 5).trim()
          if (!payload) continue
          try {
            handle(JSON.parse(payload) as StreamEvent)
          } catch {
            // ignore an unparseable frame rather than abort the whole stream
          }
        }
      }
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Something went wrong.')
      // Drop the placeholder assistant turn if it never received any content.
      setTurns((prev) => {
        const next = [...prev]
        const last = next.length - 1
        if (
          last >= 0 &&
          next[last].role === 'assistant' &&
          !next[last].content &&
          !(next[last].toolCalls?.length)
        ) {
          next.pop()
        }
        return next
      })
    } finally {
      setIsStreaming(false)
    }
  }

  function submit(text: string) {
    const trimmed = text.trim()
    if (!trimmed || isStreaming) return

    const userTurn: ChatTurn = { role: 'user', content: trimmed, ts: Date.now() }
    const history = [...turns, userTurn]
    setTurns(history)
    setInput('')
    runStream(history.map((t) => ({ role: t.role, content: t.content })))
  }

  function regenerate() {
    if (isStreaming) return
    const lastUserIndex = turns.map((t) => t.role).lastIndexOf('user')
    if (lastUserIndex === -1) return
    const history = turns.slice(0, lastUserIndex + 1)
    setTurns(history) // drop the previous assistant answer
    runStream(history.map((t) => ({ role: t.role, content: t.content })))
  }

  function clearChat() {
    if (isStreaming) return
    setTurns([])
    setError(null)
  }

  const starters = STARTER_PROMPTS_BY_PERSONA[persona]
  const lastAssistantIndex = turns.map((t) => t.role).lastIndexOf('assistant')

  return (
    <div
      className={`fixed right-0 top-0 z-40 flex h-screen w-[360px] flex-col border-l border-border bg-card shadow-xl transition-transform duration-200 ${
        open ? 'translate-x-0' : 'translate-x-full'
      }`}
      aria-hidden={!open}
    >
      {/* Header */}
      <div className="flex items-center justify-between gap-2 border-b border-border px-4 py-3">
        <div className="min-w-0">
          <h2 className="text-sm font-semibold text-fg">Assistant</h2>
          <p className="truncate text-[11px] text-muted">Grounded in the dashboard data</p>
        </div>
        <div className="flex items-center gap-1">
          {turns.length > 0 && (
            <button
              onClick={clearChat}
              disabled={isStreaming}
              className="rounded px-2 py-1 text-[11px] text-muted hover:bg-surface hover:text-fg disabled:opacity-40"
            >
              Clear
            </button>
          )}
          <button
            onClick={onClose}
            aria-label="Collapse assistant panel"
            className="rounded px-2 py-1 text-muted hover:bg-surface hover:text-fg"
          >
            ✕
          </button>
        </div>
      </div>

      {/* Persona selector */}
      <div className="flex items-center gap-2 border-b border-border px-4 py-2">
        <label htmlFor="chat-persona" className="text-[11px] text-muted">
          Viewing as
        </label>
        <select
          id="chat-persona"
          value={persona}
          onChange={(e) => setPersona(e.target.value as Persona)}
          className="flex-1 rounded-md border border-border bg-surface px-2 py-1 text-xs text-fg focus:border-accent focus:outline-none"
        >
          {PERSONAS.map((p) => (
            <option key={p.id} value={p.id}>
              {p.label} — {p.blurb}
            </option>
          ))}
        </select>
      </div>

      {/* Messages */}
      <div ref={scrollRef} className="flex-1 space-y-3 overflow-y-auto px-4 py-3">
        {turns.length === 0 && (
          <div className="space-y-3">
            <p className="text-xs text-muted">
              Ask about London crime demand, filter the map, or ask how the metrics are built.
            </p>
            <div className="space-y-2">
              {starters.map((prompt) => (
                <button
                  key={prompt}
                  onClick={() => submit(prompt)}
                  className="block w-full rounded-md border border-border bg-surface px-3 py-2 text-left text-xs text-fg hover:border-accent"
                >
                  {prompt}
                </button>
              ))}
            </div>
          </div>
        )}

        {turns.map((turn, index) => (
          <Message
            key={index}
            turn={turn}
            streaming={isStreaming && index === turns.length - 1 && turn.role === 'assistant'}
            canRegenerate={!isStreaming && index === lastAssistantIndex && !!turn.content}
            onRegenerate={regenerate}
          />
        ))}

        {error && (
          <div className="rounded-md bg-red-900/20 px-3 py-2 text-xs text-red-400">{error}</div>
        )}
      </div>

      {/* Input */}
      <form
        className="flex items-end gap-2 border-t border-border px-3 py-3"
        onSubmit={(e) => {
          e.preventDefault()
          submit(input)
        }}
      >
        <textarea
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
              e.preventDefault()
              submit(input)
            }
          }}
          rows={1}
          placeholder="Ask the assistant…"
          className="max-h-28 min-h-[2.25rem] flex-1 resize-none rounded-md border border-border bg-surface px-3 py-2 text-xs text-fg placeholder:text-muted focus:border-accent focus:outline-none"
        />
        <button
          type="submit"
          disabled={isStreaming || !input.trim()}
          className="rounded-md bg-accent px-3 py-2 text-xs font-medium text-white disabled:opacity-40"
        >
          Send
        </button>
      </form>
    </div>
  )
}

interface MessageProps {
  turn: ChatTurn
  streaming: boolean
  canRegenerate: boolean
  onRegenerate: () => void
}

function Message({ turn, streaming, canRegenerate, onRegenerate }: MessageProps) {
  const isUser = turn.role === 'user'
  const [copied, setCopied] = useState(false)

  function copy() {
    navigator.clipboard?.writeText(turn.content).then(
      () => {
        setCopied(true)
        setTimeout(() => setCopied(false), 1500)
      },
      () => {
        /* clipboard blocked — no-op */
      },
    )
  }

  return (
    <div className={isUser ? 'flex justify-end' : 'flex items-start justify-start gap-2'}>
      {!isUser && (
        <span
          aria-hidden
          className="mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-surface text-xs"
        >
          🤖
        </span>
      )}

      <div
        className={`max-w-[85%] rounded-lg px-3 py-2 text-xs ${
          isUser ? 'bg-accent text-white' : 'bg-surface text-fg'
        }`}
      >
        {streaming && !turn.content ? (
          <span className="flex items-center gap-2 text-muted">
            <span className="h-2 w-2 animate-pulse rounded-full bg-accent" />
            Thinking…
          </span>
        ) : (
          <p className="whitespace-pre-wrap">
            {turn.content}
            {streaming && <span className="ml-0.5 animate-pulse">▍</span>}
          </p>
        )}

        {turn.toolCalls && turn.toolCalls.length > 0 && (
          <div className="mt-2 flex flex-wrap gap-1 border-t border-border/50 pt-2">
            {turn.toolCalls.map((call, i) => (
              <span
                key={i}
                title={call.result_summary}
                className="rounded-full bg-card px-2 py-0.5 text-[10px] text-muted"
              >
                🔧 {call.name} · {call.result_summary}
              </span>
            ))}
          </div>
        )}

        <div className="mt-1.5 flex items-center gap-2 text-[9px] text-muted">
          <span>{formatTime(turn.ts)}</span>
          {!isUser && !streaming && turn.content && (
            <button onClick={copy} className="hover:text-fg" title="Copy reply">
              {copied ? '✓ Copied' : '📋 Copy'}
            </button>
          )}
          {canRegenerate && (
            <button onClick={onRegenerate} className="hover:text-fg" title="Regenerate reply">
              🔄 Regenerate
            </button>
          )}
        </div>
      </div>
    </div>
  )
}
