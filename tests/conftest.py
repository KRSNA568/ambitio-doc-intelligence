"""
Shared pytest setup: put the backend package on sys.path so tests can import
processor / retriever / generator / learner / llm directly, the same way
main.py does.
"""

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BACKEND = os.path.join(ROOT, "backend")
EVAL = os.path.join(ROOT, "eval")
for path in (BACKEND, EVAL):
    if path not in sys.path:
        sys.path.insert(0, path)
