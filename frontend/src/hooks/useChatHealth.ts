import { useQuery } from '@tanstack/react-query'

/**
 * Polls `GET /api/chat/health` once on mount to decide whether the AI chat panel
 * should be shown at all. Any failure (no key, missing deps, 404, network error)
 * is treated as "not configured", so the dashboard stays fully usable without a
 * chat backend.
 */
export function useChatAvailable(): boolean {
  const { data } = useQuery({
    queryKey: ['chat-health'],
    queryFn: async (): Promise<boolean> => {
      try {
        const res = await fetch('/api/chat/health')
        if (!res.ok) return false
        const body = (await res.json()) as { configured?: boolean }
        return Boolean(body.configured)
      } catch {
        return false
      }
    },
    staleTime: Infinity,
    retry: false,
  })
  return data ?? false
}
