import { Check, ChevronDown, Cpu } from 'lucide-react'

import { Button } from '@/components/ui/button'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import type { LlmModels } from '@/lib/api'

/**
 * Which model answers the next message: the configured `session_agent` unless the person
 * picks another. A model that cannot be used (its key is not set) is listed, disabled,
 * with the reason, so nobody wonders where it went.
 */
export function ModelPicker({
  models,
  value,
  defaultId,
  onChange,
}: {
  models: LlmModels
  value: string
  /** The model that answers when none is picked; the session agent unless it is a research session. */
  defaultId?: string | null
  onChange: (id: string) => void
}) {
  const short = (id: string) => id.split('/').at(-1) ?? id
  return (
    <DropdownMenu>
      <Tooltip>
        <TooltipTrigger asChild>
          <DropdownMenuTrigger asChild>
            <Button type="button" variant="ghost" size="sm" aria-label={`Model: ${value}`} className="max-w-48 text-muted-foreground">
              <Cpu aria-hidden="true" data-icon="inline-start" />
              <span className="truncate">{short(value)}</span>
              <ChevronDown aria-hidden="true" data-icon="inline-end" />
            </Button>
          </DropdownMenuTrigger>
        </TooltipTrigger>
        <TooltipContent>Model</TooltipContent>
      </Tooltip>
      <DropdownMenuContent align="start" className="w-72">
        <DropdownMenuLabel>Model for the next message</DropdownMenuLabel>
        <DropdownMenuSeparator />
        {models.models.map((model) => (
          <DropdownMenuItem
            key={model.id}
            disabled={!model.available}
            onSelect={() => onChange(model.id)}
            className="items-start"
            aria-checked={model.id === value}
            role="menuitemradio"
          >
            <Check aria-hidden="true" className={model.id === value ? 'mt-0.5' : 'invisible mt-0.5'} />
            <span className="flex min-w-0 flex-col">
              <span className="truncate">
                {model.id}
                {model.id === (defaultId ?? models.session_agent) ? ' (default)' : ''}
              </span>
              {!model.available && <span className="text-xs text-muted-foreground">{model.reason ?? 'Not available'}</span>}
            </span>
          </DropdownMenuItem>
        ))}
      </DropdownMenuContent>
    </DropdownMenu>
  )
}
