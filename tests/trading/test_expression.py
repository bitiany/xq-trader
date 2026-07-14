"""表达式引擎单元测试 — 词法分析、语法分析、求值器、算子"""

import pandas as pd
import pytest

from xqtrader.domain.trading.rules.expression.evaluator import ExpressionEvaluator
from xqtrader.domain.trading.rules.expression.lexer import TokenType, tokenize
from xqtrader.domain.trading.rules.expression.operators import (
    op_abs,
    op_cross_above,
    op_cross_below,
    op_delta,
    op_log,
    op_ma,
    op_max,
    op_min,
    op_rank,
    op_sign,
    op_zscore,
)
from xqtrader.domain.trading.rules.expression.parser import (
    CompareNode,
    FuncCallNode,
    IdentifierNode,
    LogicalNode,
    NumberNode,
    parse_expression,
)


class TestLexer:
    """词法分析器测试"""

    def test_number(self):
        tokens = tokenize("42")
        assert tokens[0].type == TokenType.NUMBER
        assert tokens[0].value == 42.0

    def test_float(self):
        tokens = tokenize("3.14")
        assert tokens[0].type == TokenType.NUMBER
        assert tokens[0].value == 3.14

    def test_negative_number(self):
        tokens = tokenize("-5.2")
        assert tokens[0].type == TokenType.NUMBER
        assert tokens[0].value == -5.2

    def test_identifier(self):
        tokens = tokenize("roe")
        assert tokens[0].type == TokenType.IDENTIFIER
        assert tokens[0].value == "roe"

    def test_and_keyword(self):
        tokens = tokenize("a and b")
        assert tokens[1].type == TokenType.AND

    def test_or_keyword(self):
        tokens = tokenize("a or b")
        assert tokens[1].type == TokenType.OR

    def test_compare_operators(self):
        for op_str in [">", "<", ">=", "<=", "==", "!="]:
            tokens = tokenize(f"x {op_str} y")
            assert tokens[1].type == TokenType.COMPARE
            assert tokens[1].value == op_str

    def test_func_call(self):
        tokens = tokenize("rank(roe)")
        assert tokens[0].type == TokenType.IDENTIFIER
        assert tokens[0].value == "rank"
        assert tokens[1].type == TokenType.LPAREN
        assert tokens[2].type == TokenType.IDENTIFIER
        assert tokens[3].type == TokenType.RPAREN

    def test_complex_expression(self):
        tokens = tokenize("rank(ep_ttm) > 0.5 and rank(mom_20d) > 0.5")
        types = [t.type for t in tokens if t.type != TokenType.EOF]
        assert types == [
            TokenType.IDENTIFIER, TokenType.LPAREN, TokenType.IDENTIFIER,
            TokenType.RPAREN, TokenType.COMPARE, TokenType.NUMBER,
            TokenType.AND,
            TokenType.IDENTIFIER, TokenType.LPAREN, TokenType.IDENTIFIER,
            TokenType.RPAREN, TokenType.COMPARE, TokenType.NUMBER,
        ]

    def test_unknown_char_raises(self):
        with pytest.raises(SyntaxError, match="未知字符"):
            tokenize("x @ y")


class TestParser:
    """语法分析器测试"""

    def test_number_literal(self):
        ast = parse_expression("42")
        assert isinstance(ast, NumberNode)
        assert ast.value == 42.0

    def test_identifier(self):
        ast = parse_expression("roe")
        assert isinstance(ast, IdentifierNode)
        assert ast.name == "roe"

    def test_compare(self):
        ast = parse_expression("roe > 12")
        assert isinstance(ast, CompareNode)
        assert ast.op == ">"
        assert isinstance(ast.left, IdentifierNode)
        assert isinstance(ast.right, NumberNode)

    def test_and_expression(self):
        ast = parse_expression("roe > 12 and pe_ttm < 25")
        assert isinstance(ast, LogicalNode)
        assert ast.op == "and"

    def test_or_expression(self):
        ast = parse_expression("roe > 12 or pe_ttm < 25")
        assert isinstance(ast, LogicalNode)
        assert ast.op == "or"

    def test_func_call_no_args(self):
        # rank() 无参数 — 语法上合法，运行时会报错
        ast = parse_expression("rank(roe)")
        assert isinstance(ast, FuncCallNode)
        assert ast.name == "rank"
        assert len(ast.args) == 1

    def test_func_call_with_number_arg(self):
        ast = parse_expression("delta(mom_20d, 5)")
        assert isinstance(ast, FuncCallNode)
        assert ast.name == "delta"
        assert len(ast.args) == 2

    def test_nested_func(self):
        ast = parse_expression("rank(zscore(roe))")
        assert isinstance(ast, FuncCallNode)
        assert ast.name == "rank"
        inner = ast.args[0]
        assert isinstance(inner, FuncCallNode)
        assert inner.name == "zscore"

    def test_parenthesized(self):
        ast = parse_expression("(roe > 12)")
        assert isinstance(ast, CompareNode)

    def test_syntax_error_unexpected_token(self):
        with pytest.raises(SyntaxError):
            parse_expression("and roe")


