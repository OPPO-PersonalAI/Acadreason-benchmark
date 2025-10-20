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
Single model test script
Usage: 
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
    print(f"🔧 Testing: {model_name} ({config['model']})")
    
    try:
        client = OpenAI(api_key=config['api_key'], base_url=config['base_url'])
        
        start = time.time()
        response = client.chat.completions.create(
            model=config['model'],
            messages=[{"role": "user", "content": "Who are you?"}],
            max_tokens=5000  
        )
        elapsed = time.time() - start
        
        content = response.choices[0].message.content
        print(f"📝 Response content: '{content}' (length: {len(content) if content else 0})")
        print(f"⏱️ Time elapsed: {elapsed:.1f}s")
        
        if content and content.strip():
            print(f"✅ Success")
            return True
        else:
            print(f"⚠️ Empty response")
            return False
    except Exception as e:
        print(f"❌ Failed: {e}")
        return False

if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python script/test_single_model.py <model_name>")
        sys.exit(1)
    
    model_name = sys.argv[1]
    
    load_env()
    with open('config.yaml', 'r', encoding='utf-8') as f:
        config = replace_env_vars(yaml.safe_load(f))
    
    models = config.get('models', {})
    if model_name not in models:
        print(f"❌ Model '{model_name}' does not exist")
        print(f"Available: {', '.join(models.keys())}")
        sys.exit(1)
    
    test_model(model_name, models[model_name])
