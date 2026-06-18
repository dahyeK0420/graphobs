# State, Logs, And Traces

Graph observability works best when state, logs, and traces answer different questions.

| Surface | Best For | Avoid |
| --- | --- | --- |
| State | Working data that graph steps read and write | Treating all state as safe to expose |
| Logs | Lifecycle events, durations, errors, and correlation | Duplicating full trace payloads |
| Traces | Execution flow, curated payloads, attributes, and errors | Recording whole graph state by default |

## State

State is the data a graph carries between steps. Contracts define which keys a node or boundary may read, which keys it may write, and which details are local implementation state.

## Logs

Logs record discrete lifecycle events. They are useful for operational timelines, error summaries, counters, and correlation fields. Logs should avoid duplicating large state payloads.

Graph Observability Kit provides `LogContext`, `CorrelationFields`,
`GraphLogCallback`, and `build_invoke_config` for LangGraph/LangChain-style
callback logging. These helpers emit start, end, and error events with run IDs,
parent run IDs, durations, correlation fields, and compact input/output shape
summaries. Applications provide normal Python logging handlers and choose their
own export path.

Use logs when you need an operational event stream: what ran, when it started,
how long it took, whether it failed, and which session or request it belongs to.
Use the same `LogContext.as_attributes()` values on spans when logs and traces
should share correlation fields.

LangGraph node callbacks may receive the graph runtime's outer chain payload
even when a node is wrapped with a contract. Use
`graph_observability_kit.callbacks.project_callback_payloads` around callbacks
that should see the contract-projected node input and output instead. Root graph
events and unknown nodes pass through unchanged.

## Traces

Traces show execution flow. A span can capture timing, a span kind, curated input, curated output, searchable attributes, and errors.

Graph Observability Kit emits OpenTelemetry spans and uses OpenInference
semantic attributes where they apply. The library does not configure exporters.
Applications choose their own OpenTelemetry-compatible backend and configure the
tracer provider at the application boundary.

Trace payloads are compact by default. Compact mode records structural summaries
such as mapping size, keys, string length, and sequence size instead of full
arbitrary state values. Full mode is explicit and records complete
JSON-compatible payloads. Do not use full mode for sensitive production data.

Recoverable trace attribute issues are logged as warnings with the original
error message. Hard trace serialization and span mutation failures are logged as
errors and raised.

Use traces when you need execution shape, span nesting, curated payloads, or
backend-specific trace analysis. Logs should not duplicate full trace
input/output payloads.

## Contract-First Boundary Design

A contract-first approach asks what each boundary may expose before deciding what to record. That keeps debugging useful while reducing accidental payload sprawl.

Contracts make the same decision reusable: the declared reads and writes can
shape node execution, validation, trace payloads, and projected callback
payloads. Logs stay focused on events and correlation.

## Public And Private State

Contract helpers project only public state by default. Private state declarations
let implementations validate local writes, but they are not a security guarantee
and should not be used as a substitute for careful data handling.

See [Public Vs Private Graph State](public-vs-private-state.md) for the detailed
boundary model.
