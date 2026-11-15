import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { createFileRoute, Link, useNavigate } from '@tanstack/react-router'
import { useId, useState } from 'react'

import { FieldControls } from '@/components/cases/fields'
import { ErrorNotice, Loading } from '@/components/notices'
import { PageHeader } from '@/components/page-header'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import {
  caseQuery,
  caseTypeQuery,
  invalidateCase,
  putCase,
  ranText,
  statisticalModelsQuery,
  type CaseValues,
} from '@/lib/api'
import { cleanValues } from '@/lib/cases'
import { toast } from '@/lib/toast'

type Search = { type: string }

export const Route = createFileRoute('/projects/$projectId/cases/new')({
  validateSearch: (search: Record<string, unknown>): Search => ({ type: typeof search.type === 'string' ? search.type : '' }),
  component: NewCasePage,
})

/** A new case of one case type: its key and the form its schema generates. Saving runs the
 * automatic models and opens the case. */
function NewCasePage() {
  const { projectId } = Route.useParams()
  const { type: caseTypeId } = Route.useSearch()
  const queryClient = useQueryClient()
  const navigate = useNavigate()
  const keyId = useId()
  const { data: caseType, error } = useQuery({ ...caseTypeQuery(caseTypeId), enabled: caseTypeId !== '' })
  const { data: models } = useQuery(statisticalModelsQuery(projectId))
  const [key, setKey] = useState('')
  const [values, setValues] = useState<CaseValues>({})

  const save = useMutation({
    mutationFn: () => putCase(caseTypeId, key.trim(), cleanValues(values)),
    onSuccess: async (saved) => {
      queryClient.setQueryData(caseQuery(caseTypeId, saved.case.key).queryKey, saved)
      const names = saved.ran.map((id) => models?.find((m) => m.id === id)?.name ?? 'A model')
      toast(`Case ${saved.case.key} saved. ${ranText(names)}`)
      void invalidateCase(queryClient, caseTypeId, saved.case.key)
      await navigate({
        to: '/projects/$projectId/cases/$caseTypeId/$key',
        params: { projectId, caseTypeId, key: saved.case.key },
      })
    },
  })

  if (caseTypeId === '') return <p className="p-4 text-sm text-muted-foreground md:p-6">Choose a case type on the Cases page.</p>
  if (error) return <div className="p-4 md:p-6"><ErrorNotice error={error} /></div>
  if (!caseType) return <div className="p-4 md:p-6"><Loading what="the case type" /></div>

  return (
    <div className="flex max-w-5xl flex-col gap-5 p-4 md:p-6">
      <PageHeader
        type="case"
        typeLabel={
          <>
            <Link to="/projects/$projectId/cases" params={{ projectId }} className="hover:text-foreground">
              Cases
            </Link>
            <span aria-hidden="true">/</span>
            <span>{caseType.name}</span>
          </>
        }
        title="New case"
        below={<p className="text-sm text-muted-foreground">Synthetic data only.</p>}
      />
      <form
        className="flex flex-col gap-5 rounded-xl border bg-card p-4"
        onSubmit={(event) => {
          event.preventDefault()
          save.mutate()
        }}
      >
        <div className="flex max-w-sm flex-col gap-1">
          <label htmlFor={keyId} className="text-xs font-medium text-muted-foreground">
            Key
          </label>
          <Input
            id={keyId}
            className="font-mono"
            required
            maxLength={128}
            pattern="[A-Za-z0-9._:\-]+"
            placeholder="SYN-0042"
            aria-describedby={`${keyId}-help`}
            value={key}
            onChange={(event) => setKey(event.target.value)}
          />
          <p id={`${keyId}-help`} className="text-xs text-muted-foreground">
            The case's key in your system: letters, digits and . _ : -. Never a personal identity code. Saving under a key
            that exists updates that case.
          </p>
        </div>
        <FieldControls fields={caseType.fields} values={values} onChange={setValues} />
        {save.isError && <ErrorNotice error={save.error} prefix="Not saved:" />}
        <div className="flex justify-end gap-2 border-t pt-4">
          <Button variant="outline" asChild>
            <Link to="/projects/$projectId/cases" params={{ projectId }}>
              Cancel
            </Link>
          </Button>
          <Button type="submit" disabled={save.isPending}>
            {save.isPending ? 'Saving…' : 'Save case'}
          </Button>
        </div>
      </form>
    </div>
  )
}
