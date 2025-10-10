#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
综合实验分数统计脚本
同时处理主实验和消融实验数据，生成包含两个sheet的Excel文件
python scripts/get_score_ablation.py results/judge -o my_results.xlsx -v -c 10
使用方法：
1. 基本用法：
   python scripts/get_score_ablation.py results/judge
   
2. 指定输出文件：
   python scripts/get_score_ablation.py results/judge -o my_results.xlsx
   
3. 显示详细输出：
   python scripts/get_score_ablation.py results/judge -v

4. 自定义期望数据条数：
   python scripts/get_score_ablation.py results/judge -c 50

5. 完整用法：
   python scripts/get_score_ablation.py results/judge -o my_results.xlsx -v -c 50

输入数据结构（固定定义）：
results/judge/
├── judge_infer_50_hints0/     # 消融实验：无hint
├── judge_infer_50_hints1/     # 消融实验：Hint1
├── judge_infer_50_hints2/     # 消融实验：Hint2
├── judge_infer_50_hints3/     # 消融实验：Hint3
├── judge_infer_50_hints4/     # 消融实验：Hint1+Hint2+Hint3


输出格式：
- Excel文件包含多个sheet：
  1. "main"：主实验结果（按category分类，格式：aspect1%/aspect2%）
  2. 每个hints条件各一个sheet（与main同格式，含各学科列）
  3. "ablation experiment"：消融实验结果（指定模型，5个hint条件的aspect1%/aspect2%格式）

自动支持的模型（无需手动配置）：
- 自动从文件名提取模型名称
- 智能生成显示名称
- 支持复杂模型名称格式
- 保持一致的排序规则

计算方式：
1. aspect1总分 = 分子得分和/数据条数（每题满分1分，只取分子作为得分）
2. aspect2总分 = 得分/sum(num_checklist)  
3. 总分 = (aspect1分子得分和 + aspect2原始总分) / (总checklist数量 + 数据条数)
4. 按所有可用的category计算总和

