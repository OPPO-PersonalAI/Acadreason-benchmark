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

import time
import json
import concurrent.futures
from pathlib import Path
from typing import Dict, List
from utils.env_utils import load_env_file
from utils.config_utils import load_config
from utils.data_utils import find_matching_files, normalize_query_for_resume
from utils.llm_clients import ClientsRegistry, is_valid_response
from utils.prompt_utils import build_prompt_safe
from utils.judge_utils import (
    parse_judge_response,
    calculate_judge_scores,
    build_authoritative_data_cache,
    supplement_missing_fields,
)
from tqdm import tqdm


# Extract query with multi-source fallback
def extract_query(item: Dict) -> str:
    q = item.get('query') or item.get('question') or item.get('input', {}).get('query') or item.get('original_query') or item.get('prompt')
    return q or ""


# Judge experiment
def run_judge_experiment(config_path: str, experiment_name: str, data_path_override: str = None, limit: int = None, resume: bool = True, models_override: List[str] = None) -> List[Dict]:
    # Step 1: Initialize environment and configuration
    load_env_file()  # Load environment variable file
    config = load_config(config_path)  # Load main configuration file
    exp_config = config['experiments'][experiment_name]  # Get experiment configuration
    models = models_override if models_override else exp_config['models']  # Determine model list to use
    original_bench_data = exp_config.get('original_bench_data', None)
    prompt_file = exp_config['prompt_file']  # Get prompt template file path
    input_field = exp_config.get('input_field', 'response')  # Get field to judge

    # Step 2: Read judge prompt template
    with open(prompt_file, 'r', encoding='utf-8') as f:
        prompt_template = f.read().strip()

    # Step 3: Determine data file path and validate
    data_path = data_path_override or exp_config.get('input_data')
    if not data_path:
        raise ValueError(f"Experiment '{experiment_name}' has no input_data configured, and no --data parameter specified")

    # Optional: Load original bench data cache (for supplementing fields like checklist/golden_truth etc.)
    authoritative_cache = build_authoritative_data_cache(original_bench_data) if original_bench_data else {}

    # Step 4: Find matching data files
    matching_files = find_matching_files(data_path, for_judge=True)
    if not matching_files:
        raise FileNotFoundError(f"No files found matching pattern '{data_path}'")

    # Step 5: Initialize LLM client registry and statistics container
    clients = ClientsRegistry(config)
    all_stats: List[Dict] = []

    # Step 6: Set up output directory structure (only needs to be calculated once)
    output_config = config.get('defaults', {}).get('output_config', {})
    infer_dir = output_config.get('infer_dir', 'results/infer')
    judge_dir = output_config.get('judge_dir') or str(Path(infer_dir).parent / 'judge')
    base_judge_dir = Path(judge_dir)

    # Step 7: Begin iterating through each model for judging
    for model_name in models:
        model_stats = []  # Current model's statistics
        # Step 8: Iterate through each matching data file
        for file_path in matching_files:
            # Step 8.1: Set up file-specific output paths and log paths
            file_name = Path(file_path).stem  # Get filename without extension
            experiment_dir = base_judge_dir / experiment_name  # Experiment output directory
            experiment_dir.mkdir(parents=True, exist_ok=True)  # Create directory
            output_filename = f"judged_{file_name}_{model_name}.jsonl"  # Judge result filename
            output_path = experiment_dir / output_filename  # Complete output path
            error_log_dir = experiment_dir / "error_logs"  # Error log directory
            error_log_dir.mkdir(parents=True, exist_ok=True)  # Create error log directory
            error_log_path = error_log_dir / f"{file_name}_{model_name}_errors.jsonl"  # Error log path
            skip_log_path = error_log_dir / f"{file_name}_{model_name}_skipped.jsonl"  # Skipped entries log path

            # Step 8.2: Ensure output file exists (create empty file)
            with open(output_path, 'a', encoding='utf-8') as _f:
                pass

            # Step 8.3: Handle resume functionality - read already processed entries
            processed = set()  # Set of processed entries
            if resume and output_path.exists():
                with open(output_path, 'r', encoding='utf-8') as f:
                    for line in f:
                        if line.strip():
                            try:
                                r = json.loads(line.strip())
                                q = extract_query(r)  # Extract query content
                                nq = normalize_query_for_resume(q)  # Normalize query for comparison
                                if nq and (r.get('success') is True):
                                    processed.add(nq)  # Add to processed set
                            except Exception:
                                pass  # Ignore parsing errors in lines

            # Step 8.4: Load data file (line-by-line reading to save memory)
            data: List[Dict] = []
            with open(file_path, 'r', encoding='utf-8') as f:
                for line in f:
                    if line.strip():
                        item = json.loads(line.strip())
                        data.append(item)
                        if limit and len(data) >= limit:  # Stop after limit if set
                            break

            # Step 8.5: Filter out entries that need processing (exclude already processed)
            remaining = [(i, it) for i, it in enumerate(data) if normalize_query_for_resume(extract_query(it)) not in processed]
            total_items = len(remaining)  # Total entries to process

            # Step 8.6: Initialize counters and configuration
            defaults = config['defaults']
            successful_count = 0  # Success count
            failed_count = 0  # Failure count
            skipped_count = 0  # Skip count

            # Step 8.7: Define worker function - process single data entry for judging
            def worker(item_data):
                index, item = item_data
                # Check if input field is valid
                if not is_valid_response(item.get(input_field, '')):
                    return {"skipped": True, "skip_reason": f"{input_field} field is empty or invalid", "success": False, **item}
                
                # Use original bench cache to supplement fields (like checklist/golden_truth/title etc.)
                enriched_item = supplement_missing_fields(item, authoritative_cache) if authoritative_cache else item

                # Build judge prompt (use safe template rendering, missing fields fallback, prioritize bench supplement, then multi-source fallback)
                # Ensure {response} in template definitely uses input_field content
                fallback_query = (
                    enriched_item.get('query')
                    or enriched_item.get('question')
                    or enriched_item.get('title')
                    or enriched_item.get('prompt')
                    or ''
                )
                prompt = build_prompt_safe(prompt_template, {
                    **enriched_item,
                    'query': fallback_query,
                    'checklist': enriched_item.get('checklist', ''),
                    'golden_truth': enriched_item.get('golden_truth', ''),
                    'response': item.get(input_field, '')
                })
                
                # Call LLM for judging
                response = clients.call_llm(model_name, prompt, return_json=exp_config.get('return_json', False))
                
                # Parse judge response
                parsed = parse_judge_response(response)
                judge_success = is_valid_response(response) and parsed["parse_success"]
                
                # Calculate scores - simplify aspect1/2 statistics to string ratio format
                if parsed["parse_success"] and parsed["parsed_scores"]:
                    jd = parsed["parsed_scores"]
                    # Calculate aspect1 score ratio
                    aspect1_ratio = "1/1" if (isinstance(jd.get('aspect_1_score', 0), (int, float)) and jd.get('aspect_1_score', 0) > 0) else "0/1"
                    
                    # Calculate aspect2 score ratio
                    aspect2_scores = jd.get('aspect_2_scores', [])
                    aspect2_total = 0
                    for score_item in aspect2_scores:
                        for key, value in score_item.items():
                            if key.endswith('_score') and isinstance(value, (int, float)):
                                aspect2_total += value
                    
                    # Calculate checklist total as denominator
                    num_checklist = len([1 for s in aspect2_scores for k in s.keys() if k.endswith('_score')]) or len(aspect2_scores)
                    aspect2_ratio = f"{int(aspect2_total)}/{int(num_checklist)}"
                    scores_obj = {"aspect1": aspect1_ratio, "aspect2": aspect2_ratio}
                else:
                    # Default scores when parsing fails
                    scores_obj = {"aspect1": "0/1", "aspect2": "0/0", "parse_error": parsed.get("parse_error")}

                # Generate timestamp
                lt = time.localtime()
                ts_str = f"{lt.tm_mon:02d}/{lt.tm_mday:02d}/{lt.tm_hour:02d}/{lt.tm_min:02d}"
                
                # Return judge result
                return {
                    "task_id": enriched_item.get('task_id', ''),
                    "model": model_name,
                    "category": enriched_item.get('domain'),  # Prioritize supplemented category
                    "query": extract_query(item),
                    "response": item.get(input_field, ''),
                    "judge_prompt": prompt,
                    "judge_parsed": parsed.get("parsed_scores"),
                    "scores": scores_obj,
                    "num_checklist": int(scores_obj.get('aspect2', '0/0').split('/')[-1]) if isinstance(scores_obj.get('aspect2'), str) and '/' in scores_obj.get('aspect2') else 0,
                    "success": judge_success,
                    "judge_success": judge_success,
                    "timestamp": ts_str
                }

            # Step 8.8: Use thread pool to execute judge tasks concurrently
            with concurrent.futures.ThreadPoolExecutor(max_workers=defaults['max_workers']) as executor:
                # Use progress bar to display processing progress
                with tqdm(total=total_items, desc=f"Judge {Path(file_path).name}") as pbar:
                    # Execute worker function concurrently to process each data entry
                    for result in executor.map(worker, remaining):
                        # Step 8.9: Save based on processing result classification
                        if result.get('success') is True:
                            # Successful judge results save to main output file
                            with open(output_path, 'a', encoding='utf-8') as f:
                                f.write(json.dumps(result, ensure_ascii=False) + '\n')
                            successful_count += 1
                        elif result.get('skipped') is True:
                            # Skipped entries save to skip log file
                            with open(skip_log_path, 'a', encoding='utf-8') as f:
                                f.write(json.dumps(result, ensure_ascii=False) + '\n')
                            skipped_count += 1
                        else:
                            # Failed entries build error information and save to error log file
                            err = {
                                "file": file_path,
                                "model": model_name,
                                "success": False,
                                "skipped": result.get('skipped', False),
                                "parse_error": (result.get('scores') or {}).get('parse_error') if isinstance(result.get('scores'), dict) else None,
                                "error": result.get('error'),
                                "judge_parsed": result.get('judge_parsed'),
                                "response": result.get('response'),
                                "timestamp": time.time(),
                            }
                            with open(error_log_path, 'a', encoding='utf-8') as f:
                                f.write(json.dumps(err, ensure_ascii=False) + '\n')
                            failed_count += 1
                        
                        # Update progress bar
                        pbar.update(1)
                        pbar.set_postfix({'Success': successful_count, 'Failed': failed_count, 'Skipped': skipped_count})

            # Step 8.10: Collect current file statistics
            file_stats = {
                "input_file": str(file_path),
                "output_file": str(output_path),
                "configured_total": len(data),
                "successful_this_run": successful_count,
                "failed_this_run": failed_count,
                "skipped_this_run": skipped_count,
            }
            model_stats.append(file_stats)

        # Step 8.11: Collect current model statistics
        all_stats.append({"model": model_name, "files_processed": len(matching_files), "file_stats": model_stats})

    # Step 9: Return all models' statistics results
    return all_stats


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Run judge experiment (utils.process_judge)")
    parser.add_argument("--experiment", default="judge_infer_50_hints0", required=True, help="Experiment name")
    parser.add_argument("--data", help="Data file path (optional, overrides config file settings)")
    parser.add_argument("--models", help="Specify model list (comma-separated), overrides config file settings")
    parser.add_argument("--limit", default=1, type=int, help="Limit processing quantity (for testing)")
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
