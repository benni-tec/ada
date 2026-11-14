import { useMutation, useQueryClient, type QueryKey } from '@tanstack/react-query'
import { useState } from 'react'

import { ApiFailure, errorMessage } from '@/lib/api'

type Revisioned = { revision: number }

/**
 * A write to a record that carries a revision (optimistic locking). On a 409 someone else
 * changed the record since it was read: the record is read again and `conflict` says
 * what it is now, so the person can decide whether to save again on top of it.
 */
export function useRevisedUpdate<T extends Revisioned, V>({
  queryKey,
  read,
  update,
  describeConflict,
  alsoInvalidate = [],
}: {
  /** Where the record sits in the cache, and how to read it again. */
  queryKey: QueryKey
  read: () => Promise<T>
  update: (current: T, value: V) => Promise<T>
  describeConflict: (latest: T) => string
  /** Lists that show the record too. */
  alsoInvalidate?: QueryKey[]
}) {
  const queryClient = useQueryClient()
  const [conflict, setConflict] = useState<string | null>(null)

  const mutation = useMutation({
    mutationFn: async (value: V) => {
      setConflict(null)
      const current = queryClient.getQueryData<T>(queryKey) ?? (await read())
      return update(current, value)
    },
    onSuccess: (saved) => {
      queryClient.setQueryData<T>(queryKey, saved)
      for (const queryKey of alsoInvalidate) void queryClient.invalidateQueries({ queryKey })
    },
    onError: async (error) => {
      if (!(error instanceof ApiFailure && error.isConflict)) return
      const latest = await queryClient.fetchQuery({ queryKey, queryFn: read, staleTime: 0 }).catch(() => null)
      setConflict(
        latest
          ? describeConflict(latest)
          : 'Someone else changed this while you were editing, and it could not be read again.',
      )
      for (const queryKey of alsoInvalidate) void queryClient.invalidateQueries({ queryKey })
    },
  })

  const failure = mutation.error && !(mutation.error instanceof ApiFailure && mutation.error.isConflict)
  return {
    save: mutation.mutateAsync,
    pending: mutation.isPending,
    /** Set after a 409, once the record has been read again. */
    conflict,
    /** Any other failure, with the server's detail. */
    error: failure ? errorMessage(mutation.error) : null,
    reset: () => {
      mutation.reset()
      setConflict(null)
    },
  }
}
