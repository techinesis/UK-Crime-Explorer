import { NavLink } from 'react-router-dom'

function linkClass({ isActive }: { isActive: boolean }): string {
  return isActive
    ? 'text-sm font-medium text-fg underline underline-offset-4'
    : 'text-sm font-medium text-muted hover:text-fg'
}

interface NavBarProps {
  chatAvailable: boolean
  chatOpen: boolean
  onToggleChat: () => void
}

export default function NavBar({ chatAvailable, chatOpen, onToggleChat }: NavBarProps) {
  return (
    <nav className="flex shrink-0 items-center gap-5 border-b border-border bg-sidebar px-5 py-2">
      <NavLink to="/" end className={linkClass}>
        Dashboard
      </NavLink>
      <NavLink to="/allocation" className={linkClass}>
        Allocation
      </NavLink>
      <NavLink to="/about" className={linkClass}>
        About
      </NavLink>
      {chatAvailable && (
        <button
          onClick={onToggleChat}
          aria-pressed={chatOpen}
          className="ml-auto rounded-md border border-border bg-card px-3 py-1.5 text-xs font-medium text-fg hover:border-accent"
        >
          💬 Assistant
        </button>
      )}
    </nav>
  )
}
