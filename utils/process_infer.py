import time
import json
import concurrent.futures
from pathlib import Path
from typing import Dict, List

from utils.env_utils import load_env_file
from utils.config_utils import load_config
from utils.data_utils import load_data, normalize_query_for_resume
from utils.prompt_utils import build_prompt_infer, build_prompt_safe
from utils.llm_clients import ClientsRegistry, is_valid_response
from tqdm import tqdm


def run_infer_experiment(config_path: str, experiment_name: str, data_path_override: str = None, limit: int = None, resume: bool = True, models_override: List[str] = None) -> List[Dict]:
    load_env_file()
    config = load_config(config_path)
    exp_config = config['experiments'][experiment_name]
    models = models_override if models_override else exp_config['models']
    prompt_file = exp_config['prompt_file']

    data_path = data_path_override or exp_config.get('input_data')
    if not data_path:
        raise ValueError(f"实验 '{experiment_name}' 没有配置input_data，且未通过--data参数指定")

    with open(prompt_file, 'r', encoding='utf-8') as f:
        prompt_template = f.read().strip()

    data = load_data(data_path)
    if limit:
        data = data[:limit]

    clients = ClientsRegistry(config)

    all_stats = []
    for model_name in models:
        model_config = clients.clients.get(model_name)
        if not model_config:
            continue

        output_config = config['defaults']['output_config']
        base_infer_dir = Path(output_config['infer_dir'])
        experiment_dir = base_infer_dir / experiment_name
        experiment_dir.mkdir(parents=True, exist_ok=True)
        output_path = experiment_dir / f"{model_name}.jsonl"
        error_log_dir = experiment_dir / "error_logs"
        error_log_dir.mkdir(parents=True, exist_ok=True)
        error_log_path = error_log_dir / f"{model_name}_errors.jsonl"

        processed = set()
        if resume and output_path.exists():
            with open(output_path, 'r', encoding='utf-8') as f:
                for line in f:
                    if line.strip():
                        try:
                            r = json.loads(line.strip())
                            q = (r.get('query') or r.get('question') or r.get('input', {}).get('query') or r.get('original_query') or "")
                            nq = normalize_query_for_resume(q)
                            if nq and r.get('infer_success'):
                                processed.add(nq)
                        except Exception:
                            pass

        remaining = [(i, item) for i, item in enumerate(data) if normalize_query_for_resume(item.get('query') or item.get('question') or item.get('input', {}).get('query') or "") not in processed]

        successful = 0
        failed = 0
        start = time.time()

        def worker(item_data):
            _, item = item_data
            # 使用安全渲染，缺失字段自动回退为空字符串
            prompt = build_prompt_safe(prompt_template, item)
            resp = clients.call_llm(model_name, prompt)
            return item, prompt, resp

        total_items = len(remaining)
        if total_items == 0:
            stats = {
                'model': model_name,
                'total': 0,
                'successful': 0,
                'failed': 0,
                'success_rate': 0,
                'total_time': 0,
                'avg_time_per_item': 0,
                'output_file': str(output_path)
            }
            all_stats.append(stats)
            continue

        with concurrent.futures.ThreadPoolExecutor(max_workers=config['defaults']['max_workers']) as executor:
            with tqdm(total=total_items, desc=f"Infer {model_name}") as pbar:
                for item, prompt, resp in executor.map(worker, remaining):
                    if is_valid_response(resp):
                        final = {
                            **item,
                            "response": resp,
                            "task_id": item.get('task_id', ''),
                            "model": model_name,
                            "experiment_name": experiment_name,
                            "infer_prompt": prompt,
                            "timestamp": time.time(),
                            "infer_success": True,
                        }
                        with open(output_path, 'a', encoding='utf-8') as f:
                            f.write(json.dumps(final, ensure_ascii=False) + '\n')
                        successful += 1
                    else:
                        err = {
                            "timestamp": time.time(),
                            "experiment_name": experiment_name,
                            "model_name": model_name,
                            "error_type": "THREAD_POOL_FAILED",
                            "error_message": "empty or invalid response",
                            "input_data": item,
                        }
                        with open(error_log_path, 'a', encoding='utf-8') as f:
                            f.write(json.dumps(err, ensure_ascii=False) + '\n')
                        failed += 1
                    pbar.update(1)
                    pbar.set_postfix({'成功': successful, '失败': failed})

        total_time = time.time() - start
        stats = {
            'model': model_name,
            'total': len(remaining),
            'successful': successful,
            'failed': failed,
            'success_rate': successful / len(remaining) if remaining else 0,
            'total_time': total_time,
            'avg_time_per_item': total_time / len(remaining) if remaining else 0,
            'output_file': str(output_path)
        }
        all_stats.append(stats)

    return all_stats


def main():
    print("process_infer: 使用 run_infer_experiment() 运行推理实验。")


if __name__ == "__main__":
    main()


