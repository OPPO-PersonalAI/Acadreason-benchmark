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
from typing import Dict, Any, Union


def is_valid_response(response) -> bool:
    if response is None:
        return False
    if isinstance(response, str):
        return bool(response.strip())
    if isinstance(response, dict):
        return bool(response)
    return True


class ClientsRegistry:
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.clients = {}
        self._init_clients()

    def _init_clients(self):
        for model_name, model_config in self.config['models'].items():
            client_config = {
                'api_key': model_config['api_key'],
                'base_url': model_config['base_url'],
                'model': model_config['model'],
                'max_tokens': model_config.get('max_tokens', 5000),
            }
            if 'temperature' in model_config:
                client_config['temperature'] = model_config['temperature']
            if 'reasoning' in model_config:
                client_config['reasoning'] = model_config['reasoning']
            self.clients[model_name] = client_config

    def call_llm(self, model_name: str, prompt: str, return_json: bool = False, max_retries: int = 3) -> Union[str, Dict]:
        # Local environment validation: only validate that current model's required fields are real values (not placeholders)
        model_config = self.clients.get(model_name)
        if not model_config:
            return None
        for key in ['api_key', 'base_url', 'model']:
            value = model_config.get(key)
            if not value or (isinstance(value, str) and value.startswith('${') and value.endswith('}')):
                # Missing required configuration: gracefully return None, let upper layer handle as failed/skip
                return None

        for attempt in range(max_retries):
            try:
                from openai import OpenAI
                client = OpenAI(
                    api_key=model_config['api_key'],
                    base_url=model_config['base_url'],
                    timeout=self.config['defaults'].get('timeout', 30)
                )
                messages = [{"role": "user", "content": prompt}]
                request_params = {
                    "model": model_config['model'],
                    "messages": messages,
                    "max_tokens": model_config['max_tokens']
                }
                if 'temperature' in model_config:
                    request_params["temperature"] = model_config['temperature']
                if 'reasoning' in model_config:
                    reasoning_config = model_config['reasoning']
                    if isinstance(reasoning_config, str) and "effort:" in reasoning_config:
                        effort_value = reasoning_config.split("effort:")[-1].strip()
                        reasoning_obj = {"effort": effort_value}
                    elif isinstance(reasoning_config, dict):
                        reasoning_obj = reasoning_config
                    else:
                        reasoning_obj = {"effort": "high"}
                    request_params["extra_body"] = {"reasoning": reasoning_obj}

                if return_json:
                    request_params["response_format"] = {"type": "json_object"}
                    if "Please return results in JSON format" not in prompt:
                        request_params["messages"][0]["content"] = prompt + "\n\nPlease return results in JSON format."

                response = client.chat.completions.create(**request_params)
                content = response.choices[0].message.content
                if return_json:
                    try:
                        return json.loads(content)
                    except json.JSONDecodeError:
                        return {"error": "Invalid JSON", "raw_content": content}
                return content
            except Exception as e:
                if attempt < max_retries - 1:
                    wait_time = 2 ** attempt
                    time.sleep(wait_time)
                else:
                    return None
