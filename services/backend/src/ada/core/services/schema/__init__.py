"""What columns mean: periods, regions and measures (spec: Semantic roles, Time ranges).

The data and its conversions stay in pipelines; this package holds the thin declaration
of what the columns mean and every check that reads it: role declarations against
columns, bindings against slots, widgets against what they need, and the guard that keeps
confidence intervals from surviving an aggregation.
"""
