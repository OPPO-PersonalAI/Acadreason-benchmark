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

# 提取query多容错处理
def extract_query(item: Dict) -> str:
    q = item.get('query') or item.get('question') or item.get('input', {}).get('query') or item.get('original_query') or item.get('prompt')
    return q or ""

# 评判实验
def run_judge_experiment(config_path: str, experiment_name: str, data_path_override: str = None, limit: int = None, resume: bool = True, models_override: List[str] = None) -> List[Dict]:
    # 步骤1：初始化环境和配置
    load_env_file()  # 加载环境变量文件
    config = load_config(config_path)  # 加载主配置文件
    exp_config = config['experiments'][experiment_name]  # 获取实验配置
    models = models_override if models_override else exp_config['models']  # 确定要使用的模型列表
    original_bench_data = exp_config.get('original_bench_data', None)
    prompt_file = exp_config['prompt_file']  # 获取提示模板文件路径
    input_field = exp_config.get('input_field', 'response')  # 获取需要judge的字段

    # 步骤2：读取评判提示模板
    with open(prompt_file, 'r', encoding='utf-8') as f:
        prompt_template = f.read().strip()

    # 步骤3：确定数据文件路径并验证
    data_path = data_path_override or exp_config.get('input_data')
    if not data_path:
        raise ValueError(f"实验 '{experiment_name}' 没有配置input_data，且未通过--data参数指定")

    # 可选：加载原始bench数据缓存（用于补全字段，如 checklist/golden_truth 等）
    authoritative_cache = build_authoritative_data_cache(original_bench_data) if original_bench_data else {}

    # 步骤4：查找匹配的数据文件
    matching_files = find_matching_files(data_path, for_judge=True)
    if not matching_files:
        raise FileNotFoundError(f"未找到匹配模式 '{data_path}' 的文件")

    # 步骤5：初始化LLM客户端注册器和统计数据容器
    clients = ClientsRegistry(config)
    all_stats: List[Dict] = []

    # 步骤6：设置输出目录结构（只需计算一次）
    output_config = config.get('defaults', {}).get('output_config', {})
    infer_dir = output_config.get('infer_dir', 'results/infer')
    judge_dir = output_config.get('judge_dir') or str(Path(infer_dir).parent / 'judge')
    base_judge_dir = Path(judge_dir)

    # 步骤7：开始遍历每个模型进行评判
    for model_name in models:
        model_stats = []  # 当前模型的统计数据
        # 步骤8：遍历每个匹配的数据文件
        for file_path in matching_files:
            # 步骤8.1：设置文件特定的输出路径和日志路径
            file_name = Path(file_path).stem  # 获取文件名（不含扩展名）
            experiment_dir = base_judge_dir / experiment_name  # 实验输出目录
            experiment_dir.mkdir(parents=True, exist_ok=True)  # 创建目录
            output_filename = f"judged_{file_name}_{model_name}.jsonl"  # 评判结果文件名
            output_path = experiment_dir / output_filename  # 完整输出路径
            error_log_dir = experiment_dir / "error_logs"  # 错误日志目录
            error_log_dir.mkdir(parents=True, exist_ok=True)  # 创建错误日志目录
            error_log_path = error_log_dir / f"{file_name}_{model_name}_errors.jsonl"  # 错误日志路径
            skip_log_path = error_log_dir / f"{file_name}_{model_name}_skipped.jsonl"  # 跳过条目日志路径

            # 步骤8.2：确保输出文件存在（创建空文件）
            with open(output_path, 'a', encoding='utf-8') as _f:
                pass

            # 步骤8.3：处理断点续传功能 - 读取已处理的条目
            processed = set()  # 已处理条目的集合
            if resume and output_path.exists():
                with open(output_path, 'r', encoding='utf-8') as f:
                    for line in f:
                        if line.strip():
                            try:
                                r = json.loads(line.strip())
                                q = extract_query(r)  # 提取查询内容
                                nq = normalize_query_for_resume(q)  # 标准化查询用于比较
                                if nq and (r.get('success') is True):
                                    processed.add(nq)  # 添加到已处理集合
                            except Exception:
                                pass  # 忽略解析错误的行

            # 步骤8.4：加载数据文件（逐行读取以节省内存）
            data: List[Dict] = []
            with open(file_path, 'r', encoding='utf-8') as f:
                for line in f:
                    if line.strip():
                        item = json.loads(line.strip())
                        data.append(item)
                        if limit and len(data) >= limit:  # 如果设置了限制，则达到限制后停止
                            break

            # 步骤8.5：筛选出需要处理的条目（排除已处理的）
            remaining = [(i, it) for i, it in enumerate(data) if normalize_query_for_resume(extract_query(it)) not in processed]
            total_items = len(remaining)  # 待处理条目总数

            # 步骤8.6：初始化计数器和配置
            defaults = config['defaults']
            successful_count = 0  # 成功计数
            failed_count = 0  # 失败计数
            skipped_count = 0  # 跳过计数

            # 步骤8.7：定义工作函数 - 处理单个数据条目的评判
            def worker(item_data):
                index, item = item_data
                # 检查输入字段是否有效
                if not is_valid_response(item.get(input_field, '')):
                    return {"skipped": True, "skip_reason": f"{input_field} field is empty or invalid", "success": False, **item}
                
                # 使用原始bench缓存补全字段（如 checklist/golden_truth/title 等）
                enriched_item = supplement_missing_fields(item, authoritative_cache) if authoritative_cache else item

                # 构建评判提示（使用安全模板渲染，缺失字段回退，优先 bench 补全，再多源兜底）
                # 确保模板中需要的 {response} 一定使用 input_field 的内容
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
                
                # 调用LLM进行评判
                response = clients.call_llm(model_name, prompt, return_json=exp_config.get('return_json', False))
                
                # 解析评判响应
                parsed = parse_judge_response(response)
                judge_success = is_valid_response(response) and parsed["parse_success"]
                
                # 计算评分 - 将aspect1/2统计简化为字符串比例格式
                if parsed["parse_success"] and parsed["parsed_scores"]:
                    jd = parsed["parsed_scores"]
                    # 计算aspect1得分比例
                    aspect1_ratio = "1/1" if (isinstance(jd.get('aspect_1_score', 0), (int, float)) and jd.get('aspect_1_score', 0) > 0) else "0/1"
                    
                    # 计算aspect2得分比例
                    aspect2_scores = jd.get('aspect_2_scores', [])
                    aspect2_total = 0
                    for score_item in aspect2_scores:
                        for key, value in score_item.items():
                            if key.endswith('_score') and isinstance(value, (int, float)):
                                aspect2_total += value
                    
                    # 计算检查项总数作为分母
                    num_checklist = len([1 for s in aspect2_scores for k in s.keys() if k.endswith('_score')]) or len(aspect2_scores)
                    aspect2_ratio = f"{int(aspect2_total)}/{int(num_checklist)}"
                    scores_obj = {"aspect1": aspect1_ratio, "aspect2": aspect2_ratio}
                else:
                    # 解析失败时的默认评分
                    scores_obj = {"aspect1": "0/1", "aspect2": "0/0", "parse_error": parsed.get("parse_error")}

                # 生成时间戳
                lt = time.localtime()
                ts_str = f"{lt.tm_mon:02d}/{lt.tm_mday:02d}/{lt.tm_hour:02d}/{lt.tm_min:02d}"
                
                # 返回评判结果
                return {
                    "task_id": enriched_item.get('task_id', ''),
                    "model": model_name,
                    "category": enriched_item.get('domain'),  # 优先使用补全后的category
                    # "title": enriched_item.get('title') or item.get('title'),
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

            # 步骤8.8：使用线程池并发执行评判任务
            with concurrent.futures.ThreadPoolExecutor(max_workers=defaults['max_workers']) as executor:
                # 使用进度条显示处理进度
                with tqdm(total=total_items, desc=f"Judge {Path(file_path).name}") as pbar:
                    # 并发执行worker函数处理每个数据条目
                    for result in executor.map(worker, remaining):
                        # 步骤8.9：根据处理结果分类保存
                        if result.get('success') is True:
                            # 成功的评判结果保存到主输出文件
                            with open(output_path, 'a', encoding='utf-8') as f:
                                f.write(json.dumps(result, ensure_ascii=False) + '\n')
                            successful_count += 1
                        elif result.get('skipped') is True:
                            # 跳过的条目保存到跳过日志文件
                            with open(skip_log_path, 'a', encoding='utf-8') as f:
                                f.write(json.dumps(result, ensure_ascii=False) + '\n')
                            skipped_count += 1
                        else:
                            # 失败的条目构建错误信息并保存到错误日志文件
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
                        
                        # 更新进度条
                        pbar.update(1)
                        pbar.set_postfix({'成功': successful_count, '失败': failed_count, '跳过': skipped_count})

            # 步骤8.10：收集当前文件的统计信息
            file_stats = {
                "input_file": str(file_path),
                "output_file": str(output_path),
                "configured_total": len(data),
                "successful_this_run": successful_count,
                "failed_this_run": failed_count,
                "skipped_this_run": skipped_count,
            }
            model_stats.append(file_stats)

        # 步骤8.11：收集当前模型的统计信息
        all_stats.append({"model": model_name, "files_processed": len(matching_files), "file_stats": model_stats})

    # 步骤9：返回所有模型的统计结果
    return all_stats


def main():
    import argparse
    parser = argparse.ArgumentParser(description="运行评判实验（utils.process_judge）")
    parser.add_argument("--experiment", default="judge_infer_50_hints0", required=True, help="实验名称")
    parser.add_argument("--data", help="数据文件路径（可选，覆盖配置文件中的设置）")
    parser.add_argument("--models", help="指定模型列表（逗号分隔），覆盖配置文件中的设置")
    parser.add_argument("--limit", default=1, type=int, help="限制处理数量（用于测试）")
    parser.add_argument("--no-resume", action="store_true", help="禁用Resume功能")
    parser.add_argument("--config", default="config.yaml", help="配置文件路径")
    args =parser.parse_args()

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
        print(f"模型 {s['model']} 处理 {s['files_processed']} 个文件：")
        for file_stat in s.get('file_stats', []):
            input_file = file_stat.get('input_file', '未知输入')
            output_file = file_stat.get('output_file', '未知输出')
            configured_total = file_stat.get('configured_total', 0)
            success = file_stat.get('successful_this_run', 0)
            failed = file_stat.get('failed_this_run', 0)
            skipped = file_stat.get('skipped_this_run', 0)

            print(f"  - 输入 {input_file}")
            print(f"    输出 {output_file}")
            print(f"    配置总数 {configured_total}")
            print(f"    本次结果：成功 {success}，失败 {failed}，跳过 {skipped}")

# def main():
#     item = {"query": "成功提取query！",
#             "question": "成功提取question！",
#             "input": {"query": "成功提取input！"},
#             "original_query": "成功提取original_query！"}

#     # for key, value in item.items():
#     for key, value in item.items():
#         print(extract_query({key: value}))

if __name__ == "__main__":
    main()


