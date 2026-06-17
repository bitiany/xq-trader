"""表达式引擎 — 语法分析器（递归下降，产出 AST）"""

from __future__ import annotations

from dataclasses import dataclass, field

from .lexer import Token, TokenType

# ==================== AST 节点 ====================

@dataclass
class ASTNode:
    """AST 基类"""
    type: str


@dataclass
class NumberNode(ASTNode):
    value: float = 0.0


@dataclass
class IdentifierNode(ASTNode):
    name: str = ""


@dataclass
class CompareNode(ASTNode):
    op: str = ""
    left: ASTNode | None = None
    right: ASTNode | None = None


@dataclass
class LogicalNode(ASTNode):
    op: str = ""  # and / or
    left: ASTNode | None = None
    right: ASTNode | None = None


@dataclass
class FuncCallNode(ASTNode):
    name: str = ""
    args: list[ASTNode] = field(default_factory=list)


# ==================== 语法分析器 ====================

class Parser:
    """递归下降语法分析器

    语法:
        expression := or_expr
        or_expr    := and_expr ('or' and_expr)*
        and_expr   := cmp_expr ('and' cmp_expr)*
        cmp_expr   := primary (('>=' | '<=' | '>' | '<' | '==' | '!=') primary)?
        primary    := NUMBER | IDENTIFIER | FUNC_CALL | '(' expression ')'
        FUNC_CALL  := IDENTIFIER '(' arg_list ')'
    """

    def __init__(self, tokens: list[Token]) -> None:
        self.tokens = tokens
        self.pos = 0

    def _current(self) -> Token:
        return self.tokens[self.pos]

    def _advance(self) -> Token:
        tok = self.tokens[self.pos]
        self.pos += 1
        return tok

    def _expect(self, token_type: TokenType) -> Token:
        tok = self._current()
        if tok.type != token_type:
            msg = f"语法错误: 期望 {token_type}, 实际 {tok.type} (value={tok.value})"
            raise SyntaxError(msg)
        return self._advance()

    def parse(self) -> ASTNode:
        node = self._or_expr()
        if self._current().type != TokenType.EOF:
            msg = f"语法错误: 未消费的 token {self._current()}"
            raise SyntaxError(msg)
        return node

    def _or_expr(self) -> ASTNode:
        left = self._and_expr()
        while self._current().type == TokenType.OR:
            self._advance()
            right = self._and_expr()
            left = LogicalNode(type="logical", op="or", left=left, right=right)
        return left

    def _and_expr(self) -> ASTNode:
        left = self._cmp_expr()
        while self._current().type == TokenType.AND:
            self._advance()
            right = self._cmp_expr()
            left = LogicalNode(type="logical", op="and", left=left, right=right)
        return left

    def _cmp_expr(self) -> ASTNode:
        left = self._primary()
        if self._current().type == TokenType.COMPARE:
            op = self._advance().value
            right = self._primary()
            return CompareNode(type="compare", op=op, left=left, right=right)
        return left

    def _primary(self) -> ASTNode:
        tok = self._current()

        # 数字
        if tok.type == TokenType.NUMBER:
            self._advance()
            return NumberNode(type="number", value=tok.value)

        # 标识符 / 函数调用
        if tok.type == TokenType.IDENTIFIER:
            self._advance()
            name = tok.value
            # 判断是否为函数调用
            if self._current().type == TokenType.LPAREN:
                self._advance()  # 消费 (
                args = self._arg_list()
                self._expect(TokenType.RPAREN)
                return FuncCallNode(type="func_call", name=name, args=args)
            return IdentifierNode(type="identifier", name=name)

        # 括号表达式
        if tok.type == TokenType.LPAREN:
            self._advance()
            node = self._or_expr()
            self._expect(TokenType.RPAREN)
            return node

        msg = f"语法错误: 意外的 token {tok.type} (value={tok.value})"
        raise SyntaxError(msg)

    def _arg_list(self) -> list[ASTNode]:
        args: list[ASTNode] = []
        if self._current().type == TokenType.RPAREN:
            return args
        args.append(self._or_expr())
        while self._current().type == TokenType.COMMA:
            self._advance()
            args.append(self._or_expr())
        return args


def parse_expression(expr: str) -> ASTNode:
    """便捷函数：表达式字符串 → AST"""
    from .lexer import tokenize

    tokens = tokenize(expr)
    parser = Parser(tokens)
    return parser.parse()
