"""Phase 2: autonomous investigation agent.

    tools.py     the bounded, allow-listed tools the agent can call (graph reads, citation verification,
                 proposal writes) and the evidence ledger every tool result feeds
    llm.py       NVIDIA-hosted, OpenAI-compatible chat client with tool calling, model fallback and a
                 per-run circuit breaker
    verify.py    independent checks of every agent finding against the ledger
    report.py    the deterministic due-diligence report (facts from the graph, agent findings verified)
    store.py     Relate persistence: Investigation, ToolCall, Finding and Proposal nodes
    runner.py    the tool-calling loop, its budgets, and the labelled deterministic fallback
"""
