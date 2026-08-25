import json
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
from app.services.retrieval import retrieve

DATASET = [
    {"query": "test", "expected_doc": None},
]

