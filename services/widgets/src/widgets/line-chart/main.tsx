import { mount } from '@/lib/mount'
import { WidgetRuntime } from '@/lib/runtime'

import { LineChart } from './line-chart'

mount(<WidgetRuntime>{(loaded) => <LineChart {...loaded} />}</WidgetRuntime>)
