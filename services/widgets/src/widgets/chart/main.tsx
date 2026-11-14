import { mount } from '@/lib/mount'
import { WidgetRuntime } from '@/lib/runtime'

import { Chart } from './chart'

mount(<WidgetRuntime>{(loaded) => <Chart {...loaded} />}</WidgetRuntime>)
