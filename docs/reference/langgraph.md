# LangGraph Reference

The LangGraph integration module wraps nodes and compiled subgraphs with the
same contract model used by the core projection and validation helpers.
`contract_node` supports both explicit wrapping and decorator-style wrapping.
`add_contract_node` registers the node under `contract.label`, so the graph node
name stays aligned with the contract's public label.

::: graph_observability_kit.langgraph
