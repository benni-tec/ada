import { mount } from '@/lib/mount'
import { WidgetRuntime } from '@/lib/runtime'

import { Custom } from './custom'

mount(<WidgetRuntime>{(loaded) => <Custom {...loaded} />}</WidgetRuntime>)
