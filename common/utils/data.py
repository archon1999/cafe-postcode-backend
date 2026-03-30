from copy import deepcopy
from typing import Any


def deep_map(data: dict | list, func_cond, func_map, in_place=True):
    if not in_place:
        data = deepcopy(data)

    if isinstance(data, dict):
        for key, value in data.items():
            if isinstance(value, (list, dict)):
                deep_map(value, func_cond, func_map, True)
            elif func_cond(value):
                data[key] = func_map(value)
    elif isinstance(data, list):
        for index, value in enumerate(data):
            if isinstance(value, (list, dict)):
                deep_map(value, func_cond, func_map, True)
            elif func_cond(value):
                data[index] = func_map(value)

    return data


def null_to_zero(data: dict | list, in_place=True):
    return deep_map(data, lambda value: value is None, lambda _: 0, in_place)


def deep_round(data: dict | list, ndigits: int, in_place=True):
    return deep_map(data, lambda value: isinstance(value, float), lambda value: round(value, ndigits), in_place)


class EData:
    def __init__(self, data):
        self.data = data

    def null_to_zero(self):
        null_to_zero(self.data)
        return self

    def round(self, ndigits: int):
        deep_round(self.data, ndigits)
        return self

    def map(self, func_cond, func_map):
        deep_map(self.data, func_cond, func_map)
        return self


def key_mapper(obj: dict, key_dict: dict, delete_other=True):
    new_obj = {}
    for old_key, new_key in key_dict.items():
        new_obj[new_key] = obj[old_key]

    if not delete_other:
        for key, value in obj.items():
            if key not in key_dict:
                new_obj[key] = value

    return new_obj


def items_values_list(items: list[dict] | Any, *keys, flat=True):
    values_list = []
    for item in items:
        if len(keys) == 1 and flat:
            values_list.append(item[keys[0]])
        else:
            values_list.append(tuple(item[key] for key in keys))

    return values_list
