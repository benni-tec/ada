import { useQuery } from '@tanstack/react-query'
import { Plus, Workflow } from 'lucide-react'
import { useState, type ComponentProps } from 'react'

import { Button } from '@/components/ui/button'
import {
  Command,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
} from '@/components/ui/command'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import { errorMessage, pipelinesQuery, type Id, type Pipeline } from '@/lib/api'

/**
 * "Add widget": a searchable list of the project's pipelines (operators nothing else
 * reads). Widgets stay agent-made: picking one does not make a widget, it puts the
 * pipeline on the message as a chip, and the person says what to show.
 */
export function AddWidget({
  projectId,
  onPick,
  label = 'Add widget',
  variant = 'outline',
  size = 'sm',
  className,
}: {
  projectId: Id
  onPick: (pipeline: Pipeline) => void
  label?: string
  variant?: ComponentProps<typeof Button>['variant']
  size?: ComponentProps<typeof Button>['size']
  className?: string
}) {
  const [open, setOpen] = useState(false)
  const pipelines = useQuery({ ...pipelinesQuery(projectId), enabled: open })
  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <Button type="button" variant={variant} size={size} className={className} aria-haspopup="dialog">
          <Plus aria-hidden="true" data-icon="inline-start" />
          {label}
        </Button>
      </PopoverTrigger>
      <PopoverContent align="start" className="w-[min(28rem,calc(100vw-2rem))] p-0">
        <Command
          label="Search the pipelines"
          // Search the name, the sources and the columns: people remember any of them.
          filter={(value, search, keywords) =>
            [value, ...(keywords ?? [])].join(' ').toLowerCase().includes(search.toLowerCase()) ? 1 : 0
          }
        >
          <CommandInput placeholder="Search the pipelines…" />
          <CommandList>
            {pipelines.isPending ? (
              <p role="status" className="p-3 text-sm text-muted-foreground">
                Loading the pipelines…
              </p>
            ) : pipelines.error ? (
              <p role="alert" className="p-3 text-sm text-destructive">
                The pipelines cannot be loaded: {errorMessage(pipelines.error)}
              </p>
            ) : (
              <>
                <CommandEmpty>
                  {pipelines.data.length === 0 ? 'This project has no pipelines yet.' : 'No pipeline matches.'}
                </CommandEmpty>
                <CommandGroup heading="Pipelines">
                  {pipelines.data.map((pipeline) => (
                    <CommandItem
                      key={pipeline.operator_id}
                      value={`${pipeline.name} ${pipeline.operator_id}`}
                      keywords={[
                        ...pipeline.sources.map((source) => source.name),
                        ...pipeline.output.columns.map((column) => column.name),
                      ]}
                      onSelect={() => {
                        setOpen(false)
                        onPick(pipeline)
                      }}
                      className="items-start"
                    >
                      <Workflow aria-hidden="true" className="mt-0.5" />
                      <span className="flex min-w-0 flex-col gap-0.5">
                        <span className="truncate font-medium">{pipeline.name}</span>
                        <span className="truncate text-xs text-muted-foreground">
                          {pipeline.sources.map((source) => source.name).join(', ') || 'No source'} ·{' '}
                          {pipeline.output.columns.length} column{pipeline.output.columns.length === 1 ? '' : 's'}:{' '}
                          {pipeline.output.columns.map((column) => column.name).join(', ')}
                        </span>
                      </span>
                    </CommandItem>
                  ))}
                </CommandGroup>
              </>
            )}
          </CommandList>
        </Command>
      </PopoverContent>
    </Popover>
  )
}
