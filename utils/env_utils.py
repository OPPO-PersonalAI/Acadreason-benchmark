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

import os


def load_env_file(env_path: str = ".env"):
    """Load environment variables from .env file"""
    if os.path.exists(env_path):
        with open(env_path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    key, value = line.split('=', 1)
                    os.environ[key.strip()] = value.strip()


def replace_env_vars(obj, strict: bool = False):
    """Recursively replace environment variable references in config, format ${VAR}

    Args:
        strict: When True, missing environment variables will raise an exception;
                When False (default), placeholders are kept as-is and validated later at usage time.
    """
    if isinstance(obj, dict):
        return {k: replace_env_vars(v, strict=strict) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [replace_env_vars(item, strict=strict) for item in obj]
    elif isinstance(obj, str):
        if obj.startswith("${") and obj.endswith("}"):
            env_var = obj[2:-1]
            value = os.getenv(env_var)
            if value is None:
                if strict:
                    raise ValueError(f"Environment variable {env_var} is not set")
                # In non-strict mode, keep placeholder for later validation at usage time
                return obj
            return value
        return obj
    else:
        return obj


def main():
    load_env_file()
    import sys
    if len(sys.argv) > 1:
        text = sys.argv[1]
        result = replace_env_vars(text, strict=False)
        print(result)
    else:
        print("env_utils: loaded .env and supports ${VAR} replacement")


if __name__ == "__main__":
    main()
