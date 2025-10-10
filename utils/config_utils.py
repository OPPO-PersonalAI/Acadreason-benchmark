import yaml
from typing import Any, Dict
from utils.env_utils import replace_env_vars

# 
def load_config(config_path: str = "config.yaml") -> Dict[str, Any]:
    with open(config_path, 'r', encoding='utf-8') as f:
        cfg = yaml.safe_load(f)

    return replace_env_vars(cfg, strict=False)


def main():
    try:
        cfg = load_config()
        print("config_utils: 已加载配置，包含键:", list(cfg.keys()))
    except Exception as e:
        print("config_utils: 加载失败", e)


if __name__ == "__main__":
    main()


