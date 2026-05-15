"""Token Accuracy Plugin — real tokenizer support (tiktoken first) via monkey-patch.

Replaces the char/2.5 heuristic for far more accurate budgets on 1M/200k/32k models.
Falls back to learned ratio or heuristic when native tokenizers are unavailable.
"""
