#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
独立推理入口。
示例:
  python infer.py --experiment exp1_basic_qa --limit 10
"""

import argparse
from utils.process_infer import run_infer_experiment


def main():
    parser = argparse.ArgumentParser(description="LLM 推理入口")
    parser.add_argument("--experiment", required=True, help="实验名称")
    parser.add_argument("--data", help="数据文件路径（可选，覆盖配置文件中的设置）")
    parser.add_argument("--models", help="指定模型列表（逗号分隔），覆盖配置文件中的设置")
    parser.add_argument("--limit", type=int, help="限制处理数量（用于测试）")
    parser.add_argument("--no-resume", action="store_true", help="禁用Resume功能")
    parser.add_argument("--config", default="config.yaml", help="配置文件路径")
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
    # 简要打印
    for s in stats:
        print(f"{s['model']}: {s['successful']}/{s['total']} ({s['success_rate']:.1%}) -> {s['output_file']}")


if __name__ == "__main__":
    main()


