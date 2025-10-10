import os
import json
import glob
from pathlib import Path
from typing import List, Dict


def find_matching_files(pattern: str, for_judge: bool = False) -> List[str]:
    """根据模式匹配文件，支持文件夹输入"""
    matching_files = []

    if os.path.exists(pattern):
        if os.path.isfile(pattern):
            return [pattern]
        elif os.path.isdir(pattern):
            folder_path = Path(pattern)
            jsonl_files = list(folder_path.rglob("*.jsonl"))
            jsonl_files = [f for f in jsonl_files if "error_logs" not in str(f)]
            return [str(f) for f in sorted(jsonl_files)]

    experiment_folder_path = Path("results/infer") / pattern
    if experiment_folder_path.exists() and experiment_folder_path.is_dir():
        jsonl_files = list(experiment_folder_path.rglob("*.jsonl"))
        jsonl_files = [f for f in jsonl_files if "error_logs" not in str(f)]
        return [str(f) for f in sorted(jsonl_files)]

    search_patterns = [pattern, f"{pattern}*.jsonl", f"*{pattern}*.jsonl"]

    if for_judge:
        search_dirs = ["results/infer/"]
        infer_base = Path("results/infer/")
        if infer_base.exists():
            for exp_dir in infer_base.iterdir():
                if exp_dir.is_dir():
                    search_dirs.append(str(exp_dir) + "/")
    else:
        search_dirs = [".", "results/infer/", "results/judge/", "data/raw/"]
        for base_dir in ["results/infer/", "results/judge/"]:
            base_path = Path(base_dir)
            if base_path.exists():
                for exp_dir in base_path.iterdir():
                    if exp_dir.is_dir():
                        search_dirs.append(str(exp_dir) + "/")

    for search_dir in search_dirs:
        if os.path.exists(search_dir):
            for search_pattern in search_patterns:
                full_pattern = os.path.join(search_dir, search_pattern)
                matches = glob.glob(full_pattern)
                matching_files.extend(matches)

    matching_files = sorted(list(set(matching_files)))
    return matching_files


def load_data_multi_files(data_path: str, limit: int = None) -> List[Dict]:
    matching_files = find_matching_files(data_path)
    if not matching_files:
        raise FileNotFoundError(f"未找到匹配模式 '{data_path}' 的文件")

    all_data = []
    for file_path in matching_files:
        file_data = []
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                for line in f:
                    if line.strip():
                        item = json.loads(line.strip())
                        item['_source_file'] = file_path
                        file_data.append(item)
                        if limit and len(all_data) + len(file_data) >= limit:
                            break
            all_data.extend(file_data)
            if limit and len(all_data) >= limit:
                break
        except Exception:
            continue
    return all_data


def load_data(data_path: str, limit: int = None) -> List[Dict]:
    if os.path.exists(data_path) and os.path.isfile(data_path):
        data = []
        with open(data_path, 'r', encoding='utf-8') as f:
            for line in f:
                if line.strip():
                    data.append(json.loads(line.strip()))
                    if limit and len(data) >= limit:
                        break
        return data
    return load_data_multi_files(data_path, limit)


def normalize_query_for_resume(query: str) -> str:
    if not query:
        return ""
    normalized = ' '.join(query.split())
    import re
    normalized = re.sub(r'\s*\|\s*', ' ', normalized)
    normalized = re.sub(r'\b\d+\.\s+', '', normalized)
    normalized = ' '.join(normalized.split())
    return normalized.strip()


def process_gemini_deepsearch_response(response: str) -> str:
    """去除<think>...</think>块（多行）。"""
    if not response or not isinstance(response, str):
        return response
    import re
    think_pattern = r'<think>.*?</think>'
    if re.search(think_pattern, response, re.IGNORECASE | re.DOTALL):
        processed = re.sub(think_pattern, '', response, flags=re.IGNORECASE | re.DOTALL)
        return processed.strip()
    return response


def main():
    """非常简单的命令行入口：列出匹配到的 .jsonl 文件。"""
    import argparse
    parser = argparse.ArgumentParser(description="data_utils: 简单文件匹配演示")
    parser.add_argument(
        "pattern",
        nargs="?",
        default="results/infer",
        help="文件/文件夹/实验名/通配符，默认 results/infer",
    )
    parser.add_argument(
        "--judge",
        action="store_true",
        help="仅在 infer 结果目录及其子目录下匹配（评测场景）",
    )
    args = parser.parse_args()

    files = find_matching_files(args.pattern, for_judge=args.judge)
    if not files:
        print(f"未找到匹配模式 '{args.pattern}' 的文件。")
        return

    print(f"共找到 {len(files)} 个匹配文件：")
    for p in files:
        print(p)


if __name__ == "__main__":
    main()


