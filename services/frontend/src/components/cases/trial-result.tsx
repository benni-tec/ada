type Match = {
  nct_id: string
  title: string
  phase?: string | null
  countries?: string[]
  finnish_site?: boolean
  nearest?: { facility?: string | null; city?: string | null; country: string; km?: number | null } | null
  sex?: string | null
  age?: 'inside' | 'partly' | 'outside' | 'unknown'
  min_age_years?: number | null
  max_age_years?: number | null
  eligibility?: string
  url: string
}

type Body = { city?: string; total?: number; matches?: Match[] }

const ageText = {
  inside: 'age group inside the limits',
  partly: 'age group partly inside the limits',
  outside: 'age group outside the limits',
  unknown: 'no age group given',
} as const

// A limit the registry did not give is said to be missing, never read as no limit.
const ages = (min?: number | null, max?: number | null) =>
  min == null && max == null ? 'age not reported' : max == null ? `${min} and over` : `${min ?? 0}–${max}`

const sexText = (sex?: string | null) => (!sex ? 'sex not reported' : sex === 'ALL' ? 'all sexes' : sex === 'FEMALE' ? 'women' : sex === 'MALE' ? 'men' : sex.toLowerCase())

/** The trial matcher's result: the recruiting trials of the case's cancer group, nearest
 * first. Sex and age limits are shown, not applied; the eligibility text is the registry's,
 * folded, and never judged. */
export function TrialResult({ body, summary }: { body: Body; summary: string }) {
  const matches = body.matches ?? []
  const city = body.city ? body.city[0].toUpperCase() + body.city.slice(1) : 'Helsinki'
  return (
    <div className="flex flex-col gap-4">
      <p className="rounded-lg bg-foreground px-3.5 py-3 text-sm text-background">{summary}</p>
      <p className="text-xs text-muted-foreground">
        The case's cancer group only; sex and age limits are shown, not applied. Something to discuss with an oncologist, not an eligibility decision. Distances from {city}.
      </p>
      <ol className="flex flex-col gap-3">
        {matches.map((m) => (
          <li key={m.nct_id} className="rounded-lg border p-3 text-sm">
            <div className="flex flex-wrap items-start justify-between gap-2">
              <a href={m.url} target="_blank" rel="noreferrer" className="font-medium underline-offset-4 hover:underline">
                {m.title}
              </a>
              {m.finnish_site && <span className="rounded-full bg-emerald-50 px-2 py-0.5 text-xs font-medium text-emerald-800 dark:bg-emerald-950 dark:text-emerald-200">Finnish site</span>}
            </div>
            <p className="mt-1 text-xs text-muted-foreground">
              {m.nct_id}
              {m.phase ? ` · ${m.phase}` : ''}
              {m.countries?.length ? ` · recruiting in ${m.countries.join(', ')}` : ''}
            </p>
            <p className="mt-1 text-xs">
              {m.nearest ? `Nearest: ${[m.nearest.facility, m.nearest.city, m.nearest.country].filter(Boolean).join(', ')}${m.nearest.km != null ? `, ${Math.round(m.nearest.km)} km` : ''}` : 'No site distance'}
            </p>
            <p className="mt-1 text-xs text-muted-foreground">
              Registry limits: {sexText(m.sex)}, {ages(m.min_age_years, m.max_age_years)}
              {m.age && <> · {ageText[m.age]}</>}
            </p>
            {m.eligibility && (
              <details className="mt-2">
                <summary className="cursor-pointer text-xs text-muted-foreground">Eligibility, as registered</summary>
                <p className="mt-1 text-xs whitespace-pre-line">{m.eligibility}</p>
              </details>
            )}
          </li>
        ))}
      </ol>
      {(body.total ?? 0) > matches.length && (
        <p className="text-xs text-muted-foreground">
          Showing {matches.length} of {body.total}.
        </p>
      )}
    </div>
  )
}
