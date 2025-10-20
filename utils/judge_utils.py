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

import json
from typing import Dict, Any, Union, List, Optional
from utils.data_utils import normalize_query_for_resume

def is_valid_response(response) -> bool:
    if response is None:
        return False
    if isinstance(response, str):
        return bool(response.strip())
    if isinstance(response, dict):
        return bool(response)
    return True


def _count_checklist_items(checklist_value: Any) -> int:
    if isinstance(checklist_value, list):
        return len(checklist_value)
    if isinstance(checklist_value, str):
        parts = [p.strip() for p in checklist_value.split('|')]
        return len([p for p in parts if p])
    return 0


def parse_judge_response(response: Union[str, Dict]) -> Dict:
    parsed_result = {
        "raw_response": response,
        "parsed_scores": None,
        "parse_success": False,
        "parse_error": None,
        "score_summary": None
    }
    try:
        judge_data = response if isinstance(response, dict) else json.loads(response) if isinstance(response, str) else None
        if judge_data and isinstance(judge_data, dict):
            if "aspect_2_scores" not in judge_data:
                import re
                idxs = set()
                for k in judge_data.keys():
                    m = re.match(r'^aspect_2_(?:analysis|score)_(\d+)$', k)
                    if m:
                        try:
                            idxs.add(int(m.group(1)))
                        except Exception:
                            pass
                if idxs:
                    items = []
                    for i in sorted(idxs):
                        items.append({
                            f"item_{i}_analysis": judge_data.get(f"aspect_2_analysis_{i}", ""),
                            f"item_{i}_score": judge_data.get(f"aspect_2_score_{i}", 0)
                        })
                    judge_data["aspect_2_scores"] = items

            required_fields = ["aspect_1_analysis", "aspect_1_score", "aspect_2_scores"]
            if all(field in judge_data for field in required_fields):
                parsed_result["parsed_scores"] = judge_data
                parsed_result["parse_success"] = True
            else:
                parsed_result["parse_error"] = f"Missing required fields: {[f for f in required_fields if f not in judge_data]}"
        else:
            parsed_result["parse_error"] = "Unable to parse as valid JSON dict"
    except json.JSONDecodeError as e:
        parsed_result["parse_error"] = f"JSON parsing error: {str(e)}"
    except Exception as e:
        parsed_result["parse_error"] = f"Parsing exception: {str(e)}"
    return parsed_result


def calculate_judge_scores(judge_data: Dict, num_checklist: int) -> Dict:
    try:
        aspect_1_score = judge_data.get("aspect_1_score", 0)
        aspect_2_scores = judge_data.get("aspect_2_scores", [])
        aspect_2_individual_scores: List[int] = []
        for score_item in aspect_2_scores:
            for key, value in score_item.items():
                if key.endswith("_score"):
                    aspect_2_individual_scores.append(int(value))
        aspect_2_total = sum(aspect_2_individual_scores)
        aspect_2_max = num_checklist
        total_score = aspect_1_score + aspect_2_total
        total_max = 2 + num_checklist
        return {
            "aspect_1": {
                "score": aspect_1_score,
                "max_score": 2,
                "percentage": (aspect_1_score / 2) * 100 if aspect_1_score is not None else 0
            },
            "aspect_2": {
                "individual_scores": aspect_2_individual_scores,
                "total_score": aspect_2_total,
                "max_score": aspect_2_max,
                "num_items": len(aspect_2_individual_scores),
                "expected_items": num_checklist,
                "percentage": (aspect_2_total / aspect_2_max) * 100 if aspect_2_max > 0 else 0
            },
            "overall": {
                "total_score": total_score,
                "max_score": total_max,
                "percentage": (total_score / total_max) * 100 if total_max > 0 else 0
            }
        }
    except Exception as e:
        return {
            "error": f"Score calculation error: {str(e)}",
            "aspect_1": {"score": 0, "max_score": 2, "percentage": 0},
            "aspect_2": {"total_score": 0, "max_score": 0, "percentage": 0},
            "overall": {"total_score": 0, "max_score": 0, "percentage": 0}
        }


