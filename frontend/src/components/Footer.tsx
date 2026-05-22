export default function Footer() {
  return (
    <section className="rounded-lg border border-border bg-card p-3 text-[11px] leading-relaxed text-muted">
      <h3 className="mb-1 text-xs font-semibold uppercase tracking-wide text-muted">
        Notes &amp; sources
      </h3>
      <p className="mb-1">
        <span className="text-fg">Severity</span> uses the Cambridge Crime Harm Index 2020
        (recommended sentence in days). <span className="text-fg">Mean</span> preserves total
        harm-days; <span className="text-fg">Median</span> is robust to long-tailed offence mixes —
        the two produce different rankings, so state the basis you used.
      </p>
      <p className="mb-1">
        <span className="text-fg">Anti-social behaviour</span> is non-notifiable and outside CCHI's
        scope, so it carries zero severity in severity-weighted and composite modes (it stays
        visible in raw and preventability modes).
      </p>
      <p className="mb-1">
        <span className="text-fg">Preventability</span> multipliers are anchored in the literature
        (Braga et&nbsp;al. 2019; Weisburd 2015/2021; Sherman, Neyroud &amp; Neyroud 2016).
      </p>
      <p>Confidence: 🟢 High · 🟡 Medium · 🔴 Low evidence strength.</p>
    </section>
  )
}
