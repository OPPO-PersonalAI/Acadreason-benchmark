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

import yaml
from typing import Any, Dict
from utils.env_utils import replace_env_vars


def load_config(config_path: str = "config.yaml") -> Dict[str, Any]:
    """Load configuration from YAML file"""
    with open(config_path, 'r', encoding='utf-8') as f:
        cfg = yaml.safe_load(f)

    return replace_env_vars(cfg, strict=False)


def main():
    try:
        cfg = load_config()
        print("config_utils: loaded configuration with keys:", list(cfg.keys()))
    except Exception as e:
        print("config_utils: failed to load", e)


if __name__ == "__main__":
    main()
