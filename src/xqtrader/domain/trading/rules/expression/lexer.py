"""表达式引擎 — 词法分析器"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, auto
from typing import Any


class TokenType(Enum):
    NUMBER = auto()
    IDENTIFIER = auto()
    AND = auto()
    OR = auto()
    COMPARE = auto()  # >= <= > < == !=
    LPAREN = auto()
    RPAREN = auto()
    COMMA = auto()
    EOF = auto()


@dataclass
class Token:
    type: TokenType
    value: Any = None


_COMPARE_OPS = {">=", "<=", ">", "<", "==", "!="}
_KEYWORDS = {"and": TokenType.AND, "or": TokenType.OR}


def tokenize(expr: str) -> list[Token]:
    """将表达式字符串转换为 Token 列表"""
    tokens: list[Token] = []
    i = 0
    n = len(expr)

    while i < n:
        ch = expr[i]

        # 跳过空白
        if ch in " \t\n\r":
            i += 1
            continue

        # 数字（含小数和负数前缀）
        if ch.isdigit() or (ch == "-" and i + 1 < n and expr[i + 1].isdigit()):
            start = i
            if ch == "-":
                i += 1
            while i < n and expr[i].isdigit():
                i += 1
            if i < n and expr[i] == ".":
                i += 1
                while i < n and expr[i].isdigit():
                    i += 1
            tokens.append(Token(TokenType.NUMBER, float(expr[start:i])))
            continue

        # 标识符 / 关键字
        if ch.isalpha() or ch == "_":
            start = i
            while i < n and (expr[i].isalnum() or expr[i] == "_"):
                i += 1
            word = expr[start:i]
            token_type = _KEYWORDS.get(word, TokenType.IDENTIFIER)
            tokens.append(Token(token_type, word))
            continue

        # 双字符比较运算符
        if i + 1 < n and expr[i : i + 2] in _COMPARE_OPS:
            tokens.append(Token(TokenType.COMPARE, expr[i : i + 2]))
            i += 2
            continue

        # 单字符比较运算符
        if ch in "><":
            tokens.append(Token(TokenType.COMPARE, ch))
            i += 1
            continue

        # 括号和逗号
        if ch == "(":
            tokens.append(Token(TokenType.LPAREN))
            i += 1
            continue
        if ch == ")":
            tokens.append(Token(TokenType.RPAREN))
            i += 1
            continue
        if ch == ",":
            tokens.append(Token(TokenType.COMMA))
            i += 1
            continue

        msg = f"词法分析错误: 未知字符 '{ch}' 在位置 {i}"
        raise SyntaxError(msg)

    tokens.append(Token(TokenType.EOF))
    return tokens
