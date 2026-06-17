import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.retrieval_eval import evaluate_retrieval_file


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate saved retrieval results against a golden set.")
    parser.add_argument("path", help="Path to a JSON file containing retrieval cases.")
    parser.add_argument("--k", type=int, default=5, help="Cutoff for precision/recall/coverage.")
    args = parser.parse_args()

    result = evaluate_retrieval_file(args.path, k=args.k)
    print(json.dumps(result.__dict__, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