def extract_query_compat(item: Dict) -> str:
    q = (
        item.get('query')
        or item.get('question')
        or item.get('input', {}).get('query')
        or item.get('original_query')
        or item.get('prompt')
    )
    return q or ""


def build_num_checklist_map_from_file(source_path: str = "data/raw/bench_50.jsonl") -> Dict[str, int]:
    mapping: Dict[str, int] = {}
    try:
        import os
        if not (os.path.exists(source_path) and os.path.isfile(source_path)):
            return mapping
        with open(source_path, 'r', encoding='utf-8') as f:
            for line in f:
                if not line.strip():
                    continue
                try:
                    obj = json.loads(line.strip())
                except Exception:
                    continue
                num_chk = obj.get('num_checklist')
                if not isinstance(num_chk, int) or num_chk <= 0:
                    continue
                for field_name in ['query', 'question', 'hints_background', 'title', 'golden_truth']:
                    field_value = obj.get(field_name, '')
                    if field_value:
                        norm_key = normalize_query_for_resume(str(field_value))
                        if norm_key:
                            mapping[norm_key] = int(num_chk)
        return mapping
    except Exception:
        return {}


def build_authoritative_data_cache(source_path: str = "data/raw/bench_50.jsonl") -> Dict[str, Dict[str, Any]]:
    """Build authoritative data cache from source file"""
    cache: Dict[str, Dict[str, Any]] = {}
    try:
        import os
        if not (os.path.exists(source_path) and os.path.isfile(source_path)):
            return cache
        with open(source_path, 'r', encoding='utf-8') as f:
            for line in f:
                if not line.strip():
                    continue
                try:
                    obj = json.loads(line.strip())
                except Exception:
                    continue
                for field_name in ['query', 'question', 'hints_background', 'title', 'golden_truth']:
                    field_value = obj.get(field_name, '')
                    if field_value:
                        norm_key = normalize_query_for_resume(str(field_value))
                        if norm_key:
                            cache[norm_key] = obj
        return cache
    except Exception:
        return {}


def get_num_checklist_for_item(item: Dict[str, Any], num_map: Dict[str, int]) -> int:
    try:
        for field_name in ['query', 'question', 'hints_background', 'title', 'golden_truth']:
            field_value = extract_query_compat(item) if field_name == 'query' else item.get(field_name, '')
            if not field_value:
                continue
            norm_key = normalize_query_for_resume(str(field_value))
            if norm_key and norm_key in num_map:
                return int(num_map[norm_key])
        return 0
    except Exception:
        return 0


def supplement_missing_fields(item: Dict[str, Any], cache: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    try:
        # Prioritize existing fields (include prompt as fallback for AFM output compatibility)
        candidate_keys = ['query', 'question', 'hints_background', 'title', 'golden_truth', 'prompt']
        authoritative_record: Optional[Dict[str, Any]] = None
        for field_name in candidate_keys:
            field_value = extract_query_compat(item) if field_name == 'query' else item.get(field_name, '')
            if not field_value:
                continue
            norm_key = normalize_query_for_resume(str(field_value))
            if norm_key and norm_key in cache:
                authoritative_record = cache[norm_key]
                break

        # If still no match, try matching by id/task_id (for AFM id field compatibility)
        if not authoritative_record:
            possible_ids = [item.get('task_id'), item.get('id'), item.get('taskId')]
            item_task_id: Optional[int] = None
            for pid in possible_ids:
                if pid is None:
                    continue
                try:
                    item_task_id = int(pid)
                    break
                except Exception:
                    continue
            if item_task_id is not None:
                for record in cache.values():
                    try:
                        if int(record.get('task_id', -1)) == item_task_id:
                            authoritative_record = record
                            break
                    except Exception:
                        continue
        if not authoritative_record:
            return item
        supplemented_item = authoritative_record.copy()
        supplemented_item.update(item)
        return supplemented_item
    except Exception:
        return item


def main():
    demo = {
        "aspect_1_analysis": "ok",
        "aspect_1_score": 2,
        "aspect_2_scores": [{"item_1_score": 1}, {"item_2_score": 0}]
    }
    parsed = parse_judge_response(json.dumps(demo))
    print("judge_utils: parse_success=", parsed["parse_success"])


if __name__ == "__main__":
    main()
