import { useEffect } from 'react'
import type { ReactNode } from 'react'
import type { UseQueryResult } from '@tanstack/react-query'
import { useQuery } from '@tanstack/react-query'
import { fetchWeights } from '../lib/api'
import type { WeightRow } from '../lib/types'

// Single source of truth for the section anchors: drives the sidebar TOC, and
// the derived SectionId union makes a drifting JSX id a compile error.
const SECTIONS = [
  { id: 'overview', title: 'Overview' },
  { id: 'composite-signal', title: 'The Composite Demand Signal' },
  { id: 'severity', title: 'Crime Severity: the Cambridge Crime Harm Index' },
  { id: 'preventability', title: 'Crime Preventability' },
  { id: 'forecasting', title: 'Forecasting' },
  { id: 'allocation', title: 'Allocation' },
  { id: 'conversational-assistant', title: 'Conversational Assistant' },
  { id: 'ethics', title: 'Ethical Framing' },
  { id: 'extensibility', title: 'Multi-city Extensibility' },
  { id: 'references', title: 'References' },
] as const

type SectionId = (typeof SECTIONS)[number]['id']

// Tier sort order for the preventability table: High first, unknown tiers last.
const TIER_RANK: Record<string, number> = { High: 0, Medium: 1, Low: 2 }

function sortWeights(rows: WeightRow[]): WeightRow[] {
  // Copy before sorting — the array is the shared react-query cache entry.
  return [...rows].sort(
    (a, b) =>
      (TIER_RANK[a.preventability_tier] ?? 99) - (TIER_RANK[b.preventability_tier] ?? 99) ||
      (b.preventability_multiplier ?? -1) - (a.preventability_multiplier ?? -1),
  )
}

type SectionProps = {
  id: SectionId
  title: string
  children: ReactNode
}

function Section({ id, title, children }: SectionProps) {
  return (
    <section id={id} className="mt-10">
      <h2 className="text-lg font-semibold text-fg">
        <a href={`#${id}`} className="hover:text-accent">
          {title}
        </a>
      </h2>
      <div className="mt-2 space-y-3 text-sm leading-relaxed text-muted">{children}</div>
    </section>
  )
}

