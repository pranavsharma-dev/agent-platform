import pytest

from src.tools.calculator import CalculatorTool, safe_eval


class TestSafeEval:
    def test_addition(self):
        assert safe_eval("2 + 3") == 5.0

    def test_subtraction(self):
        assert safe_eval("10 - 4") == 6.0

    def test_multiplication(self):
        assert safe_eval("6 * 7") == 42.0

    def test_division(self):
        assert safe_eval("10 / 4") == 2.5

    def test_modulo(self):
        assert safe_eval("10 % 3") == 1.0

    def test_power(self):
        assert safe_eval("2 ** 3") == 8.0

    def test_negation(self):
        assert safe_eval("-5 + 3") == -2.0

    def test_parentheses(self):
        assert safe_eval("(2 + 3) * 4") == 20.0

    def test_nested_parentheses(self):
        assert safe_eval("((1 + 2) * (3 + 4))") == 21.0

    def test_complex_expression(self):
        assert safe_eval("2 ** 3 + 4 * 5 - 1") == 27.0

    def test_decimal(self):
        assert safe_eval("3.14 * 2") == pytest.approx(6.28)

    def test_division_by_zero(self):
        with pytest.raises(ZeroDivisionError):
            safe_eval("1 / 0")

    def test_rejects_strings(self):
        with pytest.raises((ValueError, SyntaxError)):
            safe_eval("'hello'")

    def test_rejects_function_calls(self):
        with pytest.raises((ValueError, SyntaxError)):
            safe_eval("__import__('os').system('ls')")

    def test_rejects_names(self):
        with pytest.raises((ValueError, SyntaxError)):
            safe_eval("x + 1")

    def test_rejects_empty(self):
        with pytest.raises(SyntaxError):
            safe_eval("")


class TestCalculatorTool:
    @pytest.fixture
    def calculator(self):
        return CalculatorTool()

    def test_schema_has_required_fields(self, calculator):
        schema = calculator.schema()
        assert schema["name"] == "calculator"
        assert "description" in schema
        assert "input_schema" in schema
        assert "expression" in schema["input_schema"]["properties"]

    async def test_execute_integer_result(self, calculator):
        result = await calculator.execute({"expression": "2 + 3"})
        assert result == "5"

    async def test_execute_float_result(self, calculator):
        result = await calculator.execute({"expression": "10 / 4"})
        assert result == "2.5"

    async def test_execute_raises_on_bad_input(self, calculator):
        with pytest.raises(Exception):
            await calculator.execute({"expression": "not math"})
