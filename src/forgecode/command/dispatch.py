"""/ 输入解析：提取命令名、判断是否以 / 开头。"""

from __future__ import annotations


def parse(input_text: str) -> tuple[str, bool]:
    """解析用户输入，返回 (命令名小写, 是否为斜杠命令)。

    规则：
    - 空/空白/非 "/" 开头 → ("", False)
    - 仅为 "/" → ("", True)  —— 让 lookup miss 走未命中提示
    - "//xxx" 或 "/ /xxx" → ("", True)  —— 无效输入按未命中
    - "/name xxx" → ("name", True)  —— 保留命令名，args 由 dispatch_slash 校验
    - "/name" → (name.lower(), True)
    """
    text = input_text.strip()
    if not text.startswith("/"):
        return ("", False)

    # 仅 "/"
    if text == "/":
        return ("", True)

    body = text[1:]  # 去掉前导 "/"
    # 若 body 为空或以 "/" 开头（如 "//double"），按未命中处理
    if not body or body.startswith("/"):
        return ("", True)

    # 若 body 有前导空白（如 "/ /help"），按未命中处理
    if body != body.lstrip():
        return ("", True)

    parts = body.split(maxsplit=1)
    return (parts[0].lower(), True)