function WeightsTable({ query }: { query: UseQueryResult<WeightRow[]> }) {
  if (query.isPending) {
    return <p>Loading weights…</p>
  }

  if (query.isError) {
    const message = query.error instanceof Error ? query.error.message : 'Unexpected error'
    return <p className="text-red-400">Could not load the weights table: {message}</p>
  }

  return (
    <div className="overflow-x-auto rounded-lg border border-border">
      <table className="w-full border-collapse bg-card text-left text-xs">
        <thead>
          <tr className="border-b border-border text-fg">
            <th className="px-3 py-2 font-semibold">Category</th>
            <th className="px-3 py-2 font-semibold">Tier</th>
            <th className="px-3 py-2 font-semibold">Multiplier</th>
            <th className="px-3 py-2 font-semibold">Confidence</th>
            <th className="px-3 py-2 font-semibold">Anchor</th>
          </tr>
        </thead>
        <tbody>
          {sortWeights(query.data).map((row) => (
            <tr key={row.category} className="border-b border-border last:border-b-0 align-top">
              <td className="px-3 py-2 font-medium text-fg">{row.category}</td>
              <td className="px-3 py-2">{row.preventability_tier}</td>
              <td className="px-3 py-2">{row.preventability_multiplier?.toFixed(1) ?? '—'}</td>
              <td className="px-3 py-2">{row.preventability_confidence}</td>
              <td className="px-3 py-2">{row.preventability_anchor}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

export default function AboutPage() {
  const weights = useQuery({ queryKey: ['weights'], queryFn: fetchWeights })

  // Deep links like /about#severity: the browser's native fragment scroll fires
  // before React mounts, so replay it once the sections exist.
  useEffect(() => {
    const id = window.location.hash.slice(1)
    if (id) document.getElementById(id)?.scrollIntoView()
  }, [])

  // The weights table loads async and expands above the later sections, pushing
  // a deep-linked target back down — re-align once the query settles.
  const weightsSettled = !weights.isPending
  useEffect(() => {
    if (!weightsSettled) return
    const id = window.location.hash.slice(1)
    if (id) document.getElementById(id)?.scrollIntoView()
  }, [weightsSettled])

  return (
    <div className="h-full overflow-y-auto bg-surface">
      <div className="mx-auto flex max-w-7xl justify-center gap-10 px-5 py-10">
        <aside className="hidden w-44 shrink-0 lg:block">
          <nav aria-label="On this page" className="sticky top-10">
            <p className="text-xs font-semibold uppercase tracking-wide text-fg">On this page</p>
            <ul className="mt-3 space-y-2">
              {SECTIONS.map((s) => (
                <li key={s.id}>
                  <a
                    href={`#${s.id}`}
                    className="block text-xs leading-snug text-muted hover:text-fg"
                  >
                    {s.title}
                  </a>
                </li>
              ))}
            </ul>
          </nav>
        </aside>

        <div className="w-full min-w-0 max-w-3xl">
          <h1 className="text-2xl font-semibold text-fg">About &amp; Methodology</h1>
          <p className="mt-2 text-sm leading-relaxed text-muted">
            This page explains how the London Crime Explorer turns recorded crime into the police
            demand signal shown on the map. Everything here describes analysis that already runs in
            the app; the page adds no new numbers of its own.
          </p>

          <Section id="overview" title="Overview">
            <p>
              The London Crime Explorer is a decision-support system for police resource allocation.
              We combine three things an officer planner cares about: how much crime an area is
              expected to see, how serious that crime is, and how much of it visible patrol presence
              can realistically prevent.
            </p>
            <p>
              The system rests on four building blocks: open crime data aggregated to small areas
              (LSOAs), a composite demand signal that weights crime counts by severity and
              preventability, a forecast of near-future crime volume, and an allocation step that
              turns demand into a suggested distribution of attention. The tool is advisory — it
              ranks and explains, and every deployment decision stays with a human planner.
            </p>
          </Section>

          <Section id="composite-signal" title="The Composite Demand Signal">
            <p>
              Raw crime counts treat a stolen bicycle and a robbery as equal, so we do not rank areas
              by counts alone. Instead, every area and time period gets a composite score:
            </p>
            <pre className="overflow-x-auto rounded-lg border border-border bg-card p-3 text-xs text-fg">
              {`demand(area, period) = sum over categories c of
    crime_count(c, area, period)
  × severity_weight(c, basis)
  × preventability_multiplier(c)`}
            </pre>
            <p>
              Each term contributes something different. The crime count gives scale: more incidents
              mean more demand. The severity weight raises the contribution of serious offences, so
              one robbery counts for more than one bicycle theft. The preventability multiplier
              discounts categories that patrol presence cannot realistically deter, so the signal
              concentrates on harm that policing can actually avert. The same computation backs every
              metric mode on the map, so the numbers here and the numbers on the dashboard always
              agree.
            </p>
          </Section>

          <Section id="severity" title="Crime Severity: the Cambridge Crime Harm Index">
            <p>
              Severity comes from the Cambridge Crime Harm Index (CCHI), which scores each offence by
              the number of days of imprisonment recommended for a first-time offender (Sherman,
              Neyroud and Neyroud 2016). Using sentencing guidelines rather than public opinion gives
              a stable, documented measure of harm per offence.
            </p>
            <p>
              Police-recorded categories are broader than CCHI offences, so each of our 14 categories
              maps to a group of CCHI offences and we store both the mean and the median score of that
              group. The two can diverge sharply: Violence and sexual offences has a mean of roughly
              730 days but a median of roughly 183 days, because a few very high-harm offences pull
              the mean up. The dashboard exposes a Mean/Median toggle so users can choose whether
              those extremes should dominate the signal. Anti-social behaviour is non-notifiable and
              has no CCHI score; its severity is treated as zero, though it still contributes to the
              preventability-weighted view.
            </p>
          </Section>

          <Section id="preventability" title="Crime Preventability">
            <p>
              Preventability asks a simple question: if more officers were visibly present in an
              area, how much of this crime type would not happen? Decades of hot-spot policing
              research show the answer differs a lot by category. Street robbery concentrates in tiny
              geographic pockets and responds strongly to patrol presence, while most violence
              against the person happens indoors, between people who know each other, where a patrol
              cannot intervene.
            </p>
            <p>
              We encode this as a multiplier between 0.1 and 1.0 per category, each anchored to a
              specific finding in the literature and carrying a confidence rating that is honest
              about how directly the evidence applies. Tiers are derived from the multiplier
              (≥ 0.9 High, ≥ 0.4 Medium, below that Low). The table below is read live from the
              same weights file the analysis uses:
            </p>
            <WeightsTable query={weights} />
          </Section>

          <Section id="forecasting" title="Forecasting">
            <p>
              The forecast predicts how many crimes of each category each LSOA will see in upcoming
              months, so the demand signal can look forward rather than only describing the past.
            </p>
            <p>
              We use a gradient-boosted tree model (XGBoost with a Poisson objective, suited to count
              data) blended with a random forest, trained per volume tier so the few very high-volume
              areas do not distort predictions for the quiet majority. The features are deliberately
              simple: a time index that captures the overall trend, the calendar month that captures
              seasonality, and the LSOA and crime category identities that capture stable area
              characteristics. We evaluate on a chronological 70/30 split — the model is always
              tested on months it has never seen — and report MAE and RMSE, with a bias correction
              estimated on the most recent months.
            </p>
          </Section>

          <Section id="allocation" title="Allocation">
            <p>
              Allocation turns the demand signal into a suggested distribution of police attention
              across areas. We compare three variants: a proportional baseline that simply splits
              resources in proportion to forecast demand, a primary linear-programming model that
              maximises the total preventable harm covered, and a Rawlsian variant that maximises the
              position of the worst-served area.
            </p>
            <p>
              The three span the classic efficiency-versus-fairness trade-off: the LP concentrates
              resources where they avert the most harm overall, while the Rawlsian variant accepts a
              lower total to guarantee no area is left far behind. The dashboard presents the result
              as a ranking of areas, never as an instruction — it never prescribes officer counts,
              and the deployment decision always stays with the human planner.
            </p>
          </Section>

          <Section id="conversational-assistant" title="Conversational Assistant">
            <p>
              The dashboard ships with a conversational assistant that answers in plain language
              while staying anchored to the same numbers as the rest of the app. It offers three
              personas — a police planner, an examiner, and a community voice — that differ in tone
              but read from one shared data layer, so the figures never diverge. Every quantitative
              claim comes from an explicit tool call — filters, weights, forecast, allocation, and
              the methodology docs — and an audit badge under each reply names the tool that
              supplied the number, so a reader can check it rather than trust it. The same guardrail
              as the allocation view applies: the assistant ranks and explains options, and never
              prescribes a deployment.
            </p>
          </Section>

          <Section id="ethics" title="Ethical Framing">
            <p>
              Three guardrails are built into the design. First, the system is advisory: it informs
              a human decision and automates nothing. Second, allocation is per-area only — the
              system never scores, profiles, or makes predictions about individuals. Third, every
              number on the map is traceable: each weight links to a published study or a documented
              index, so a sceptical reader can check our reasoning rather than trust it. The
              project report's Ethics chapter discusses the harder questions — feedback loops,
              reporting bias in recorded crime, and the limits of place-based prediction — in full.
            </p>
          </Section>

          <Section id="extensibility" title="Multi-city Extensibility">
            <p>
              Nothing in the pipeline is London-specific. The same code runs for any city given two
              inputs: boundary files for its statistical areas and a crime feed in the
              data.police.uk format. Severity weights are UK-national and carry over directly. The
              app currently runs on London; extending it to further cities is a data swap, not a
              rewrite.
            </p>
          </Section>

          <Section id="references" title="References">
            <ul className="list-disc space-y-2 pl-5">
              <li>
                Sherman, L., Neyroud, P. W. and Neyroud, E. (2016). The Cambridge Crime Harm Index:
                Measuring Total Harm from Crime Based on Sentencing Guidelines.{' '}
                <em>Policing: A Journal of Policy and Practice</em>, 10(3), 171–183.{' '}
                <a
                  href="https://doi.org/10.1093/police/paw003"
                  target="_blank"
                  rel="noreferrer"
                  className="text-accent hover:underline"
                >
                  doi:10.1093/police/paw003
                </a>
              </li>
              <li>
                Braga, A. A., Turchan, B., Papachristos, A. V. and Hureau, D. M. (2019). Hot spots
                policing and crime reduction: an update of an ongoing systematic review and
                meta-analysis. <em>Journal of Experimental Criminology</em>, 15, 289–311.{' '}
                <a
                  href="https://doi.org/10.1007/s11292-019-09372-3"
                  target="_blank"
                  rel="noreferrer"
                  className="text-accent hover:underline"
                >
                  doi:10.1007/s11292-019-09372-3
                </a>
              </li>
              <li>
                Weisburd, D. (2015). The law of crime concentration and the criminology of place.{' '}
                <em>Criminology</em>, 53(2), 133–157.{' '}
                <a
                  href="https://doi.org/10.1111/1745-9125.12070"
                  target="_blank"
                  rel="noreferrer"
                  className="text-accent hover:underline"
                >
                  doi:10.1111/1745-9125.12070
                </a>
              </li>
              <li>
                Cambridge Centre for Evidence-Based Policing (2020). Cambridge Crime Harm Index 2020
                (offence-level harm scores, recommended sentence in days).{' '}
                <a
                  href="https://www.cambridge-ebp.co.uk/the-cchi"
                  target="_blank"
                  rel="noreferrer"
                  className="text-accent hover:underline"
                >
                  cambridge-ebp.co.uk/the-cchi
                </a>
              </li>
            </ul>
          </Section>
        </div>

        {/* Invisible twin of the TOC rail: both flanks reserve equal width, so
            the prose column sits exactly at the viewport centre. */}
        <div className="hidden w-44 shrink-0 lg:block" aria-hidden="true" />
      </div>
    </div>
  )
}
