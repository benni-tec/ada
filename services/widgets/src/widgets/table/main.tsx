import { mount } from '@/lib/mount'
import { WidgetRuntime } from '@/lib/runtime'

import { Table } from './table'

mount(<WidgetRuntime>{(loaded) => <Table {...loaded} />}</WidgetRuntime>)
