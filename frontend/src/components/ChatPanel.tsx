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
import type {
  KeyboardEvent as ReactKeyboardEvent,
  PointerEvent as ReactPointerEvent,
} from 'react'
import type { Level, MapRequest, Metric, SeverityBasis } from '../lib/types'
import { CITIES } from '../hooks/useFilters'
import type { FilterState } from '../hooks/useFilters'
import ChatMarkdown from './ChatMarkdown'

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

// --- Panel sizing ------------------------------------------------------------ //

/** Default (and minimum) drawer width; matches the original fixed 360px. */
const MIN_PANEL_WIDTH = 360

/** Keyboard resize step for the drag handle (arrow keys). */
const PANEL_RESIZE_STEP = 24

/** The drawer can be dragged out to at most a third of the viewport. */
function clampPanelWidth(width: number): number {
  const max = Math.max(MIN_PANEL_WIDTH, Math.floor(window.innerWidth / 3))
  return Math.min(Math.max(width, MIN_PANEL_WIDTH), max)
}

function loadPersona(): Persona {
  try {
    const stored = localStorage.getItem(PERSONA_STORAGE_KEY)
    if (stored === 'police' || stored === 'examiner' || stored === 'community') return stored
  } catch {
    // localStorage unavailable (private mode etc.) — fall through to default
  }
  return 'police'
}

// --- Transcript persistence (sessionStorage, per persona) ------------------ //
// sessionStorage (NOT localStorage): the transcript survives a tab reload but is
// discarded when the tab closes. One key per persona keeps voices isolated.

const TRANSCRIPT_SCHEMA_VERSION = 1
const turnsKey = (persona: Persona): string => `crime-chat-turns:${persona}`

interface StoredTranscript {
  schema_version: number
  persona: Persona
  turns: ChatTurn[]
  updated_at?: string
}

/** Read a persona's transcript from sessionStorage. Any error, a missing entry,
 * or a schema-version mismatch (stale tab from a prior deploy) yields []. */
function loadTurns(persona: Persona): ChatTurn[] {
  try {
    const raw = sessionStorage.getItem(turnsKey(persona))
    if (!raw) return []
    const parsed = JSON.parse(raw) as Partial<StoredTranscript>
    if (parsed?.schema_version !== TRANSCRIPT_SCHEMA_VERSION) return []
    return Array.isArray(parsed.turns) ? (parsed.turns as ChatTurn[]) : []
  } catch {
    return []
  }
}

/** Persist a persona's transcript. An empty transcript removes the key (so a
 * cleared persona leaves nothing behind). Returns false on quota/unavailability
 * so the caller can surface a non-fatal warning. */
function saveTurns(persona: Persona, turns: ChatTurn[]): boolean {
  try {
    if (turns.length === 0) {
      sessionStorage.removeItem(turnsKey(persona))
    } else {
      const payload: StoredTranscript = {
        schema_version: TRANSCRIPT_SCHEMA_VERSION,
        persona,
        turns,
        updated_at: new Date().toISOString(),
      }
      sessionStorage.setItem(turnsKey(persona), JSON.stringify(payload))
    }
    return true
  } catch {
    return false
  }
}

// --- Helpers --------------------------------------------------------------- //

