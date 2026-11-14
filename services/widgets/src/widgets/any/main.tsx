import { mount } from '@/lib/mount'
import { WidgetRuntime } from '@/lib/runtime'

import { Any } from './any'

mount(<WidgetRuntime>{(loaded) => <Any {...loaded} />}</WidgetRuntime>)