class TestEvaluator:
    """求值器测试"""

    def setup_method(self):
        self.evaluator = ExpressionEvaluator()

    def test_number_literal(self):
        ast = parse_expression("42")
        result = self.evaluator.evaluate(ast)
        assert result == 42.0

    def test_identifier_from_factor_values(self):
        ast = parse_expression("roe")
        result = self.evaluator.evaluate(ast, factor_values={"roe": 15.5})
        assert result == 15.5

    def test_compare_true(self):
        ast = parse_expression("roe > 12")
        result = self.evaluator.evaluate(ast, factor_values={"roe": 15.0})
        assert result is True

    def test_compare_false(self):
        ast = parse_expression("roe > 12")
        result = self.evaluator.evaluate(ast, factor_values={"roe": 10.0})
        assert result is False

    def test_and_expression(self):
        ast = parse_expression("roe > 12 and pe_ttm < 25")
        result = self.evaluator.evaluate(
            ast, factor_values={"roe": 15.0, "pe_ttm": 20.0},
        )
        assert result is True

    def test_and_expression_partial(self):
        ast = parse_expression("roe > 12 and pe_ttm < 25")
        result = self.evaluator.evaluate(
            ast, factor_values={"roe": 15.0, "pe_ttm": 30.0},
        )
        assert result is False

    def test_or_expression(self):
        ast = parse_expression("roe > 12 or pe_ttm < 25")
        result = self.evaluator.evaluate(
            ast, factor_values={"roe": 10.0, "pe_ttm": 20.0},
        )
        assert result is True

    def test_cross_section_rank(self):
        """截面模式：rank() 对整列操作"""
        df = pd.DataFrame(
            {"roe": [10.0, 15.0, 20.0, 5.0]},
            index=["A", "B", "C", "D"],
        )
        ast = parse_expression("rank(roe)")
        result = self.evaluator.evaluate(ast, cross_section_df=df)
        assert isinstance(result, pd.Series)
        assert abs(result.loc["C"] - 1.0) < 0.01  # 最高排名 1.0
        assert abs(result.loc["D"] - 0.25) < 0.01  # 最低排名 0.25

    def test_cross_section_compare(self):
        """截面模式：rank(roe) > 0.5 返回 Series[bool]"""
        df = pd.DataFrame(
            {"roe": [10.0, 15.0, 20.0, 5.0]},
            index=["A", "B", "C", "D"],
        )
        ast = parse_expression("rank(roe) > 0.5")
        result = self.evaluator.evaluate(ast, cross_section_df=df)
        assert isinstance(result, pd.Series)
        assert result.loc["C"] is True or result.loc["C"] == True  # noqa: E712
        assert result.loc["D"] is False or result.loc["D"] == False  # noqa: E712

    def test_unknown_identifier_raises(self):
        ast = parse_expression("unknown_factor")
        with pytest.raises(KeyError, match="未知标识符"):
            self.evaluator.evaluate(ast, factor_values={"roe": 15.0})


class TestOperators:
    """算子函数测试"""

    def test_rank(self):
        s = pd.Series([10, 20, 30, 5])
        result = op_rank(s)
        assert abs(result.iloc[3] - 0.25) < 0.01  # 5 最低
        assert abs(result.iloc[2] - 1.0) < 0.01  # 30 最高

    def test_zscore(self):
        s = pd.Series([1.0, 2.0, 3.0, 4.0, 5.0])
        result = op_zscore(s)
        assert abs(result.mean()) < 1e-10  # 均值约 0

    def test_delta(self):
        s = pd.Series([10, 12, 15, 14, 18], dtype=float)
        result = op_delta(s, 1)
        assert pd.isna(result.iloc[0])
        assert result.iloc[1] == 2.0
        assert result.iloc[2] == 3.0

    def test_ma(self):
        s = pd.Series([1.0, 2.0, 3.0, 4.0, 5.0])
        result = op_ma(s, 3)
        assert abs(result.iloc[2] - 2.0) < 0.01
        assert abs(result.iloc[4] - 4.0) < 0.01

    def test_cross_above(self):
        a = pd.Series([1.0, 1.5, 3.0])
        b = pd.Series([2.0, 2.0, 2.0])
        assert op_cross_above(a, b) is True

    def test_cross_above_not_crossed(self):
        a = pd.Series([3.0, 2.5, 1.0])
        b = pd.Series([2.0, 2.0, 2.0])
        assert op_cross_above(a, b) is False

    def test_cross_below(self):
        a = pd.Series([3.0, 2.5, 1.0])
        b = pd.Series([2.0, 2.0, 2.0])
        assert op_cross_below(a, b) is True

    def test_cross_above_with_scalar(self):
        a = pd.Series([-1.0, -0.5, 1.0])
        assert op_cross_above(a, 0.0) is True

    def test_abs_scalar(self):
        assert op_abs(-5.0) == 5.0

    def test_abs_series(self):
        s = pd.Series([-1.0, -2.0, 3.0])
        result = op_abs(s)
        assert list(result) == [1.0, 2.0, 3.0]

    def test_log_scalar(self):
        result = op_log(2.718281828)
        assert abs(result - 1.0) < 0.001

    def test_sign_scalar(self):
        assert op_sign(-5.0) == -1.0
        assert op_sign(5.0) == 1.0

    def test_max_min(self):
        assert op_max(3.0, 5.0) == 5.0
        assert op_min(3.0, 5.0) == 3.0
