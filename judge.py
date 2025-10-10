#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
独立评判入口。
示例:
  python judge.py --experiment judge_quality --limit 10
"""

import argparse
from utils.process_judge import run_judge_experiment


def main():
    parser = argparse.ArgumentParser(description="LLM 评判入口")
    parser.add_argument("--experiment", default="judge_infer_50_hints0", help="实验名称")
    parser.add_argument("--data", help="数据文件路径（可选，覆盖配置文件中的设置）")
    parser.add_argument("--models", help="指定模型列表（逗号分隔），覆盖配置文件中的设置")
    parser.add_argument("--limit", type=int, help="限制处理数量（用于测试）")
    parser.add_argument("--no-resume", action="store_true", help="禁用Resume功能")
    parser.add_argument("--config", default="config.yaml", help="配置文件路径")
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


if __name__ == "__main__":
    main()


