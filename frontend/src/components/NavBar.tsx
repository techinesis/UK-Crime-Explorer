import { NavLink } from 'react-router-dom'

function linkClass({ isActive }: { isActive: boolean }): string {
  return isActive
    ? 'text-sm font-medium text-fg underline underline-offset-4'
    : 'text-sm font-medium text-muted hover:text-fg'
}

export default function NavBar() {
  return (
    <nav className="flex shrink-0 items-center gap-5 border-b border-border bg-sidebar px-5 py-2">
      <NavLink to="/" end className={linkClass}>
        Dashboard
      </NavLink>
      <NavLink to="/about" className={linkClass}>
        About
      </NavLink>
    </nav>
  )
}
