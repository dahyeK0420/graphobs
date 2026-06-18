# Backend Export

This example configures OpenTelemetry with local, dependency-free exporters:
`InMemorySpanExporter` for tests and `ConsoleSpanExporter` for terminal output.

```bash
uv run python -m examples.backend_export.app
```

The example does not contact a hosted service. If you later choose an OTLP
backend, add the matching OpenTelemetry exporter package and configure it at the
application boundary rather than inside the library.
