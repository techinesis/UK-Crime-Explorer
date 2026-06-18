// One shared FilterState for the whole app. The Dashboard, the standalone
// Allocation page, and the AI chat all read and write the SAME state through this
// context, so a change made on any surface (a slider, or the chat's
// set_filters / set_allocation_params action) is reflected everywhere. Without
// this, each route held its own useFilters island and the chat could only ever
// affect the page it lived on.

import { createContext, useContext, type ReactNode } from 'react'
import { useFilters } from './useFilters'

type FiltersValue = ReturnType<typeof useFilters>

const FiltersContext = createContext<FiltersValue | null>(null)

export function FiltersProvider({ children }: { children: ReactNode }) {
  const value = useFilters()
  return <FiltersContext.Provider value={value}>{children}</FiltersContext.Provider>
}

export function useFiltersContext(): FiltersValue {
  const ctx = useContext(FiltersContext)
  if (!ctx) throw new Error('useFiltersContext must be used within a FiltersProvider')
  return ctx
}
