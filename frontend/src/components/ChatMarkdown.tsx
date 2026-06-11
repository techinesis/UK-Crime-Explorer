// Markdown renderer for ASSISTANT chat messages only — user messages stay plain
// text (see Message in ChatPanel.tsx).
//   - GitHub-flavoured markdown (tables, strikethrough, task lists) via remark-gfm.
//   - No raw HTML: react-markdown never renders raw HTML without rehype-raw (not
//     installed), and img/iframe/script/style are explicitly disallowed on top.
//   - No syntax highlighting: plain monospace code blocks keep the bundle lean.
// Styling uses the semantic theme tokens (fg/card/sidebar/border/accent) so the
// output follows the runtime light/dark toggle; in dark mode they resolve to the
// dark-slate palette the chat spec names.

import ReactMarkdown, { type Components } from 'react-markdown'
import remarkGfm from 'remark-gfm'

const REMARK_PLUGINS = [remarkGfm]

const DISALLOWED_ELEMENTS = ['img', 'iframe', 'script', 'style']

// The assistant should emit h3 at the largest; render every heading level at the
// same modest size so a stray h1 can't shout inside the text-xs bubble.
const HEADING_CLASS = 'mb-1 mt-3 text-sm font-semibold text-fg first:mt-0'

// Module-level constant so the map keeps a stable identity across the re-render
// per streamed token.
const COMPONENTS: Components = {
  p: ({ node: _node, ...props }) => <p className="mb-2 leading-relaxed last:mb-0" {...props} />,
  strong: ({ node: _node, ...props }) => (
    <strong className="font-semibold text-fg" {...props} />
  ),
  em: ({ node: _node, ...props }) => <em className="italic" {...props} />,
  ul: ({ node: _node, ...props }) => <ul className="mb-2 list-disc space-y-1 pl-4" {...props} />,
  ol: ({ node: _node, ...props }) => (
    <ol className="mb-2 list-decimal space-y-1 pl-4" {...props} />
  ),
  h1: ({ node: _node, ...props }) => <h3 className={HEADING_CLASS} {...props} />,
  h2: ({ node: _node, ...props }) => <h3 className={HEADING_CLASS} {...props} />,
  h3: ({ node: _node, ...props }) => <h3 className={HEADING_CLASS} {...props} />,
  h4: ({ node: _node, ...props }) => <h4 className={HEADING_CLASS} {...props} />,
  a: ({ node: _node, ...props }) => (
    <a className="text-accent underline" target="_blank" rel="noopener noreferrer" {...props} />
  ),
  code: ({ node: _node, ...props }) => (
    <code className="rounded bg-card px-1 py-0.5 font-mono" {...props} />
  ),
  // react-markdown ≥9 has no `inline` flag on `code`; fenced blocks arrive as
  // <pre><code>, so the block look lives here and the inline-chip styles are
  // reset on the nested <code>.
  pre: ({ node: _node, ...props }) => (
    <pre
      className="mb-2 overflow-x-auto rounded bg-sidebar p-3 font-mono text-[11px] [&_code]:rounded-none [&_code]:bg-transparent [&_code]:p-0"
      {...props}
    />
  ),
  table: ({ node: _node, ...props }) => (
    <div className="mb-2 overflow-x-auto">
      <table className="w-full border-collapse text-xs" {...props} />
    </div>
  ),
  th: ({ node: _node, ...props }) => (
    <th className="border border-border px-2 py-1 text-left font-semibold text-fg" {...props} />
  ),
  td: ({ node: _node, ...props }) => <td className="border border-border px-2 py-1" {...props} />,
  blockquote: ({ node: _node, ...props }) => (
    <blockquote className="mb-2 border-l-2 border-border pl-2 text-muted" {...props} />
  ),
  hr: ({ node: _node, ...props }) => <hr className="my-2 border-border" {...props} />,
}

interface ChatMarkdownProps {
  content: string
}

export default function ChatMarkdown({ content }: ChatMarkdownProps) {
  return (
    <ReactMarkdown
      remarkPlugins={REMARK_PLUGINS}
      disallowedElements={DISALLOWED_ELEMENTS}
      unwrapDisallowed
      components={COMPONENTS}
    >
      {content}
    </ReactMarkdown>
  )
}
