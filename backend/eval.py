import json
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
from app.services.retrieval import retrieve

DATASET = [
    {"query": "test", "expected_doc": None},
]

def recall_at_k(k=5):
    hits = 0
    evaluated = 0
    for item in DATASET:
        if item["expected_doc"] is None:
            continue
        evaluated += 1
        res = retrieve(1, item["query"], top_k=k)
        if any(r.get("file_name") == item["expected_doc"] for r in res):
            hits += 1
    if evaluated == 0:
        print(f"Recall@{k}: no labeled queries in DATASET")
        return
    print(f"Recall@{k}: {hits}/{evaluated}")

if __name__ == "__main__":
    recall_at_k(5)
    print("Eval harness ready. Populate DATASET with labeled queries.")
