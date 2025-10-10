from typing import Dict, Mapping


def build_prompt_infer(template: str, item: Dict) -> str:
    try:
        return template.format(**item)
    except KeyError:
        return template


def build_prompt_safe(template: str, mapping: Mapping) -> str:
    """
    使用 format_map + defaultdict 实现的容错渲染：
    - 缺失字段自动回退为空字符串
    - 不会抛 KeyError
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


