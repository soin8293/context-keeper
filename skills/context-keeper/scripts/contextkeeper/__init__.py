"""Context Keeper: a small, deterministic tool that keeps project context and
hands over the right slice for a task.

Five jobs:
  ingest        -> scan the project's docs into records (nobody types by hand)
  save          -> add records (decisions, constraints, facts, state)
  keep-current  -> correct/supersede without deleting; never lose the original
  find          -> search the current view
  hand over     -> build a bounded, source-linked brief and check its freshness
"""
from .store import Store, KINDS, ContextError  # noqa: F401
from .brief import build_brief, diff_snapshot, extract_snapshot  # noqa: F401
from .ingest import MAX_FILE_BYTES, discover_files, extract_items, ingest  # noqa: F401

__version__ = "0.4.1"
