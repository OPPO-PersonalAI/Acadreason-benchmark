#!/usr/bin/env python3
"""
单独模型测试脚本
用法: 
python script/test_single_model.py gpt4o
python script/test_single_model.py o1
"""
import os
import sys
import time
import yaml
from openai import OpenAI

def load_env():
    if os.path.exists('.env'):
        with open('.env', 'r', encoding='utf-8') as f:
            for line in f:
                if line.strip() and not line.startswith('#') and '=' in line:
                    key, value = line.split('=', 1)
                    os.environ[key.strip()] = value.strip()

def replace_env_vars(obj):
    if isinstance(obj, dict):
        return {k: replace_env_vars(v) for k, v in obj.items()}
    elif isinstance(obj, str) and obj.startswith("${") and obj.endswith("}"):
        return os.getenv(obj[2:-1], obj)
    return obj

def test_model(model_name, config):
    print(f"🔧 测试: {model_name} ({config['model']})")
    
    try:
        client = OpenAI(api_key=config['api_key'], base_url=config['base_url'])
        
        start = time.time()
        response = client.chat.completions.create(
            model=config['model'],
            messages=[{"role": "user", "content": "你是谁?"}],
            max_tokens=5000  
        )
        elapsed = time.time() - start
        
        content = response.choices[0].message.content
        print(f"📝 响应内容: '{content}' (长度: {len(content) if content else 0})")
        print(f"⏱️ 耗时: {elapsed:.1f}s")
        
        if content and content.strip():
            print(f"✅ 成功")
            return True
        else:
            print(f"⚠️ 响应为空")
            return False
    except Exception as e:
        print(f"❌ 失败: {e}")
        return False

if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("用法: python script/test_single_model.py <model_name>")
        sys.exit(1)
    
    model_name = sys.argv[1]
    
    load_env()
    with open('config.yaml', 'r', encoding='utf-8') as f:
        config = replace_env_vars(yaml.safe_load(f))
    
    models = config.get('models', {})
    if model_name not in models:
        print(f"❌ 模型 '{model_name}' 不存在")
        print(f"可用: {', '.join(models.keys())}")
        sys.exit(1)
    
    test_model(model_name, models[model_name]) 