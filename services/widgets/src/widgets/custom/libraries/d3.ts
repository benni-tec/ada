// d3 (7.9.0, pinned) for a custom widget whose spec lists it: built into a script
// (`?script`) that leaves it on the frame's global, where child-main.ts finds it.

import * as d3 from 'd3'

;(globalThis as typeof globalThis & { d3?: unknown }).d3 = d3
