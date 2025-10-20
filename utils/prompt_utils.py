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

from typing import Dict, Mapping


def build_prompt_infer(template: str, item: Dict) -> str:
    try:
        return template.format(**item)
    except KeyError:
        return template


def build_prompt_safe(template: str, mapping: Mapping) -> str:
    """
    Fault-tolerant rendering using format_map + defaultdict:
    - Missing fields automatically fallback to empty string
    - Won't raise KeyError
    """
    try:
        from collections import defaultdict
        return template.format_map(defaultdict(str, dict(mapping)))
    except Exception:
        return template


def main():
    tpl = "Hello {name}!"
    print(build_prompt_infer(tpl, {"name": "world"}))


if __name__ == "__main__":
    main()
