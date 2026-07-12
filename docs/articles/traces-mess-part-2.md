# I Shipped the Fix for My Messy LangGraph Traces. The Base Class Was the First Thing to Go.

*Last time I blamed three questions collapsed into one blob. Then I actually built the library — and reality rewrote half the design.*

This is a continuation of [Your LangGraph traces are a mess, and it is not the tracer's
fault](https://medium.com/@dahye.k94420/your-langgraph-traces-are-a-mess-and-its-not-the-tracer-s-fault-1bd6c1ad2146).
If you have not read it, the one-paragraph version is this: state, logs, and traces
answer three different questions, and LangGraph happily lets you answer all three with
the same fat state blob. The result is a "trace" that is really a whole-state dump with
timestamps on it — 6,000 lines of attributes you cannot search. That is not a tracer
bug. It is a design decision nobody made on purpose.

I ended that article by proposing a **base `Node` class**: inherit from it, declare what
your node reads and writes, and get a clean span for free. Tidy diagram, confident tone,
about fifteen lines of code.

Then I tried to put it on a real graph. This article is what survived, what didn't, and
how to actually adopt the thing. The library is called
[`graphobs`](https://github.com/dahyeK0420/graphobs), and everything below runs against
its synthetic examples.

## The base class was the first casualty

The base class assumed something that is almost never true: that you own how your nodes
are constructed. Real LangGraph graphs are full of nodes that are plain functions,
`functools.partial` objects, closures over a client, lambdas in a routing table. You do
not get to insert yourself into a class hierarchy that was never there.

It also fought the one promise the first article actually cared about — *migrate one node
at a time*. A base class is all-or-nothing per node: either the node is an instance of my
class or it isn't. There is no "just watch this node for a week" setting.

And then reducers. LangGraph channels can be reducer-managed —`add_messages`,
`Annotated[list, operator.add]`. A node is supposed to return a **partial update**, and
the reducer folds it into state exactly once. A base class that wraps execution and
returns a reconstructed state object double-applies through those reducers and quietly
duplicates your message history. That bug does not show up in a diagram.

So the single base class split into two things that turned out to want very different
lifetimes:

```python
from graphobs import NodeContract, contract_node


@contract_node(
    NodeContract(
        name="classify",
        reads=("request.text",),
        writes=("classification.label",),
    )
)
def classify(state):
    return {"classification": {"label": "question"}}
```

- `NodeContract` is the **declaration** — plain Python, no graph runtime dependency at
  all. You can import it in a unit test that never touches LangGraph.
- `contract_node` is the **enforcement** — the only piece that knows about LangGraph, and
  the piece that is careful to return your node's partial update *untouched* so reducers
  still apply once.

Same idea as the base class. Opposite shape. Inheritance became declaration-plus-wrapper,
and the declaration became the valuable half.

## The contract is just a boundary

A `NodeContract` says what a node is allowed to touch, and nothing else:

```python
from graphobs import NodeContract

classify_contract = NodeContract(
    name="classify",
    reads=("request.text",),
    writes=("classification.label",),
    private_reads=("scratch.notes",),   # local working state, never projected publicly
    span_kind="CHAIN",                  # OpenInference kind: CHAIN / RETRIEVER / TOOL / LLM / AGENT
    attributes={"graph.step": "classify"},
)
```

That declaration is the single source of truth. The same reads/writes drive four things
that used to drift apart in every codebase I have seen: what the node is *given*, what it
is *allowed to return*, what shows up in the **span** payload, and what a projected
**callback** payload contains. Declare the boundary once; stop re-deciding it in four
places.

`reads` and `writes` are dotted paths: you declare the boundary once, and heavy values —
the `documents` list you want to *see the shape of* — are kept to their shape in the span
by the default compact serializer, without dumping every body into a trace.

## Adoption is a ladder, not a switch

The second thing reality taught me: you cannot flip a live graph to strict mode on a
Tuesday afternoon. Real nodes read fallback keys you forgot about and write namespace
markers some reducer owns. Turn on enforcement blind and you get a wall of
`StateContractError`s that tell you nothing except "this is scary, revert."

So enforcement is a dial, `NodeContractMode`, and you climb it per node:

| Goal | Start here | Changes execution? |
| --- | --- | --- |
| Cleaner downstream callback payloads only | `project_callback_payloads` | No |
| Cleaner spans, zero behavior change | `contract_node(..., mode=OBSERVE)` | No |
| Surface undeclared reads/writes as warnings | `contract_node(..., mode=AUDIT)` | No (full state still flows) |
| Strict, contract-shaped execution | `contract_node(...)` (default `ENFORCE`) | Yes |

The bottom rung touches nothing but the payloads your callbacks see:

```python
from graphobs.langgraph.callbacks import project_callback_payloads

config = {
    "callbacks": [
        project_callback_payloads(callback, [classify_contract], diagnostics=True),
    ],
}
```

`OBSERVE` gives you clean spans while the node still runs on the real, full state.
`AUDIT` adds a log line every time the node reads or writes a path the contract didn't
declare — no values, just the path — so you learn the true boundary from production
traffic before you enforce it. `ENFORCE` (the default) projects the input down to
declared reads and raises on undeclared writes.

You can instrument a whole graph in `OBSERVE` in one call and promote nodes to `ENFORCE`
individually as each boundary stops surprising you:

```python
from graphobs import NodeContractMode, add_contract_nodes

add_contract_nodes(
    graph,
    [(classify_contract, classify), (answer_contract, answer)],
    mode=NodeContractMode.OBSERVE,
)
```

The base class had one setting: on. The ladder is the difference between a design that
demos and a design you can actually roll out.

## The payoff, in real output

Here is the `simple_rag` example — a three-node classify → retrieve → answer graph. First,
the trace you get by dumping state, which is the mess from article one, reproduced
faithfully:

```json
{
  "name": "raw_simple_rag",
  "kind": "CHAIN",
  "input": {
    "request": {
      "raw_notes": "raw request notes stay out of contract spans",
      "text": "How do contracts improve graph traces?"
    },
    "scratch": { "draft_query": "contract graph trace payload boundaries" }
  },
  "output": {
    "answer": { "text": "Answer from synthetic docs: Contracts keep trace payloads focused." },
    "classification": { "intent": "question" },
    "documents": [ { "summary": "...", "title": "Observability Notes" }, "..." ],
    "request": { "raw_notes": "raw request notes stay out of contract spans", "text": "..." },
    "scratch": { "draft_query": "contract graph trace payload boundaries" }
  }
}
```

`raw_notes` is in the trace. `scratch.draft_query` is in the trace, twice. Full document
bodies are in the trace. And this is *one* span for the whole run, because there is no
per-node structure to hang anything on.

Now the same graph with a contract on each node. This is the `retrieve_docs` span,
verbatim from the exporter:

```json
{
  "name": "retrieve_docs",
  "kind": "RETRIEVER",
  "attributes": { "graph.node": "retrieve_docs" },
  "input": {
    "classification": { "intent": { "length": 8, "type": "str" } },
    "request": { "text": { "length": 38, "type": "str" } }
  },
  "output": {
    "documents": [
      { "summary": { "length": 38, "type": "str" }, "title": { "length": 19, "type": "str" } },
      { "summary": { "length": 51, "type": "str" }, "title": { "length": 15, "type": "str" } }
    ]
  }
}
```

Three things changed and all three matter:

1. **One span per node**, with the right OpenInference kind (`RETRIEVER` here, `CHAIN`
   elsewhere). Now it renders as a real tree in Phoenix, Langfuse, LangSmith, Arize —
   whatever you point it at.
2. **Only declared reads and writes.** `raw_notes` and `scratch` are simply not here.
   They were never in the contract, so they were never projected.
3. **Compact by default.** `{"length": 38, "type": "str"}` instead of the string. That is
   not a redaction pass bolted on afterward — the payload serializer records *shape, not
   value* unless you explicitly ask for full mode. Over-collection is the default-off
   state, not the thing you remember to turn off. (The same `shape_summary` helper feeds
   traces, logs, and callback projection, so the surfaces cannot drift apart.)

## The bug the contract catches for free

Article one claimed that enforcing write contracts makes state corruption "impossible to
hide." Here is that claim as a running assertion. A retriever that reaches outside its
lane:

```python
def bad_retriever(state):
    return {"documents": [], "debug": {"query": "unexpected"}}  # debug.* is not ours
```

Wrapped in a contract that declares `writes=("documents",)`, the run stops with a message
that names the exact drift:

```text
StateContractError: Contract 'bad_retriever' wrote undeclared state paths: debug.query
```

That is a node quietly growing a new state key — the thing that later becomes "why is
there a `debug` blob in production state and who owns it?" The contract turns it into a
failed test today. As of `0.3.0` the same enforcement runs on the read side too: a strict
node that reaches for a key it never declared raises instead of silently resolving a
default.

## The parts that only exist because I built it

None of these were in the tidy fifteen-line sketch. All of them turned out to be the
actual work.

- **Public vs private state.** Nodes have local scratch that is genuinely useful and
  genuinely nobody else's business. `private_reads` / `private_writes` are validated like
  everything else but never projected into a parent boundary or a span. It is a *modeling*
  boundary, not a security control — sensitive data still needs real handling — but it
  keeps implementation detail out of the trace.
- **Reducer safety, stated out loud.** `contract_node` returns your partial update
  unchanged, so `add_messages` and accumulating reducers apply exactly once. `contract_subgraph`
  is the sharp edge: it cannot see the parent's channel reducers, so it returns the
  subgraph's full projected value — correct for last-value-wins channels, wrong for
  non-deduplicating accumulators. Keep those on node-level contracts. This is the kind of
  thing you only find by running it, not by drawing it.
- **Backend portability by omission.** The library emits OpenTelemetry spans with
  OpenInference attributes and configures **no exporter**. The application owns the tracer
  provider, the credentials, the retention. So the same span shape goes to an in-memory
  exporter in a unit test and to your OTLP backend in production, unchanged.
- **Drift tests and discovery.** `assert_contract_matches` runs a node against synthetic
  samples and warns when it reads or writes outside its contract; pass
  `on_drift=ContractViolationAction.RAISE` and it becomes a red CI test instead of a 2 a.m.
  surprise. And `discover_contract` runs an existing node against sample states to *draft* a
  contract for you to review. It is best-effort and sample-dependent; it is a starting
  point, not an oracle.

## When not to bother

Same honesty as last time. If your graph has fewer than three nodes, or no noisy shared
state, plain LangGraph plus zero-code auto-instrumentation is genuinely enough. A messy
trace is fine when the whole run fits on one screen.

Reach for contracts the day you scroll a trace hunting for one field and cannot find it,
or the day a node writes a key you did not know it owned. That is the day the boundary was
already real — you just had not written it down.

## Get it

```bash
pip install "graphobs[demo]"
jupyter lab examples/notebooks/quickstart.ipynb
```

The notebook does the whole argument in two acts: curated-vs-messy spans in an embedded
viewer with no credentials, then a per-platform `.env` recipe for Phoenix, LangSmith,
MLflow, or Langfuse. If you'd rather read than run, the practical path is spelled out in
[Migrate one node at a time](../guides/migration-one-node-at-a-time.md) and
[Designing node contracts](../concepts/designing-node-contracts.md).

The thesis from article one didn't change: **clean state and clean traces are the same
constraint.** What changed is where I put it. Not a base class you inherit — a contract
you declare, enforced at the one boundary that was always there.
