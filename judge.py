#!/usr/bin/env python
# coding=utf-8
# Copyright 2025 The OPPO Inc. PersonalAI team. All rights reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""
Standalone judge entry point.
Example:
  python judge.py --experiment judge_quality --limit 10
"""

import argparse
from utils.process_judge import run_judge_experiment


def main():
    parser = argparse.ArgumentParser(description="LLM judge entry point")
    parser.add_argument("--experiment", default="judge_infer_50_hints0", help="Experiment name")
    parser.add_argument("--data", help="Data file path (optional, overrides config file settings)")
    parser.add_argument("--models", help="Specify model list (comma-separated), overrides config file settings")
    parser.add_argument("--limit", type=int, help="Limit processing quantity (for testing)")
    parser.add_argument("--no-resume", action="store_true", help="Disable resume functionality")
    parser.add_argument("--config", default="config.yaml", help="Configuration file path")
    args = parser.parse_args()

    models_override = [m.strip() for m in args.models.split(',')] if args.models else None
    stats = run_judge_experiment(
        config_path=args.config,
        experiment_name=args.experiment,
        data_path_override=args.data,
        limit=args.limit,
        resume=not args.no_resume,
        models_override=models_override,
    )
    for s in stats:
        print(f"Model {s['model']} processed {s['files_processed']} files:")
        for file_stat in s.get('file_stats', []):
            input_file = file_stat.get('input_file', 'Unknown input')
            output_file = file_stat.get('output_file', 'Unknown output')
            configured_total = file_stat.get('configured_total', 0)
            success = file_stat.get('successful_this_run', 0)
            failed = file_stat.get('failed_this_run', 0)
            skipped = file_stat.get('skipped_this_run', 0)

            print(f"  - Input: {input_file}")
            print(f"    Output: {output_file}")
            print(f"    Configured total: {configured_total}")
            print(f"    Current run results: success {success}, failed {failed}, skipped {skipped}")


if __name__ == "__main__":
    main()
