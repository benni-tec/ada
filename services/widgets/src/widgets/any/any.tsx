import type { Loaded } from '@/lib/runtime'
import { Chart } from '@/widgets/chart/chart'
import { LineChart } from '@/widgets/line-chart/line-chart'
import { RegionMap } from '@/widgets/map/map'
import { Table } from '@/widgets/table/table'
import { Value } from '@/widgets/value/value'

const TYPES = { value: Value, table: Table, 'line-chart': LineChart, map: RegionMap, chart: Chart }

/**
 * Every widget type in one bundle, picked by the widget's type once it is loaded.
 *
 * An MCP host renders one ui:// resource per tool, and create_widget makes widgets of any
 * type, so that resource is this bundle. The frontend loads the bundle of each type.
 */
export function Any(loaded: Loaded) {
  const Widget = TYPES[loaded.widget.type as keyof typeof TYPES]
  if (!Widget) return <p className="ada-error">Unknown widget type: {loaded.widget.type}</p>
  return <Widget {...loaded} />
}
