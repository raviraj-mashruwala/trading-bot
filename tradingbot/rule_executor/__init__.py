"""Rule-based executor: a separate, slimmed copy of the plan executor for fixed rules.

It reuses the broker contract, OrderManager, the paper broker and the Kite client
unchanged, and never touches tradingbot.executor. One rule per session, decided from
market data at the open instead of from an LLM plan written the night before.
"""
