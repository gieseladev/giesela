import os
import rapidjson
from typing import Any, Dict, List

import yaml

__all__ = ["to_redis", "from_redis", "flatten_data", "unflatten_data", "unflatten_list", "lower_data", "lower_list", "depth_update", "get_env_config"]


def to_redis(data: Dict[str, Any], prefix: str) -> Dict[str, str]:
    data = flatten_data(data)
    final = {}
    for key, value in data.items():
        value = rapidjson.dumps(value)
        final[prefix + key] = value
    return final


def from_redis(data):
    if not isinstance(data, dict):
        return rapidjson.loads(data)

    final = {}
    for key, value in data.items():
        value = rapidjson.loads(value)
        final[key] = value
    return unflatten_data(final)


def flatten_data(data: Dict[str, Any]) -> Dict[str, Any]:
    flat = {}
    for key, value in data.items():
        if isinstance(value, dict):
            value = flatten_data(value)
            for sub_key, val in value.items():
                flat[f"{key}.{sub_key}"] = val
        else:
            flat[key] = value

    return flat


def unflatten_data(data: Dict[str, Any], delimiter: str = ".") -> Dict[str, Any]:
    final: Dict[str, Any] = {}

    for key, value in data.items():
        if isinstance(value, list):
            value = unflatten_list(value)

        *parts, key = key.split(delimiter)

        target = final
        for part in parts:
            target.setdefault(part, {})
            target = target[part]

        target[key] = value
    return final


def unflatten_list(data: List[Any]) -> List[Any]:
    value = []
    for item in data:
        if isinstance(item, dict):
            item = unflatten_data(item)
        elif isinstance(item, list):
            item = unflatten_list(item)
        value.append(item)
    return value


def lower_data(data: Dict[str, Any]) -> Dict[str, Any]:
    final = {}
    for key, value in data.items():
        if isinstance(value, dict):
            value = lower_data(value)
        elif isinstance(value, list):
            value = lower_list(value)

        final[key.lower()] = value

    return final


def lower_list(data: List[Any]) -> List[Any]:
    value = []
    for item in data:
        if isinstance(item, dict):
            item = lower_data(item)
        elif isinstance(item, list):
            item = lower_list(item)
        value.append(item)
    return value


def depth_update(a: dict, b: dict):
    for key, b_val in b.items():
        a_val = a.get(key)

        if isinstance(a_val, dict) and isinstance(b_val, dict):
            depth_update(a_val, b_val)
        else:
            a[key] = b_val


def get_env_config():
    env = os.environ.copy()
    for key, value in env.items():
        try:
            decoded_value = yaml.safe_load(value)
        except Exception as e:
            # storing the exception so we can raise it later if the value is actually required
            env[key] = e
        else:
            env[key] = decoded_value

    return unflatten_data(env, delimiter="__")
