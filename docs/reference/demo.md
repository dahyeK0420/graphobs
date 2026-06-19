# Demo Reference

Lightweight display and exporter implementation helpers for notebooks and
local demos.

Requires the `demo` optional dependencies:

```bash
pip install "graph-observability-kit[demo]"
```

These modules are not imported by the core package. Production code should
configure OpenTelemetry exporters directly.

::: graph_observability_kit.demo.tracing_setup

::: graph_observability_kit.demo.span_records
