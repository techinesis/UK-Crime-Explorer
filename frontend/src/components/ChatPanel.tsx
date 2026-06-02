// AI chat panel (Phase 1, Police persona). A collapsible fixed drawer on the
// right that talks to POST /api/chat. The assistant can:
//   - Navigate: emit `set_filters` actions, applied here via the filter hook.
//   - Query / Explain: surface grounded numbers + methodology, with each tool
//     call shown as an audit badge under the message.
//
// Server state (chat health + the send request) uses TanStack Query, matching
// the rest of the app; conversation/UI state is local component state.

import { useEffect, useRef, useState } from 'react'
import { useMutation } from '@tanstack/react-query'
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

interface ChatApiResponse {
  text: string
  actions: ChatAction[]
  tool_calls: ToolCallAudit[]
}

interface ChatTurn {
  role: 'user' | 'assistant'
  content: string
  toolCalls?: ToolCallAudit[]
}

const STARTER_PROMPTS = [
  'Which five boroughs have the highest preventable harm?',
  'Show me robbery in Westminster in 2024',
  'How is preventability calculated?',
]

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

async function sendChat(payload: {
  messages: Array<{ role: string; content: string }>
  filters: MapRequest
}): Promise<ChatApiResponse> {
  const res = await fetch('/api/chat', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
  if (!res.ok) {
    let message = `Chat failed: ${res.status}`
    try {
      const body = (await res.json()) as { error?: string }
      if (body.error) message = body.error
    } catch {
      // keep the status-code message
    }
    throw new Error(message)
  }
  return (await res.json()) as ChatApiResponse
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
  const scrollRef = useRef<HTMLDivElement>(null)

  const mutation = useMutation({
    mutationFn: sendChat,
    onSuccess: (response) => {
      setTurns((prev) => [
        ...prev,
        { role: 'assistant', content: response.text, toolCalls: response.tool_calls },
      ])
      // Apply navigation actions after the assistant text has been appended.
      for (const action of response.actions) {
        if (action.type === 'set_filters') {
          update(actionToFilterPatch(action.payload))
        }
      }
    },
    onError: (err: unknown) => {
      setError(err instanceof Error ? err.message : 'Something went wrong.')
    },
  })

  // Keep the latest message in view.
  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: 'smooth' })
  }, [turns, mutation.isPending])

  function submit(text: string) {
    const trimmed = text.trim()
    if (!trimmed || mutation.isPending) return
    setError(null)

    const nextTurns: ChatTurn[] = [...turns, { role: 'user', content: trimmed }]
    setTurns(nextTurns)
    setInput('')

    mutation.mutate({
      messages: nextTurns.map((t) => ({ role: t.role, content: t.content })),
      filters: toMapRequest(filters),
    })
  }

  function clearChat() {
    setTurns([])
    setError(null)
  }

  return (
    <div
      className={`fixed right-0 top-0 z-40 flex h-screen w-[360px] flex-col border-l border-border bg-card shadow-xl transition-transform duration-200 ${
        open ? 'translate-x-0' : 'translate-x-full'
      }`}
      aria-hidden={!open}
    >
      {/* Header */}
      <div className="flex items-center justify-between gap-2 border-b border-border px-4 py-3">
        <div>
          <h2 className="text-sm font-semibold text-fg">Assistant</h2>
          <p className="text-[11px] text-muted">Police view · grounded in the dashboard data</p>
        </div>
        <div className="flex items-center gap-1">
          {turns.length > 0 && (
            <button
              onClick={clearChat}
              className="rounded px-2 py-1 text-[11px] text-muted hover:bg-surface hover:text-fg"
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

      {/* Messages */}
      <div ref={scrollRef} className="flex-1 space-y-3 overflow-y-auto px-4 py-3">
        {turns.length === 0 && (
          <div className="space-y-3">
            <p className="text-xs text-muted">
              Ask about London crime demand, filter the map, or ask how the metrics are built.
            </p>
            <div className="space-y-2">
              {STARTER_PROMPTS.map((prompt) => (
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
          <Message key={index} turn={turn} />
        ))}

        {mutation.isPending && (
          <div className="flex items-center gap-2 text-xs text-muted">
            <span className="h-2 w-2 animate-pulse rounded-full bg-accent" />
            Thinking…
          </div>
        )}

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
          disabled={mutation.isPending || !input.trim()}
          className="rounded-md bg-accent px-3 py-2 text-xs font-medium text-white disabled:opacity-40"
        >
          Send
        </button>
      </form>
    </div>
  )
}

function Message({ turn }: { turn: ChatTurn }) {
  const isUser = turn.role === 'user'
  return (
    <div className={isUser ? 'flex justify-end' : 'flex justify-start'}>
      <div
        className={`max-w-[90%] rounded-lg px-3 py-2 text-xs ${
          isUser ? 'bg-accent text-white' : 'bg-surface text-fg'
        }`}
      >
        <p className="whitespace-pre-wrap">{turn.content}</p>

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
      </div>
    </div>
  )
}