数据完整性检查：
- 每个category默认期望50条数据（可通过-c参数自定义）
- 正常数据处理时不显示，只在最后统一显示有问题的数据
- 缺失情况会自动保存到带时间戳的txt文件中
"""

import json
import argparse
import os
import glob
import re
from typing import Dict, List, Tuple, Set
from collections import defaultdict
import pandas as pd
import openpyxl
from openpyxl import Workbook
from openpyxl.styles import Font, Alignment
from datetime import datetime

# 全局变量收集所有完整性问题
all_completeness_issues = []


# ========== 模型管理系统 ==========

class ModelManager:
    """模型配置和名称管理器"""
    
    # 预定义的模型配置（保持向后兼容性和排序优先级）
    PREDEFINED_MODELS = {
        # 核心模型（高优先级）
        'gpt41': {'display_name': 'gpt4.1', 'priority': 100},
        'gpt4o': {'display_name': 'gpt4o', 'priority': 99},
        'gpt5': {'display_name': 'gpt5', 'priority': 98}, 
        'gpt5mini': {'display_name': 'gpt5mini', 'priority': 97},
        'claude4': {'display_name': 'claude4', 'priority': 96},
        'o1': {'display_name': 'o1', 'priority': 95},
        'o3': {'display_name': 'o3', 'priority': 94},
        'o3-dr': {'display_name': 'o3-dr', 'priority': 93},
        'o4_mini_dr': {'display_name': 'o4_mini_dr', 'priority': 92},
        
        # DeepSeek系列
        'deepseekv3': {'display_name': 'deepseekv3', 'priority': 85},
        'deepseekv31': {'display_name': 'deepseekv31', 'priority': 84},
        'deepseekr1': {'display_name': 'deepseekr1', 'priority': 83},
        
        # Gemini系列 
        'gemini25pro': {'display_name': 'gemini2.5pro', 'priority': 75},
        'gemini_2.5_pro_deepsearch_async': {'display_name': 'gemini2.5pro_deepsearch', 'priority': 74},
        'gemini_2.5_flash_deepsearch_async': {'display_name': 'gemini2.5flash_deepsearch', 'priority': 73},
        
        # AFM系列
        'AFM_sft': {'display_name': 'AFM_sft', 'priority': 70},
        'AFM_rl': {'display_name': 'AFM_rl', 'priority': 69},
        
        # 其他模型
        'oagent': {'display_name': 'oagent', 'priority': 65},
        'gptoss': {'display_name': 'gptoss', 'priority': 64},
        'kimik2': {'display_name': 'kimik2', 'priority': 63},
        'qwen3': {'display_name': 'qwen3', 'priority': 62},
        'seedoss': {'display_name': 'seedoss', 'priority': 61},
    }
    
    def __init__(self):
        self.discovered_models = {}  # 运行时发现的新模型
    
    def extract_model_name(self, filename: str) -> str:
        """
        智能提取模型名称，支持各种文件名格式
        """
        if not filename or not isinstance(filename, str):
            return filename
        
        # 移除文件扩展名
        base_name = filename
        if base_name.endswith('.jsonl'):
            base_name = base_name[:-6]
        
        # 处理不同的文件名格式
        if base_name.startswith('judged_'):
            # 格式: judged_{model}_{judge}.jsonl
            name_part = base_name[7:]  # 移除 'judged_' 前缀
            
            # 文件名格式: judged_{被评判模型}_{judge模型}.jsonl
            # 我们需要识别出被评判的模型，而不是judge模型
            
            # 已知的judge模型列表（这些应该被排除，不作为被评判模型）
            judge_models = {
                'gpt5mini', 'gpt41', 'gpt4o', 'gpt5', 'claude4', 'o1', 'o3'
            }
            
            # 特殊处理复杂模型名称（被评判模型，按长度优先匹配）
            complex_patterns = [
                'gemini_2.5_pro_deepsearch_async',
                'gemini_2.5_flash_deepsearch_async', 
                'deepseekv31',
                'deepseekv3',
                'deepseekr1',
                'o4_mini_dr',
                'o3-dr',
                'gemini25pro',
                'AFM_sft',
                'AFM_rl',
                'oagent',
                'gptoss',
                'kimik2',
                'qwen3',
                'seedoss'
            ]
            
            # 按长度倒序排列，确保长模式优先匹配
            complex_patterns.sort(key=len, reverse=True)
            
            # 首先尝试匹配被评判模型（排除judge模型）
            for pattern in complex_patterns:
                if pattern in name_part:
                    # 确保这不是judge模型的部分
                    remaining = name_part.replace(pattern, '')
                    # 检查剩余部分是否是已知的judge模型
                    remaining_parts = [p for p in remaining.split('_') if p]
                    if any(part in judge_models for part in remaining_parts):
                        return pattern
            
            # 通用解析：分割并智能识别被评判模型
            parts = name_part.split('_')
            if len(parts) >= 2:
                # 尝试识别最后一部分是否为judge模型
                last_part = parts[-1]
                if last_part in judge_models:
                    # 最后一部分是judge模型，前面的是被评判模型
                    model_name = '_'.join(parts[:-1])
                    return model_name
                else:
                    # 无法确定，使用原有逻辑
                    model_name = '_'.join(parts[:-1])
                    return model_name
            elif len(parts) == 1:
                return parts[0]
                
        elif base_name.startswith('judge_test_'):
            # 格式: judge_test_first_{model}_{judge}.jsonl
            name_part = base_name[11:]  # 移除 'judge_test_' 前缀
            
            # 移除常见后缀模式
            for suffix in ['_gpt41', '_gpt5mini']:
                if name_part.endswith(suffix):
                    name_part = name_part[:-len(suffix)]
                    break
            
            # 在剩余部分中查找已知模型名
            for pattern in ['gpt41', 'gpt5', 'claude4', 'deepseekv3', 'deepseekr1', 
                           'o1', 'o3', 'gemini25pro', 'o4_mini_dr', 'AFM_sft', 'AFM_rl']:
                if pattern in name_part:
                    return pattern
        
        # 如果以上都不匹配，返回处理后的基础名称
        return base_name
    
    def get_display_name(self, model_name: str) -> str:
        """
        获取模型的显示名称
        """
        if not model_name:
            return model_name
            
        # 先检查预定义模型
        if model_name in self.PREDEFINED_MODELS:
            return self.PREDEFINED_MODELS[model_name]['display_name']
        
        # 检查已发现的模型
        if model_name in self.discovered_models:
            return self.discovered_models[model_name]['display_name']
        
        # 为新模型生成显示名称
        display_name = self._generate_display_name(model_name)
        
        # 记录新发现的模型（中等优先级）
        self.discovered_models[model_name] = {
            'display_name': display_name,
            'priority': 50  # 新模型默认中等优先级
        }
        
        print(f"🆕 发现新模型: {model_name} -> {display_name}")
        
        return display_name
    
    def _generate_display_name(self, model_name: str) -> str:
        """
        为新模型智能生成显示名称
        """
        # 简单清理和格式化
        display_name = model_name.replace('_', '.')
        
        # 处理常见模式
        patterns = [
            (r'gpt(\d+)', r'gpt\1'),
            (r'claude(\d+)', r'claude\1'),  
            (r'o(\d+)', r'o\1'),
            (r'deepseek(v\d+)', r'deepseek\1'),
            (r'gemini(\d+\.?\d*)', r'gemini\1'),
        ]
        
        for pattern, replacement in patterns:
            display_name = re.sub(pattern, replacement, display_name, flags=re.IGNORECASE)
        
        return display_name
    
    def get_priority(self, model_name: str) -> int:
        """
        获取模型的排序优先级
        """
        if model_name in self.PREDEFINED_MODELS:
            return self.PREDEFINED_MODELS[model_name]['priority']
        elif model_name in self.discovered_models:
            return self.discovered_models[model_name]['priority']
        else:
            # 未知模型默认最低优先级
            return 0
    
    def get_sorted_models(self, available_models: Set[str]) -> List[Tuple[str, str]]:
        """
        获取排序后的模型列表：(model_name, display_name)
        """
        # 确保所有模型都有显示名称
        for model in available_models:
            self.get_display_name(model)  # 这会自动注册新模型
        
        # 按优先级排序，优先级相同则按名称排序
        sorted_models = sorted(
            available_models,
            key=lambda x: (-self.get_priority(x), x)
        )
        
        return [(model, self.get_display_name(model)) for model in sorted_models]


# 全局模型管理器实例
model_manager = ModelManager()


# ========== Bench query -> num_checklist mapping ==========
_GLOBAL_BENCH_MAP = None
_GLOBAL_BENCH_DATA = None  # 存储完整的bench数据，用于字段匹配


def _normalize_query(q: str) -> str:
    if not q:
        return ""
    q = ' '.join(q.split())
    q = q.replace(' | ', ' ').replace('|', ' ')
    return ' '.join(q.split()).strip()


def _load_bench_map(default_path: str = 'data/raw/bench_50.jsonl') -> Dict[str, int]:
    bench_map: Dict[str, int] = {}
    try:
        if not os.path.exists(default_path):
            return bench_map
        with open(default_path, 'r', encoding='utf-8') as f:
            for line in f:
                if not line.strip():
                    continue
                try:
                    obj = json.loads(line)
                except Exception:
                    continue
                q = obj.get('query') or obj.get('original_query') or ''
                ncl = obj.get('num_checklist')
                if isinstance(ncl, int) and ncl > 0:
                    bench_map[q] = ncl
                    bench_map[_normalize_query(q)] = ncl
    except Exception:
        pass
    return bench_map


def _get_bench_map() -> Dict[str, int]:
    global _GLOBAL_BENCH_MAP
    if _GLOBAL_BENCH_MAP is None:
        _GLOBAL_BENCH_MAP = _load_bench_map()
    return _GLOBAL_BENCH_MAP


def _load_bench_data(default_path: str = 'data/raw/bench_50.jsonl') -> Dict[str, dict]:
    """加载完整的bench数据，用于字段匹配"""
    bench_data: Dict[str, dict] = {}
    try:
        if not os.path.exists(default_path):
            return bench_data
        with open(default_path, 'r', encoding='utf-8') as f:
            for line in f:
                if not line.strip():
                    continue
                try:
                    obj = json.loads(line)
                    query = obj.get('query', '').strip()
                    if query:
                        # 使用原始query作为key进行精确匹配
                        bench_data[query] = obj
                except Exception:
                    continue
    except Exception:
        pass
    return bench_data


def _get_bench_data() -> Dict[str, dict]:
    global _GLOBAL_BENCH_DATA
    if _GLOBAL_BENCH_DATA is None:
        _GLOBAL_BENCH_DATA = _load_bench_data()
    return _GLOBAL_BENCH_DATA


def get_category_from_bench(query: str) -> str:
    """从bench_50.jsonl中根据query匹配获取category"""
    bench_data = _get_bench_data()
    if query in bench_data:
        return bench_data[query].get('category', '')
    return ''


def smart_categorize(data: dict) -> str:
    """
    当category为null时，首先尝试从bench_50.jsonl匹配，然后智能识别类别
    
    Args:
        data: 包含query等字段的数据字典
        
    Returns:
        识别出的类别名称，如果无法识别则返回'Unknown'
    """
    # 首先尝试从 bench_50.jsonl 匹配
    query = data.get('query', '')
    if query:
        bench_category = get_category_from_bench(query.strip())
        if bench_category:
            return bench_category
    
    # 如果无法从bench_50.jsonl匹配，则使用智能识别
    query_lower = query.lower()
    sheet_name = data.get('sheet_name', '').lower()
    
    # 数学关键词
    math_keywords = [
        'hilbert', 'samuel', 'multiplicity', 'cohen', 'macaulay', 'rings', 
        'characteristic', 'frobenius', 'gorenstein', 'algebra', 'algebraic',
        'theorem', 'lemma', 'proof', 'mathematical', 'equation', 'formula',
        'function', 'matrix', 'polynomial', 'topology', 'geometry', 'calculus',
        'analysis', 'number theory', 'combinatorics', 'permutation', 'bijection',
        'motzkin', 'fibonacci', 'probability', 'stochastic', 'quantum', 'optimization'
    ]
    
    # 计算机科学关键词
    cs_keywords = [
        'algorithm', 'data structure', 'programming', 'software', 'computer',
        'machine learning', 'artificial intelligence', 'neural network',
        'database', 'network', 'security', 'cryptography', 'blockchain'
    ]
    
    # 哲学关键词
    philosophy_keywords = [
        'philosophy', 'philosophical', 'ethics', 'moral', 'ontology',
        'epistemology', 'metaphysics', 'logic', 'phenomenology'
    ]
    
    # 法学关键词
    law_keywords = [
        'law', 'legal', 'court', 'justice', 'rights', 'constitution',
        'legislation', 'jurisprudence', 'contract', 'tort'
    ]
    
    # 经济学关键词
    economics_keywords = [
        'economic', 'economics', 'market', 'trade', 'finance', 'fiscal',
        'monetary', 'GDP', 'inflation', 'supply', 'demand'
    ]
    
    # 检查各类别关键词
    if any(keyword in query_lower for keyword in math_keywords):
        return 'Math'
    elif any(keyword in query_lower for keyword in cs_keywords):
        return 'Computer Science'
    elif any(keyword in query_lower for keyword in philosophy_keywords):
        return 'philosophy'
    elif any(keyword in query_lower for keyword in law_keywords):
        return 'Law'
    elif any(keyword in query_lower for keyword in economics_keywords):
        return 'economics'
    
    # 如果sheet_name包含学科信息，也可以作为参考
    if 'math' in sheet_name:
        return 'Math'
    elif 'computer' in sheet_name or 'cs' in sheet_name:
        return 'Computer Science'
    elif 'philosophy' in sheet_name:
        return 'philosophy'
    elif 'law' in sheet_name:
        return 'Law'
    elif 'econ' in sheet_name:
        return 'economics'
    
    return 'Unknown'


def parse_score_ratio(score_str: str) -> Tuple[float, float]:
    """
    解析分数比例字符串，如 "1/2" -> (1.0, 2.0)
    
    Args:
        score_str: 分数字符串，格式为 "分子/分母"
        
    Returns:
        (分子, 分母) 的元组
    """
    try:
        if '/' in score_str:
            numerator, denominator = score_str.split('/')
            return float(numerator), float(denominator)
        else:
            # 如果没有分母，默认分母为1
            return float(score_str), 1.0
    except (ValueError, AttributeError):
        return 0.0, 1.0




def calculate_scores_for_file(jsonl_file: str) -> Dict:
    """
    计算单个jsonl文件中所有数据的分数统计，按category分类
    
    Args:
        jsonl_file: 输入的jsonl文件路径
        
    Returns:
        包含分类计算结果的字典
    """
    if not os.path.exists(jsonl_file):
        raise FileNotFoundError(f"文件不存在: {jsonl_file}")
    
    # 分类统计 - 使用defaultdict自动创建嵌套字典
    category_stats = defaultdict(lambda: {
        'count': 0,
        'aspect1_score': 0.0,
        'aspect1_denominator': 0.0,
        'aspect2_score': 0.0,
        'num_checklist': 0
    })
    
    print(f"正在处理文件: {jsonl_file}")
    
    with open(jsonl_file, 'r', encoding='utf-8') as f:
        for line_num, line in enumerate(f, 1):
            try:
                data = json.loads(line.strip())
                
                # 检查是否有scores字段
                if 'scores' not in data:
                    print(f"警告: 文件{jsonl_file}第{line_num}行缺少scores字段，跳过")
                    continue
                
                scores = data['scores']
                
                # 解析aspect1分数（将多分制折算为1分制：分子>0 记1分，否则0分）
                aspect1_str = scores.get('aspect1', '0/1')
                aspect1_score, aspect1_max = parse_score_ratio(aspect1_str)
                # 折算为通过/未通过
                aspect1_raw_score = 1.0 if aspect1_score > 0 else 0.0
                aspect1_max = 1.0
                
                # 解析aspect2分数
                aspect2_str = scores.get('aspect2', '0/1')
                aspect2_score, aspect2_max = parse_score_ratio(aspect2_str)
                
                # 获取num_checklist：优先用scores.num_checklist；
                # 若缺失，再从bench_50.jsonl按query匹配获取；仍缺失再兜底用aspect2分母
                num_checklist = scores.get('num_checklist', None)
                if not isinstance(num_checklist, (int, float)) or num_checklist <= 0:
                    # bench查找
                    bench_map = _get_bench_map()
                    q = data.get('query') or data.get('original_query') or ''
                    num_checklist = bench_map.get(q) or bench_map.get(_normalize_query(q))
                if not isinstance(num_checklist, (int, float)) or num_checklist <= 0:
                    num_checklist = aspect2_max
                
                # 获取category（从原始数据中）
                category = data.get('category', 'Unknown')
                # 如果category为None或空字符串，先尝试从bench匹配，再智能识别类别
                if category is None or category == '':
                    # 尝试从 bench_50.jsonl 匹配获取完整字段信息
                    query = data.get('query', '')
                    if query:
                        bench_data = _get_bench_data()
                        matched_data = bench_data.get(query.strip())
                        if matched_data:
                            # 成功匹配到bench数据，使用其category
                            category = matched_data.get('category', 'Unknown')
                            print(f"✅ 已从bench_50.jsonl匹配补充category: {category}，query: {query[:50]}...")
                        else:
                            # 无法匹配，使用智能识别
                            category = smart_categorize(data)
                            if category == 'Unknown':
                                print(f"警告: 文件{jsonl_file}第{line_num}行category为null且无法自动识别，设为Unknown")
                                print(f"      内容预览: {data.get('query', '')[:100]}...")
                    else:
                        category = 'Unknown'
                
                # 分类统计
                category_stats[category]['count'] += 1
                category_stats[category]['aspect1_score'] += aspect1_raw_score
                category_stats[category]['aspect1_denominator'] += aspect1_max
                category_stats[category]['aspect2_score'] += aspect2_score
                category_stats[category]['num_checklist'] += num_checklist
                
            except json.JSONDecodeError as e:
                print(f"警告: 文件{jsonl_file}第{line_num}行JSON解析错误，跳过: {e}")
                continue
            except Exception as e:
                print(f"警告: 文件{jsonl_file}第{line_num}行处理错误，跳过: {e}")
                continue
    
    # 计算各类别结果
    category_results = {}
    for category, stats in category_stats.items():
        if stats['count'] > 0:  # 只计算有数据的类别
            category_results[category] = calculate_category_scores(
                stats['count'], 
                stats['aspect1_score'], 
                stats['aspect1_denominator'],
                stats['aspect2_score'], 
                stats['num_checklist']
            )
    
    return category_results


def calculate_category_scores(data_count: int, aspect1_score: float, aspect1_denominator: float, aspect2_score: float, num_checklist: int) -> Dict:
    """
    计算单个类别的分数
    
    Args:
        data_count: 数据条数
        aspect1_score: aspect1分子累计得分（不归一化，只取分子）
        aspect1_denominator: aspect1的分母累计（通常为题目数量）
        aspect2_score: aspect2总分
        num_checklist: checklist总数
        
    Returns:
        计算结果字典
    """
    # aspect1总分 = 分子得分和 / 题目数量（每题满分1分）
    aspect1_total = aspect1_score / aspect1_denominator if aspect1_denominator > 0 else 0

    # aspect2总分 = 得分/sum(num_checklist)
    aspect2_total = aspect2_score / num_checklist if num_checklist > 0 else 0
    
    # 总分 = (aspect1原始总分 + aspect2原始总分) / (总checklist数量 + aspect1分母累计)
    denominator = num_checklist + aspect1_denominator
    final_total = (aspect1_score + aspect2_score) / denominator if denominator > 0 else 0
    
    return {
        'data_count': data_count,
        'num_checklist': num_checklist,
        'raw_scores': {
            'aspect1_score': aspect1_score,
            'aspect1_denominator': aspect1_denominator,
            'aspect2_score': aspect2_score
        },
        'calculated_scores': {
            'aspect1_total': aspect1_total,
            'aspect2_total': aspect2_total,
            'final_total': final_total
        },
        'formatted_score': f"{aspect1_total*100:.1f}/{aspect2_total*100:.1f}"
    }


def check_data_completeness(category_results: Dict, expected_count_per_category: int = 50) -> Dict:
    """
    检查数据完整性，确保每个category都有预期的数据条数
    
    Args:
        category_results: 各category的计算结果
        expected_count_per_category: 每个category预期的数据条数
        
    Returns:
        包含完整性检查结果的字典
    """
    completeness_info = {
        'is_complete': True,
        'missing_data': [],
        'category_counts': {},
        'total_expected': 0,
        'total_actual': 0
    }
    
    for category, result in category_results.items():
        actual_count = result['data_count']
        completeness_info['category_counts'][category] = {
            'expected': expected_count_per_category,
            'actual': actual_count,
            'missing': expected_count_per_category - actual_count
        }
        
        completeness_info['total_expected'] += expected_count_per_category
        completeness_info['total_actual'] += actual_count
        
        if actual_count < expected_count_per_category:
            completeness_info['is_complete'] = False
            completeness_info['missing_data'].append({
                'category': category,
                'expected': expected_count_per_category,
                'actual': actual_count,
                'missing': expected_count_per_category - actual_count
            })
    
    return completeness_info


def calculate_overall_aspect1_aspect2_from_categories(category_results: Dict) -> Tuple[float, float]:
    """
    计算Overall的aspect1和aspect2百分比（基于所有category的加权平均）
    
    Args:
        category_results: 各category的计算结果
        
    Returns:
        (aspect1_percentage, aspect2_percentage) 的元组
    """
    if not category_results:
        return 0.0, 0.0
    
    # 累计各category的原始分数和分母
    total_aspect1_score = 0.0
    total_aspect1_denominator = 0.0
    total_aspect2_score = 0.0
    total_aspect2_denominator = 0.0
    
    for category, result in category_results.items():
        # 跳过非category数据（如completeness、overall_score等）
        if not isinstance(result, dict) or 'raw_scores' not in result:
            continue
            
        raw_scores = result['raw_scores']
        data_count = result['data_count']
        num_checklist = result['num_checklist']
        
        # aspect1累计（使用记录的分母；兼容旧结果）
        total_aspect1_score += raw_scores['aspect1_score']
        aspect1_denominator = raw_scores.get('aspect1_denominator', data_count)  # 兼容旧数据
        total_aspect1_denominator += aspect1_denominator
        
        # aspect2累计
        total_aspect2_score += raw_scores['aspect2_score']
        total_aspect2_denominator += num_checklist  # aspect2满分为checklist总数
    
    # 计算百分比
    aspect1_percentage = (total_aspect1_score / total_aspect1_denominator * 100) if total_aspect1_denominator > 0 else 0.0
    aspect2_percentage = (total_aspect2_score / total_aspect2_denominator * 100) if total_aspect2_denominator > 0 else 0.0
    
    return aspect1_percentage, aspect2_percentage


def calculate_overall_score_from_categories(category_results: Dict) -> float:
    """
    计算Overall总分（基于所有category的加权平均）
    
    Args:
        category_results: 各category的计算结果
        
    Returns:
        Overall总分百分比
    """
    if not category_results:
        return 0.0
    
    total_raw_score = 0.0
    total_denominator = 0.0
    
    for category, result in category_results.items():
        raw_scores = result['raw_scores']
        data_count = result['data_count']
        num_checklist = result['num_checklist']
        
        # 累加原始分数和分母
        total_raw_score += raw_scores['aspect1_score'] + raw_scores['aspect2_score']
        aspect1_denominator = raw_scores.get('aspect1_denominator', data_count)  # 兼容旧数据
        total_denominator += num_checklist + aspect1_denominator
    
    # 计算总体得分
    overall_score = (total_raw_score / total_denominator * 100) if total_denominator > 0 else 0.0
    return overall_score


def process_hints_folder(hints_folder: str, expected_count: int = 50) -> Dict[str, Dict]:
    """
    处理单个hints文件夹中的所有judged_{model_name}_{judge_model}.jsonl文件
    
    Args:
        hints_folder: hints文件夹路径 (如 infer_40_hints0)
        
    Returns:
        {model_name: {category: result_dict, 'overall': overall_score}} 的字典
    """
    if not os.path.exists(hints_folder):
        raise FileNotFoundError(f"文件夹不存在: {hints_folder}")
    
    # 查找所有符合条件的文件（支持任何judge模型）
    pattern = os.path.join(hints_folder, "judged_*.jsonl")
    files = glob.glob(pattern)
    
    if not files:
        print(f"警告: 在文件夹 {hints_folder} 中未找到符合 judged_*.jsonl 格式的文件")
        return {}
    
    print(f"\n处理文件夹: {hints_folder}")
    print(f"找到 {len(files)} 个文件:")
    for f in files:
        print(f"  - {os.path.basename(f)}")
    
    results = {}
    
    for file_path in files:
        filename = os.path.basename(file_path)
        # 使用全局模型管理器提取模型名称
        model_name = model_manager.extract_model_name(filename)
        
        try:
            category_results = calculate_scores_for_file(file_path)
            overall_score = calculate_overall_score_from_categories(category_results)
            
            # 计算Overall的aspect1/aspect2百分比（与主实验保持一致）
            overall_aspect1, overall_aspect2 = calculate_overall_aspect1_aspect2_from_categories(category_results)
            
            # 检查数据完整性
            completeness_info = check_data_completeness(category_results, expected_count)
            
            results[model_name] = category_results.copy()
            results[model_name]['overall'] = overall_score
            results[model_name]['overall_aspect1_percentage'] = overall_aspect1
            results[model_name]['overall_aspect2_percentage'] = overall_aspect2
            results[model_name]['completeness'] = completeness_info
            
            # 收集完整性问题到全局列表
            if not completeness_info['is_complete']:
                all_completeness_issues.append({
                    'folder': hints_folder,
                    'model': model_name,
                    'completeness_info': completeness_info,
                    'overall_score': overall_score,
                    'category_count': len(category_results)
                })
            
            # 只显示处理完成信息，不显示完整性问题（留到最后统一显示）
            status_icon = "✓" if completeness_info['is_complete'] else "⚠️"
            print(f"{status_icon} {model_name}: 处理完成，找到 {len(category_results)} 个category，总分: {overall_score:.1f}%")
            
        except Exception as e:
            print(f"✗ {model_name}: 处理失败 - {e}")
            continue
    
    return results


# 删除了自动发现功能，现在使用固定的文件夹定义


def process_all_hints_experiments(base_path: str, expected_count: int = 50) -> Dict[str, Dict[str, Dict]]:
    """
    处理所有hints实验文件夹
    
    Args:
        base_path: 包含所有hints文件夹的基础路径
        expected_count: 每个category期望的数据条数
        
    Returns:
        {hints_folder: {model_name: results}} 的嵌套字典
    """
    # 固定定义的hints文件夹
    hints_folders = [
        'judge_infer_50_hints0',  # 无hint
        'judge_infer_50_hints1',  # Hint1
        'judge_infer_50_hints2',  # Hint2
        'judge_infer_50_hints3',  # Hint3
        'judge_infer_50_hints4'   # Hint1+Hint2+Hint3
    ]
    
    print(f"处理指定的hints实验文件夹: {hints_folders}")
    
    all_results = {}
    
    for hints_folder in hints_folders:
        folder_path = os.path.join(base_path, hints_folder)
        
        if os.path.exists(folder_path):
            try:
                folder_results = process_hints_folder(folder_path, expected_count)
                if folder_results:
                    all_results[hints_folder] = folder_results
                else:
                    print(f"警告: {hints_folder} 文件夹中没有有效数据")
            except Exception as e:
                print(f"错误: 处理 {hints_folder} 失败 - {e}")
        else:
            print(f"警告: 文件夹 {folder_path} 不存在，跳过")
    
    return all_results


def process_main_experiment(base_path: str, expected_count: int = 50) -> Dict[str, Dict]:
    """
    处理主实验数据（自动寻找hints0文件夹的数据，按category显示）
    
    Args:
        base_path: 包含实验文件夹的基础路径
        expected_count: 每个category期望的数据条数
        
    Returns:
        {model_name: {category: result_dict}} 的字典
    """
    # 使用固定的hints0文件夹作为主实验数据源
    hints0_folder = os.path.join(base_path, "judge_infer_50_hints0")
    
    if not os.path.exists(hints0_folder):
        print(f"警告: 主实验数据源文件夹 {hints0_folder} 不存在")
        return {}
    
    # 查找所有符合条件的文件（支持任何judge模型）
    pattern = os.path.join(hints0_folder, "judged_*.jsonl")
    files = glob.glob(pattern)
    
    if not files:
        print(f"警告: 在文件夹 {hints0_folder} 中未找到主实验文件")
        return {}
    
    print(f"\n📊 处理主实验数据（基于hints0数据）:")
    print(f"找到 {len(files)} 个主实验文件:")
    for f in files:
        print(f"  - {os.path.basename(f)}")
    
    results = {}
    
    for file_path in files:
        filename = os.path.basename(file_path)
        # 使用全局模型管理器提取模型名称
        model_name = model_manager.extract_model_name(filename)
        
        try:
            category_results = calculate_scores_for_file(file_path)
            
            # 检查数据完整性
            completeness_info = check_data_completeness(category_results, expected_count)
            
            # 计算Overall分数
            overall_score = calculate_overall_score_from_categories(category_results)
            
            # 计算Overall的aspect1/aspect2百分比
            overall_aspect1, overall_aspect2 = calculate_overall_aspect1_aspect2_from_categories(category_results)
            
            results[model_name] = category_results.copy()
            results[model_name]['completeness'] = completeness_info
            results[model_name]['overall_score'] = overall_score
            results[model_name]['overall_aspect1_percentage'] = overall_aspect1
            results[model_name]['overall_aspect2_percentage'] = overall_aspect2
            
            # 收集完整性问题到全局列表
            if not completeness_info['is_complete']:
                all_completeness_issues.append({
                    'folder': 'main_experiment',
                    'model': model_name,
                    'completeness_info': completeness_info,
                    'overall_score': overall_score,
                    'category_count': len(category_results)
                })
            
            # 只显示处理完成信息
            status_icon = "✓" if completeness_info['is_complete'] else "⚠️"
            print(f"{status_icon} {model_name}: 处理完成，找到 {len(category_results)} 个category，Overall: {overall_score:.1f}%")
            
        except Exception as e:
            print(f"✗ {model_name}: 处理失败 - {e}")
            continue
    
    return results


def map_category_to_column(category: str) -> str:
    """
    将category映射到Excel列名
    """
    category_mapping = {
        'philosophy': 'Phi',
        'Computer Science': 'CS', 
        'Law': 'Law',
        'economics': 'Econ',
        # 可以根据需要添加更多映射
    }
    return category_mapping.get(category, category)


def create_comprehensive_excel(all_results: Dict, output_file: str):
    """
    创建包含主实验和消融实验两个sheet的Excel文件
    
    Args:
        all_results: 包含主实验和消融实验的所有结果数据
        output_file: 输出Excel文件路径
    """
    # 自动创建目录（如果不存在）
    output_dir = os.path.dirname(output_file)
    if output_dir and not os.path.exists(output_dir):
        os.makedirs(output_dir, exist_ok=True)
        print(f"创建目录: {output_dir}")
    
    # 分离主实验和消融实验数据
    ablation_results = {}
    main_results = {}
    
    # 定义消融实验的文件夹名称
    ablation_folders = {
        'judge_infer_50_hints0',
        'judge_infer_50_hints1', 
        'judge_infer_50_hints2',
        'judge_infer_50_hints3',
        'judge_infer_50_hints4'
    }
    
    for key, value in all_results.items():
        if key in ablation_folders:
            ablation_results[key] = value
        else:
            # 主实验数据（模型名称为key）
            main_results[key] = value
    
    # 创建工作簿
    wb = Workbook()
    
    # 删除默认的Sheet
    wb.remove(wb.active)
    
    # === 创建主实验sheet ===
    main_ws = wb.create_sheet("main")
    
    if main_results:
        # 收集所有出现的category并排序
        all_categories = set()
        for model_results in main_results.values():
            # 只包含真正的category，排除特殊字段
            for key, value in model_results.items():
                # 确保这是一个真正的category结果，不是特殊字段，且key不为None
                if (key is not None and 
                    key not in ['completeness', 'overall_score', 'overall_aspect1_percentage', 'overall_aspect2_percentage'] and
                    isinstance(value, dict) and 'calculated_scores' in value):
                    all_categories.add(key)
        
        # 映射category到列名并排序
        column_mapping = {cat: map_category_to_column(cat) for cat in all_categories}
        # 过滤掉None值，防止排序错误
        valid_columns = [col for col in column_mapping.values() if col is not None]
        columns = ['Overall'] + sorted(set(valid_columns))
        
        print(f"主实验发现的categories: {sorted(all_categories)}")
        print(f"主实验Excel列: {columns}")
        
        # 设置表头
        headers = ['Model'] + columns
        for col_idx, header in enumerate(headers, 1):
            cell = main_ws.cell(row=1, column=col_idx, value=header)
            cell.font = Font(bold=True)
            cell.alignment = Alignment(horizontal='center')
        
        # 使用模型管理器自动排序模型
        available_model_names = set(main_results.keys())
        available_models = model_manager.get_sorted_models(available_model_names)
        
        print(f"主实验指定的模型（按顺序）: {[display_name for _, display_name in available_models]}")
        
        # 填充数据
        row_idx = 2
        for file_name, display_name in available_models:
            model_results = main_results[file_name]
            
            # 模型名称
            main_ws.cell(row=row_idx, column=1, value=display_name)
            
            # Overall列：显示aspect1/aspect2格式
            if 'overall_aspect1_percentage' in model_results and 'overall_aspect2_percentage' in model_results:
                aspect1_pct = model_results['overall_aspect1_percentage']
                aspect2_pct = model_results['overall_aspect2_percentage']
                main_ws.cell(row=row_idx, column=2, value=f"{aspect1_pct:.1f}/{aspect2_pct:.1f}")
            else:
                main_ws.cell(row=row_idx, column=2, value="")
            
            # 填充各category的数据
            for col_idx, col_name in enumerate(columns[1:], 3):  # 从第3列开始（跳过Overall）
                # 查找对应的category
                matching_category = None
                for category, mapped_name in column_mapping.items():
                    if mapped_name == col_name:
                        matching_category = category
                        break
                
                if matching_category and matching_category in model_results:
                    result = model_results[matching_category]
                    # 确保这是一个真正的category结果，有formatted_score字段
                    if isinstance(result, dict) and 'formatted_score' in result:
                        formatted_score = result['formatted_score']
                        main_ws.cell(row=row_idx, column=col_idx, value=formatted_score)
                    else:
                        main_ws.cell(row=row_idx, column=col_idx, value="")
                else:
                    main_ws.cell(row=row_idx, column=col_idx, value="")
            
            row_idx += 1
        
        # 设置列宽
        for col in main_ws.columns:
            max_length = 0
            column = col[0].column_letter
            for cell in col:
                try:
                    if len(str(cell.value)) > max_length:
                        max_length = len(str(cell.value))
                except:
                    pass
            adjusted_width = min(max_length + 2, 20)
            main_ws.column_dimensions[column].width = adjusted_width
    
    # === 为每个hints条件创建与主实验相同结构的sheet ===
    if ablation_results:
        # 动态命名函数
        def sheet_title_for_folder(folder_name: str) -> str:
            if 'hints0' in folder_name:
                return '无hint'
            elif 'hints1' in folder_name:
                return 'Hint1'
            elif 'hints2' in folder_name:
                return 'Hint2'
            elif 'hints3' in folder_name:
                return 'Hint3'
            elif 'hints4' in folder_name:
                return 'Hint1+Hint2+Hint3'
            else:
                return folder_name

        for hints_folder in sorted(ablation_results.keys()):
            folder_results = ablation_results[hints_folder]
            title = sheet_title_for_folder(hints_folder)
            ws = wb.create_sheet(title)

            if folder_results:
                # 收集所有出现的category
                all_categories = set()
                for model_results in folder_results.values():
                    for key, value in model_results.items():
                        if (
                            key is not None and
                            key not in ['completeness', 'overall', 'overall_aspect1_percentage', 'overall_aspect2_percentage'] and
                            isinstance(value, dict) and 'calculated_scores' in value
                        ):
                            all_categories.add(key)

                column_mapping = {cat: map_category_to_column(cat) for cat in all_categories}
                valid_columns = [col for col in column_mapping.values() if col is not None]
                columns = ['Overall'] + sorted(set(valid_columns))

                # 表头
                headers = ['Model'] + columns
                for col_idx, header in enumerate(headers, 1):
                    cell = ws.cell(row=1, column=col_idx, value=header)
                    cell.font = Font(bold=True)
                    cell.alignment = Alignment(horizontal='center')

                # 使用模型管理器自动排序模型
                available_model_names = set(folder_results.keys())
                available_models = model_manager.get_sorted_models(available_model_names)

                # 填充数据
                row_idx = 2
                for file_name, display_name in available_models:
                    model_results = folder_results[file_name]
                    ws.cell(row=row_idx, column=1, value=display_name)

                    # Overall列：aspect1/aspect2
                    aspect1_pct = model_results.get('overall_aspect1_percentage', 0)
                    aspect2_pct = model_results.get('overall_aspect2_percentage', 0)
                    ws.cell(row=row_idx, column=2, value=f"{aspect1_pct:.1f}/{aspect2_pct:.1f}")

                    # 各category
                    for col_idx, col_name in enumerate(columns[1:], 3):
                        matching_category = None
                        for category, mapped_name in column_mapping.items():
                            if mapped_name == col_name:
                                matching_category = category
                                break
                        if matching_category and matching_category in model_results:
                            result = model_results[matching_category]
                            if isinstance(result, dict) and 'formatted_score' in result:
                                ws.cell(row=row_idx, column=col_idx, value=result['formatted_score'])
                            else:
                                ws.cell(row=row_idx, column=col_idx, value="")
                        else:
                            ws.cell(row=row_idx, column=col_idx, value="")

                    row_idx += 1

                # 自适应列宽
                for col in ws.columns:
                    max_length = 0
                    column = col[0].column_letter
                    for cell in col:
                        try:
                            if len(str(cell.value)) > max_length:
                                max_length = len(str(cell.value))
                        except:
                            pass
                    adjusted_width = min(max_length + 2, 20)
                    ws.column_dimensions[column].width = adjusted_width

    # === 创建消融实验sheet ===
    ablation_ws = wb.create_sheet("ablation experiment")
    
    if ablation_results:
        # 收集所有模型名称
        all_models = set()
        for folder_results in ablation_results.values():
            for model_name, model_data in folder_results.items():
                # 确保模型数据有效（排除特殊字段）
                if isinstance(model_data, dict) and any(key not in ['overall', 'completeness'] for key in model_data.keys()):
                    all_models.add(model_name)
        
        # 使用模型管理器自动排序模型
        available_models = model_manager.get_sorted_models(all_models)
        
        # 动态列名映射（适应不同的hints数字）
        def get_column_name(folder_name):
            if 'hints0' in folder_name:
                return '无hint'
            elif 'hints1' in folder_name:
                return 'Hint1'
            elif 'hints2' in folder_name:
                return 'Hint2'
            elif 'hints3' in folder_name:
                return 'Hint3'
            elif 'hints4' in folder_name:
                return 'Hint1+Hint2+Hint3'
            else:
                return folder_name
        
        column_mapping = {folder: get_column_name(folder) for folder in ablation_results.keys()}
        
        # 设置表头
        headers = ['ablation experiment'] + [column_mapping.get(folder, folder) for folder in sorted(ablation_results.keys())]
        for col_idx, header in enumerate(headers, 1):
            cell = ablation_ws.cell(row=1, column=col_idx, value=header)
            cell.font = Font(bold=True)
            cell.alignment = Alignment(horizontal='center')
        
        print(f"消融实验Excel列: {headers}")
        print(f"消融实验指定的模型（按顺序）: {[display_name for _, display_name in available_models]}")
        
        # 填充数据
        row_idx = 2
        for file_name, display_name in available_models:
            # 模型名称（显示名称）
            ablation_ws.cell(row=row_idx, column=1, value=display_name)
            
            # 填充各hints条件的数据
            col_idx = 2
            for hints_folder in sorted(ablation_results.keys()):
                if file_name in ablation_results[hints_folder]:
                    # 使用aspect1/aspect2格式（与主实验保持一致）
                    model_data = ablation_results[hints_folder][file_name]
                    aspect1_pct = model_data.get('overall_aspect1_percentage', 0)
                    aspect2_pct = model_data.get('overall_aspect2_percentage', 0)
                    ablation_ws.cell(row=row_idx, column=col_idx, value=f"{aspect1_pct:.1f}/{aspect2_pct:.1f}")
                else:
                    ablation_ws.cell(row=row_idx, column=col_idx, value="")
                col_idx += 1
            
            row_idx += 1
        
        # 设置列宽
        for col in ablation_ws.columns:
            max_length = 0
            column = col[0].column_letter
            for cell in col:
                try:
                    if len(str(cell.value)) > max_length:
                        max_length = len(str(cell.value))
                except:
                    pass
            adjusted_width = min(max_length + 2, 20)
            ablation_ws.column_dimensions[column].width = adjusted_width
    
    # 保存文件
    wb.save(output_file)
    print(f"\n结果已保存到: {output_file}")
    print(f"包含的sheet: {[ws.title for ws in wb.worksheets]}")


def print_ablation_results(all_results: Dict[str, Dict[str, Dict]]):
    """
    打印消融实验结果摘要
    """
    print(f"\n📊 消融实验结果摘要:")
    
    # 收集所有模型
    all_models = set()
    for folder_results in all_results.values():
        all_models.update(folder_results.keys())
    
    # 使用模型管理器自动排序模型
    available_models = model_manager.get_sorted_models(all_models)
    
    print(f"处理了 {len(available_models)} 个指定模型在 {len(all_results)} 个实验条件下的数据")
    
    # 按指定顺序显示结果
    for file_name, display_name in available_models:
        print(f"\n🎯 {display_name}:")
        for hints_folder, folder_results in all_results.items():
            if file_name in folder_results:
                model_data = folder_results[file_name]
                # 使用aspect1/aspect2格式（与主实验保持一致）
                aspect1_pct = model_data.get('overall_aspect1_percentage', 0)
                aspect2_pct = model_data.get('overall_aspect2_percentage', 0)
                # 动态获取条件名称
                if 'hints0' in hints_folder:
                    condition_name = '无hint'
                elif 'hints1' in hints_folder:
                    condition_name = 'Hint1'
                elif 'hints2' in hints_folder:
                    condition_name = 'Hint2'
                elif 'hints3' in hints_folder:
                    condition_name = 'Hint3'
                elif 'hints4' in hints_folder:
                    condition_name = 'Hint1+Hint2+Hint3'
                else:
                    condition_name = hints_folder
                print(f"  📌 {condition_name}: {aspect1_pct:.1f}/{aspect2_pct:.1f}")


def print_completeness_issues():
    """
    显示所有完整性问题
    """
    if not all_completeness_issues:
        print("\n✅ 所有数据完整性检查通过，没有发现缺失数据")
        return
    
    print(f"\n⚠️  发现 {len(all_completeness_issues)} 个数据完整性问题:")
    print("="*60)
    
    for issue in all_completeness_issues:
        folder = issue['folder']
        model = issue['model']
        completeness_info = issue['completeness_info']
        overall_score = issue['overall_score']
        category_count = issue['category_count']
        
        print(f"\n🔍 {folder} - {model}:")
        print(f"   总分: {overall_score:.1f}% | Categories: {category_count}")
        print(f"   数据不完整: 预期 {completeness_info['total_expected']} 条，实际 {completeness_info['total_actual']} 条")
        
        for missing in completeness_info['missing_data']:
            print(f"   - {missing['category']}: 缺少 {missing['missing']} 条数据 ({missing['actual']}/{missing['expected']})")


def save_completeness_issues_to_file(output_dir: str = "results"):
    """
    将完整性问题保存到文件
    
    Args:
        output_dir: 输出目录
    """
    if not all_completeness_issues:
        return
    
    # 确保输出目录存在
    os.makedirs(output_dir, exist_ok=True)
    
    # 生成文件名（包含时间戳）
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"data_completeness_issues_{timestamp}.txt"
    filepath = os.path.join(output_dir, filename)
    
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(f"数据完整性问题报告\n")
        f.write(f"生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write(f"发现问题数量: {len(all_completeness_issues)}\n")
        f.write("="*60 + "\n\n")
        
        for issue in all_completeness_issues:
            folder = issue['folder']
            model = issue['model']
            completeness_info = issue['completeness_info']
            overall_score = issue['overall_score']
            category_count = issue['category_count']
            
            f.write(f"实验: {folder}\n")
            f.write(f"模型: {model}\n")
            f.write(f"总分: {overall_score:.1f}%\n")
            f.write(f"Categories数量: {category_count}\n")
            f.write(f"数据完整性: 预期 {completeness_info['total_expected']} 条，实际 {completeness_info['total_actual']} 条\n")
            f.write(f"缺失明细:\n")
            
            for missing in completeness_info['missing_data']:
                f.write(f"  - {missing['category']}: 缺少 {missing['missing']} 条数据 ({missing['actual']}/{missing['expected']})\n")
            
            f.write("\n" + "-"*40 + "\n\n")
    
    print(f"\n📄 完整性问题报告已保存到: {filepath}")


def print_main_results(main_results: Dict[str, Dict]):
    """
    打印主实验结果摘要
    """
    print(f"\n📊 主实验结果摘要:")
    print(f"处理了 {len(main_results)} 个模型的数据")
    
    # 使用模型管理器自动排序模型
    available_model_names = set(main_results.keys())
    available_models = model_manager.get_sorted_models(available_model_names)
    
    # 按排序顺序显示结果
    for file_name, display_name in available_models:
        print(f"\n🎯 {display_name}:")
        model_results = main_results[file_name]
        # 过滤出真正的category数据，排除特殊字段
        for category, result in model_results.items():
            if category not in ['completeness', 'overall_score', 'overall_aspect1_percentage', 'overall_aspect2_percentage']:
                if isinstance(result, dict) and 'calculated_scores' in result:
                    calc = result['calculated_scores']
                    print(f"  📌 {category}: {calc['aspect1_total']*100:.1f}%/{calc['aspect2_total']*100:.1f}%")


def main():
    parser = argparse.ArgumentParser(description="综合实验分析：同时处理主实验和消融实验数据，生成包含两个sheet的Excel文件")
    parser.add_argument('base_path', help='包含实验数据的基础路径（包含hints文件夹和主实验文件）')
    parser.add_argument('--output', '-o', help='输出Excel文件路径（默认：results.xlsx）', default='results.xlsx')
    parser.add_argument('--verbose', '-v', action='store_true', help='显示详细输出')
    parser.add_argument('--expected-count', '-c', type=int, default=50, help='每个category期望的数据条数（默认：50）')
    
    args = parser.parse_args()
    
    # 清理全局变量（防止多次运行时累积）
    global all_completeness_issues
    all_completeness_issues = []
    
    try:
        print("🚀 开始处理综合实验数据...")
        
        # 处理消融实验数据
        print("\n" + "="*50)
        print("🔬 消融实验数据处理")
        print("="*50)
        print(f"每个category期望数据条数: {args.expected_count}")
        ablation_results = process_all_hints_experiments(args.base_path, args.expected_count)
        
        # 处理主实验数据
        print("\n" + "="*50)
        print("📊 主实验数据处理")
        print("="*50)
        main_experiment_results = process_main_experiment(args.base_path, args.expected_count)
        
        # 检查是否有数据
        if not ablation_results and not main_experiment_results:
            print("❌ 没有成功处理任何实验数据")
            return 1
        
        # 打印结果摘要
        if args.verbose:
            if ablation_results:
                print_ablation_results(ablation_results)
            if main_experiment_results:
                print_main_results(main_experiment_results)
        
        # 确保输出文件有.xlsx扩展名
        output_file = args.output
        if not output_file.endswith('.xlsx'):
            output_file += '.xlsx'
        
        # 创建综合Excel文件
        print("\n" + "="*50)
        print("📝 生成Excel报告")
        print("="*50)
        
        # 合并所有结果用于Excel生成
        all_results_for_excel = {}
        if ablation_results:
            all_results_for_excel.update(ablation_results)
        if main_experiment_results:
            all_results_for_excel.update(main_experiment_results)
        
        create_comprehensive_excel(all_results_for_excel, output_file)
        
        # 显示和保存完整性问题
        print("\n" + "="*50)
        print("🔍 数据完整性检查结果")
        print("="*50)
        print_completeness_issues()
        
        # 保存完整性问题到文件
        if all_completeness_issues:
            output_dir = os.path.dirname(output_file) or "results"
            save_completeness_issues_to_file(output_dir)
        
        # 统计结果
        ablation_count = len(ablation_results) if ablation_results else 0
        main_experiment_count = len(main_experiment_results) if main_experiment_results else 0
        
        print(f"\n✅ 综合实验数据处理完成！")
        print(f"🔬 消融实验: {ablation_count} 个实验条件")
        print(f"📊 主实验: {main_experiment_count} 个模型")
        print(f"📁 输出文件: {output_file}")
        if all_completeness_issues:
            print(f"⚠️  发现 {len(all_completeness_issues)} 个数据完整性问题，详情请查看上述报告")
        
    except Exception as e:
        print(f"❌ 错误: {e}")
        import traceback
        traceback.print_exc()
        return 1
    
    return 0


if __name__ == "__main__":
    exit(main()) 