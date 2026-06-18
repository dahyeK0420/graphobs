# Designing Node Contracts

A useful node contract is small enough to be safe and specific enough to debug.
Start from the node's role, then declare the state boundary it needs.

## Start With One Node

Choose a node with stable input and output shape. Avoid the most complex node in
the graph for the first adoption step. The first contract should prove the
workflow, not model every possible boundary at once.

## Choose Reads

Declare only the state paths the node needs to make its decision.

```python
reads=("request.text", "retrieval.documents")
```

If a node receives the whole graph state today, the contract can still project a
smaller execution input before the node runs.

## Choose Writes

Declare the state paths the node is allowed to return.

```python
writes=("answer.text", "answer.confidence")
```

`validate_update` raises `StateContractError` when a node returns an undeclared
path. That failure is useful during adoption because it shows where state shape
and node behavior disagree.

## Use Private Paths Deliberately

Use private reads and writes for local scratch state that should not appear in
public projections.

```python
private_reads=("scratch.notes",)
private_writes=("scratch.notes",)
```

Private paths are validated, but they are not a substitute for payload safety or
access control.

## Add Searchable Attributes

Attributes should be flat, stable labels that help filter traces.

```python
contract = NodeContract(
    name="answer_question",
    reads=("request.question", "retrieval.documents"),
    writes=("answer.text",),
    span_kind="CHAIN",
    attributes={"graph.step": "answer"},
)
```

Avoid putting user content or large state values in attributes. Curated input and
output belong in span payload helpers.

## Design Review Questions

- Can a reader tell what this node is allowed to read and write?
- Are public writes limited to values other nodes need?
- Are local scratch values private?
- Would compact trace payloads still be useful?
- Would an undeclared write indicate a real boundary drift?
