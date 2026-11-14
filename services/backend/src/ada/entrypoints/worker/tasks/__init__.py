"""One module per group of tasks, each declaring its tasks with @task from
ada.entrypoints.worker.registry. Each task calls one use case. Nothing is returned, since no
result backend is configured: services publish what clients need to know as events."""
