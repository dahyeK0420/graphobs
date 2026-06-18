# Logging

The logging module contains structured lifecycle logging helpers for graph
runs. These APIs emit discrete callback events with correlation fields,
durations, and compact shape summaries. They do not configure a log exporter or
store full graph state payloads.

::: graph_observability_kit.logging
