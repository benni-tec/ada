import { mount } from '@/lib/mount'
import { WidgetRuntime } from '@/lib/runtime'

import { Text } from './text'

mount(<WidgetRuntime>{(loaded) => <Text {...loaded} />}</WidgetRuntime>)
