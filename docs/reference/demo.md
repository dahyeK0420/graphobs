# Demo Reference

Lightweight display and exporter implementation helpers for notebooks and
local demos.

Requires the `demo` optional dependencies:

```bash
pip install "graphobs[demo]"
```

These modules are not imported by the core package. Production code should
configure OpenTelemetry exporters directly.

::: graphobs.demo.tracing_setup

::: graphobs.demo.span_records
