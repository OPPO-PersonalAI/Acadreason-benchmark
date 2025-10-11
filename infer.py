#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Standalone inference entry point.
Example:
  python infer.py --experiment exp1_basic_qa --limit 10
"""

import argparse
from utils.process_infer import run_infer_experiment


def main():
    parser = argparse.ArgumentParser(description="LLM Inference Entry Point")
    parser.add_argument("--experiment", required=True, help="Experiment name")
    parser.add_argument("--data", help="Data file path (optional, overrides config file setting)")
    parser.add_argument("--models", help="Specify model list (comma-separated), overrides config file setting")
    parser.add_argument("--limit", type=int, help="Limit processing count (for testing)")
    parser.add_argument("--no-resume", action="store_true", help="Disable resume functionality")
    parser.add_argument("--config", default="config.yaml", help="Configuration file path")
    args = parser.parse_args()

    models_override = [m.strip() for m in args.models.split(',')] if args.models else None
    stats = run_infer_experiment(
        config_path=args.config,
        experiment_name=args.experiment,
        data_path_override=args.data,
        limit=args.limit,
        resume=not args.no_resume,
        models_override=models_override,
    )
    # Print summary
    for s in stats:
        print(f"{s['model']}: {s['successful']}/{s['total']} ({s['success_rate']:.1%}) -> {s['output_file']}")


if __name__ == "__main__":
    main()


