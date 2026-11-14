import { mount } from '@/lib/mount'
import { WidgetRuntime } from '@/lib/runtime'

import { RegionMap } from './map'

mount(<WidgetRuntime>{(loaded) => <RegionMap {...loaded} />}</WidgetRuntime>)
