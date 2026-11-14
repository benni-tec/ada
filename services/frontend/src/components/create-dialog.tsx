import { useMutation } from '@tanstack/react-query'
import { useId, useState, type FormEvent, type ReactElement } from 'react'

import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle, DialogTrigger } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'

import { Hint } from './icon-action'
import { ErrorNotice } from './notices'

/**
 * A small dialog that asks for one name and creates something with it, e.g. a session
 * from the sidebar's "New session". `create` resolves once the page has moved on to it.
 */
export function CreateDialog({
  trigger,
  hint,
  title,
  description,
  field,
  placeholder,
  submit,
  create,
}: {
  /** The control that opens it (a DialogTrigger child). */
  trigger: ReactElement
  /** A tooltip on the trigger, for an icon-only one. */
  hint?: string
  title: string
  description: string
  /** The field's label, e.g. "Title". */
  field: string
  placeholder?: string
  /** The button, e.g. "Start session". */
  submit: string
  create: (value: string) => Promise<unknown>
}) {
  const inputId = useId()
  const [open, setOpen] = useState(false)
  const [value, setValue] = useState('')
  const mutation = useMutation({
    mutationFn: create,
    onSuccess: () => {
      setValue('')
      setOpen(false)
    },
  })

  const onSubmit = (event: FormEvent) => {
    event.preventDefault()
    if (value.trim() !== '' && !mutation.isPending) mutation.mutate(value.trim())
  }

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        setOpen(next)
        if (!next) mutation.reset()
      }}
    >
      {hint ? (
        <Hint label={hint}>
          <DialogTrigger asChild>{trigger}</DialogTrigger>
        </Hint>
      ) : (
        <DialogTrigger asChild>{trigger}</DialogTrigger>
      )}
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{title}</DialogTitle>
          <DialogDescription>{description}</DialogDescription>
        </DialogHeader>
        <form onSubmit={onSubmit} className="flex flex-col gap-3">
          <label htmlFor={inputId} className="text-sm font-medium">
            {field}
          </label>
          <Input id={inputId} value={value} placeholder={placeholder} onChange={(event) => setValue(event.target.value)} />
          {mutation.error && <ErrorNotice error={mutation.error} prefix="Not created:" />}
          <Button type="submit" className="self-end" disabled={mutation.isPending || value.trim() === ''}>
            {mutation.isPending ? 'Creating…' : submit}
          </Button>
        </form>
      </DialogContent>
    </Dialog>
  )
}