/** Current dashboard FilterState → MapRequest (the API's snake_case shape). */
function toMapRequest(filters: FilterState): MapRequest {
  return {
    city: filters.city,
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
  if ('city' in payload && payload.city) {
    // Backend city values are lowercase; the city selector uses the Title-case
    // CITIES entries. Resolve case-insensitively, ignore anything unknown.
    const canonical = CITIES.find((c) => c.toLowerCase() === String(payload.city).toLowerCase())
    if (canonical) patch.city = canonical
  }
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
  const [turns, setTurns] = useState<ChatTurn[]>(() => loadTurns(loadPersona()))
  const [input, setInput] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [isStreaming, setIsStreaming] = useState(false)
  const [persona, setPersona] = useState<Persona>(loadPersona)
  const [panelWidth, setPanelWidth] = useState(MIN_PANEL_WIDTH)
  // "Continuing previous conversation" hint: shown when a non-empty transcript is
  // hydrated (on mount or persona switch), cleared once the user sends a message.
  const [showContinued, setShowContinued] = useState<boolean>(() => turns.length > 0)
  // Sticky for the session once a sessionStorage write fails (quota/unavailable).
  const [persistFailed, setPersistFailed] = useState(false)
  const scrollRef = useRef<HTMLDivElement>(null)

  // Refs let the persist/switch effects read the latest persona & turns without
  // widening their dependency arrays — which is what keeps a persona switch from
  // writing the outgoing transcript under the incoming persona's key.
  const personaRef = useRef(persona)
  personaRef.current = persona
  const prevPersonaRef = useRef(persona)
  const turnsRef = useRef(turns)
  turnsRef.current = turns

  // Persist persona choice across sessions.
  useEffect(() => {
    try {
      localStorage.setItem(PERSONA_STORAGE_KEY, persona)
    } catch {
      // ignore persistence failures
    }
  }, [persona])

  // Persist the transcript on every change, under the *active* persona's key.
  // Depends on [turns] only: on a persona switch the turns are unchanged for one
  // render, so this never writes the old transcript under the new persona's key.
  useEffect(() => {
    if (!saveTurns(personaRef.current, turns)) setPersistFailed(true)
  }, [turns])

  // On a real persona switch, stash the outgoing persona's transcript under its
  // own key, then hydrate the incoming persona's transcript. Uses refs so it can
  // run on [persona] alone and still see the (not-yet-rehydrated) outgoing turns.
  useEffect(() => {
    const prev = prevPersonaRef.current
    if (prev === persona) return // initial mount, or no actual change
    saveTurns(prev, turnsRef.current)
    const loaded = loadTurns(persona)
    setTurns(loaded)
    setShowContinued(loaded.length > 0)
    setError(null)
    prevPersonaRef.current = persona
  }, [persona])

  // Re-clamp the drawer if the window shrinks below its ⅓-viewport budget.
  useEffect(() => {
    const onWindowResize = () => setPanelWidth((w) => clampPanelWidth(w))
    window.addEventListener('resize', onWindowResize)
    return () => window.removeEventListener('resize', onWindowResize)
  }, [])

  /** Drag the panel's left edge: width follows the pointer, clamped to [360px, ⅓ viewport]. */
  function startPanelResize(event: ReactPointerEvent<HTMLDivElement>) {
    event.preventDefault()
    const onPointerMove = (e: PointerEvent) => {
      setPanelWidth(clampPanelWidth(window.innerWidth - e.clientX))
    }
    const stop = () => {
      window.removeEventListener('pointermove', onPointerMove)
      window.removeEventListener('pointerup', stop)
      window.removeEventListener('pointercancel', stop)
      document.body.style.cursor = ''
      document.body.style.userSelect = ''
    }
    window.addEventListener('pointermove', onPointerMove)
    window.addEventListener('pointerup', stop)
    window.addEventListener('pointercancel', stop)
    // Keep the resize cursor (and kill text selection) while the pointer roams the page.
    document.body.style.cursor = 'col-resize'
    document.body.style.userSelect = 'none'
  }

  function handleResizeKeyDown(event: ReactKeyboardEvent<HTMLDivElement>) {
    if (event.key !== 'ArrowLeft' && event.key !== 'ArrowRight') return
    event.preventDefault()
    const delta = event.key === 'ArrowLeft' ? PANEL_RESIZE_STEP : -PANEL_RESIZE_STEP
    setPanelWidth((w) => clampPanelWidth(w + delta))
  }

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
    setShowContinued(false) // a new message means we're no longer "continuing"
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
    setShowContinued(false)
    try {
      sessionStorage.removeItem(turnsKey(persona))
    } catch {
      // ignore — the empty-transcript persist effect also clears the key
    }
  }

  const starters = STARTER_PROMPTS_BY_PERSONA[persona]
  const lastAssistantIndex = turns.map((t) => t.role).lastIndexOf('assistant')

  return (
    <div
      className={`fixed right-0 top-0 z-40 flex h-screen flex-col border-l border-border bg-card shadow-xl transition-transform duration-200 ${
        open ? 'translate-x-0' : 'translate-x-full'
      }`}
      style={{ width: panelWidth }}
      aria-hidden={!open}
    >
      {/* Resize handle: drag the left edge to widen the drawer (up to ⅓ of the page). */}
      <div
        role="separator"
        aria-orientation="vertical"
        aria-label="Resize assistant panel"
        aria-valuemin={MIN_PANEL_WIDTH}
        aria-valuemax={Math.max(MIN_PANEL_WIDTH, Math.floor(window.innerWidth / 3))}
        aria-valuenow={Math.round(panelWidth)}
        tabIndex={0}
        onPointerDown={startPanelResize}
        onKeyDown={handleResizeKeyDown}
        className="absolute left-0 top-0 z-10 h-full w-1.5 cursor-col-resize hover:bg-accent/40 focus-visible:bg-accent/40 focus-visible:outline-none"
      />

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
        {persistFailed && (
          <p className="text-[11px] text-muted">History persistence unavailable for this session.</p>
        )}

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

        {showContinued && turns.length > 0 && (
          <p className="text-[11px] text-muted">Continuing previous conversation</p>
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
        ) : isUser ? (
          // User messages stay plain text — `*test*` keeps its literal asterisks.
          <p className="whitespace-pre-wrap">{turn.content}</p>
        ) : (
          <div>
            <ChatMarkdown content={turn.content} />
            {streaming && <span className="ml-0.5 animate-pulse">▍</span>}
          </div>
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
