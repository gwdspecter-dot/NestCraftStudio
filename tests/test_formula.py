# -*- coding: utf-8 -*-
"""Тесты вычислителя формул core/formula.py: функции с несколькими аргументами и десятичная запятая."""

from __future__ import annotations

import unittest

from core.formula import eval_math_expression, is_formula_text


class TestFormulaMultiArgAndDecimalComma(unittest.TestCase):
    def test_decimal_comma_in_numbers_and_arithmetic(self) -> None:
        self.assertAlmostEqual(eval_math_expression("568,5"), 568.5)
        self.assertAlmostEqual(eval_math_expression("= 568,5 + 15,5"), 584.0)
        self.assertAlmostEqual(eval_math_expression("+= 12,5", current_value=100.0), 112.5)

    def test_multi_arg_functions_with_space_after_comma(self) -> None:
        self.assertAlmostEqual(eval_math_expression("max(1, 2)"), 2.0)
        self.assertAlmostEqual(eval_math_expression("min(10, 3, 7)"), 3.0)
        self.assertAlmostEqual(
            eval_math_expression("min(w, 500)", variables={"w": 568.0}),
            500.0,
        )
        self.assertAlmostEqual(eval_math_expression("round(10.556, 2)"), 10.56)
        self.assertAlmostEqual(eval_math_expression("round(10.5, 0)"), 10.0)

    def test_multi_arg_functions_without_spaces(self) -> None:
        self.assertAlmostEqual(eval_math_expression("max(1,2)"), 2.0)
        self.assertAlmostEqual(eval_math_expression("min(10,3,7)"), 3.0)
        self.assertAlmostEqual(eval_math_expression("round(10.5,0)"), 10.0)
        self.assertAlmostEqual(
            eval_math_expression("max(w,500)", variables={"w": 568.0}),
            568.0,
        )

    def test_multi_arg_functions_with_decimal_comma_and_semicolon(self) -> None:
        # Десятичная запятая внутри аргументов, разделённых пробелом после запятой или точкой с запятой
        self.assertAlmostEqual(eval_math_expression("max(1,5, 2,25)"), 2.25)
        self.assertAlmostEqual(eval_math_expression("min(10,5; 3,25)"), 3.25)
        self.assertAlmostEqual(eval_math_expression("round(10,556, 2)"), 10.56)
        self.assertAlmostEqual(eval_math_expression("round(10,556;2)"), 10.56)

    def test_nested_functions_and_expressions(self) -> None:
        self.assertAlmostEqual(
            eval_math_expression("max(min(w, 600), 300 - 16,5)", variables={"w": 450.0}),
            450.0,
        )
        self.assertTrue(is_formula_text("max(1, 2)"))
        self.assertTrue(is_formula_text("min(w, 500)"))


if __name__ == "__main__":
    unittest.main()
