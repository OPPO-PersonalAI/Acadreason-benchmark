import os


def load_env_file(env_path: str = ".env"):
    """加载.env文件中的环境变量"""
    if os.path.exists(env_path):
        with open(env_path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    key, value = line.split('=', 1)
                    os.environ[key.strip()] = value.strip()


def replace_env_vars(obj, strict: bool = False):
    """递归替换配置中的环境变量引用，形如 ${VAR}

    参数:
        strict: 为 True 时，缺失的环境变量会抛出异常；
                为 False 时（默认），保留占位符原样，延迟到实际使用处再校验。
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
                    raise ValueError(f"环境变量 {env_var} 未设置")
                # 非严格模式下，保留占位符，后续在实际用到时再校验
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
        print("env_utils: 已加载 .env 并支持 ${VAR} 替换")


if __name__ == "__main__":
    main()


