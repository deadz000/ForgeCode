"""Hook 条件求值：把 permission.Matcher 应用到 payload 的字段路径上。"""

from __future__ import annotations

import json

from forgecode.hook.rule import CombineMode, Condition, Payload


def get_by_path(p: Payload, path: str) -> str:
    """按 '.' 分隔的字段路径取值，返回字符串。

    路径不存在、中途遇 None 或非 dict → 返回空串，不报错。
    bool / int / float 用 str() 转换（True → "True"，与 N6 输出一致）；
    嵌套对象转 json.dumps(sort_keys=True)。
    """
    if not path:
        return ""
    parts = path.split(".")
    cur: object = p
    for part in parts:
        if not isinstance(cur, dict):
            return ""
        cur = cur.get(part)
        if cur is None:
            return ""
    return _stringify(cur)


def _stringify(value: object) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, bool):
        return "True" if value else "False"
    if isinstance(value, (int, float)):
        return str(value)
    return json.dumps(value, sort_keys=True, ensure_ascii=False)


def eval_condition(c: Condition | None, p: Payload) -> bool:
    """求值条件表达式。

    - c is None → 无条件，返回 True
    - 遍历原子的 get_by_path + matcher.match
    - ALL_OF 要求全部 True；ANY_OF 要求至少一个 True
    """
    if c is None:
        return True
    if not c.atoms:
        return True
    hits = [atom.matcher.match(get_by_path(p, atom.field)) for atom in c.atoms]
    if c.mode is CombineMode.ALL_OF:
        return all(hits)
    return any(hits)
