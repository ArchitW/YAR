import json
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
from app.services.retrieval import retrieve

DATASET = [
    {"query": "test", "expected_doc": None},
]

def recall_at_k(k=5):
    hits = 0
    total = len(DATASET)
    for item in DATASET:
        res = retrieve(1, item["query"], top_k=k)
        if item["expected_doc"] is None:
            continue
        if any(r.get("file_name") == item["expected_doc"] for r in res):
            hits += 1
    print(f"Recall@{k}: {hits}/{total}")

if __name__ == "__main__":
    recall_at_k(5)
    print("Eval harness ready. Populate DATASET with labeled queries.")
