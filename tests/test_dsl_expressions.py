"""Tests of the expressions of computed fields (`appgen.dsl.expressions`)."""

import pytest

from appgen.dsl.expressions import (
    Binary,
    Call,
    ExpressionError,
    FieldRef,
    Negate,
    Number,
    date_paths,
    expression_paths,
    parse_expression,
)


def test_an_expression_has_the_usual_order_of_the_operators() -> None:
    assert parse_expression("a + b * 2") == Binary(
        "+", FieldRef("a"), Binary("*", FieldRef("b"), Number("2"))
    )
    assert parse_expression("(a + b) / -c") == Binary(
        "/", Binary("+", FieldRef("a"), FieldRef("b")), Negate(FieldRef("c"))
    )


def test_a_function_takes_field_paths() -> None:
    expression = parse_expression("hours(starts_at, ends_at) * room.hourly_rate")
    assert expression == Binary(
        "*",
        Call("hours", (FieldRef("starts_at"), FieldRef("ends_at"))),
        FieldRef("room.hourly_rate"),
    )
    assert list(expression_paths(expression)) == ["starts_at", "ends_at", "room.hourly_rate"]
    assert list(date_paths(expression)) == ["starts_at", "ends_at"]


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("", "The expression is empty."),
        ("a +", "The expression ends too early."),
        ("a b", "Unexpected 'b'."),
        ("a % b", "Unexpected '%'."),
        ("(a + b", "The expression ends too early."),
        ("sum(a, b)", "Unknown function 'sum'. The functions are 'hours', 'days'."),
        ("hours(a)", "The function 'hours' takes 2 arguments, not 1."),
    ],
)
def test_an_expression_that_does_not_parse_gives_a_message(text: str, message: str) -> None:
    with pytest.raises(ExpressionError) as error:
        parse_expression(text)
    assert str(error.value) == message
