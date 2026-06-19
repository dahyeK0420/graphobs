# Quickstart

The quickstart notebook walks through the full kit in two acts.

**Act 1 — zero credentials.** Install the demo bundle, run the notebook, and see
a curated contract span next to the raw state blob inside the notebook viewer.
No collector, no signup, no `.env` required.

**Act 2 — your platform.** Add a `.env` with your platform credentials and re-run
to send the same spans to Arize Phoenix, LangSmith, MLflow, or Langfuse.

## Install and open

```bash
pip install "graphobs[demo]"
jupyter lab examples/notebooks/quickstart.ipynb
```

## What is in the `[demo]` extra

| Package | Purpose |
|---------|---------|
| `opentelemetry-sdk` | Span capture and in-memory exporter |
| `opentelemetry-exporter-otlp-proto-http` | OTLP HTTP exporter for Act 2 |
| `arize-phoenix` | Embedded span viewer for Act 1 |
| `python-dotenv` | Loads `.env` in Act 2 |
| `jupyterlab` | Notebook runtime |
| `ipykernel` | Python kernel for JupyterLab |

The core package (`graphobs` without extras) only depends on
`opentelemetry-api`. The SDK and exporters are never pulled into a production
install unless you opt in.

## `.env` recipes

### Arize Phoenix (cloud)

Full OpenInference support — the recommended platform for this kit.

```dotenv
OTEL_EXPORTER_OTLP_ENDPOINT=https://app.phoenix.arize.com/v1/traces
OTEL_EXPORTER_OTLP_HEADERS=api_key=<your-phoenix-api-key>
```

### LangSmith

OpenInference `input.value` and `output.value` attributes appear in the span
attribute list rather than the primary I/O panel.

```dotenv
OTEL_EXPORTER_OTLP_ENDPOINT=https://api.smith.langchain.com/otel/v1/traces
OTEL_EXPORTER_OTLP_HEADERS=x-api-key=<your-langsmith-api-key>
LANGSMITH_PROJECT=<your-project-name>
```

### MLflow (self-hosted)

Start a local server first: `mlflow server --port 5000`.
OpenInference attributes appear in the raw attribute list; the I/O panel
uses MLflow's own convention and will be empty.

```dotenv
OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:5000/api/2.0/mlflow/otlp/v1/traces
```

### Langfuse

```dotenv
OTEL_EXPORTER_OTLP_ENDPOINT=https://cloud.langfuse.com/api/public/otel/v1/traces
OTEL_EXPORTER_OTLP_HEADERS=Authorization=Basic <base64(public_key:secret_key)>
```
