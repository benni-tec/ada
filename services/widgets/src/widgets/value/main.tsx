import { mount } from '@/lib/mount'
import { WidgetRuntime } from '@/lib/runtime'

import { Value } from './value'

mount(<WidgetRuntime>{(loaded) => <Value {...loaded} />}</WidgetRuntime>)
