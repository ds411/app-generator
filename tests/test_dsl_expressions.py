"""Tests of the expressions of computed fields (`appgen.dsl.expressions`)."""

import pytest

from appgen.dsl.expressions import (
    Binary,
    Call,
    ExpressionError,
    FieldRef,
    Negate,
    Number,
    Total,
    date_paths,
    expression_paths,
    expression_totals,
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


def test_a_total_counts_or_adds_the_records_of_a_relation() -> None:
    expression = parse_expression("sum(lines.amount) - discount + count(votes) * 2")
    assert expression == Binary(
        "+",
        Binary("-", Total("sum", "lines", "amount"), FieldRef("discount")),
        Binary("*", Total("count", "votes"), Number("2")),
    )
    assert list(expression_paths(expression)) == ["discount"]
    assert list(expression_totals(expression)) == [
        Total("sum", "lines", "amount"),
        Total("count", "votes"),
    ]
    assert [str(t) for t in expression_totals(expression)] == ["sum(lines.amount)", "count(votes)"]
    for function in ("avg", "min", "max"):
        assert parse_expression(f"{function}(lines.amount)") == Total(function, "lines", "amount")


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("", "The expression is empty."),
        ("a +", "The expression ends too early."),
        ("a b", "Unexpected 'b'."),
        ("a % b", "Unexpected '%'."),
        ("(a + b", "The expression ends too early."),
        (
            "total(a, b)",
            "Unknown function 'total'. The functions are 'hours', 'days', 'count', 'sum', "
            "'avg', 'min', 'max'.",
        ),
        (
            "count(lines.amount)",
            "The function 'count' takes a relation, not 'lines.amount', for example count(lines).",
        ),
        (
            "sum(lines)",
            "The function 'sum' takes a field of a relation, not 'lines', for "
            "example sum(lines.amount).",
        ),
        (
            "avg(lines.product.price)",
            "The function 'avg' takes a field of a relation, not "
            "'lines.product.price', for example avg(lines.amount).",
        ),
        (
            "max(1)",
            "The function 'max' takes a field of a relation, not '1', for example "
            "max(lines.amount).",
        ),
        ("hours(a)", "The function 'hours' takes 2 arguments, not 1."),
    ],
)
def test_an_expression_that_does_not_parse_gives_a_message(text: str, message: str) -> None:
    with pytest.raises(ExpressionError) as error:
        parse_expression(text)
    assert str(error.value) == message
