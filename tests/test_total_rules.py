"""The compare rules over the totals of the lines of a record (ADR 0034)."""

from pathlib import Path
from textwrap import dedent

import pytest

from appgen.bindings import fastapi, nextjs
from appgen.bindings.fastapi.model import python_app
from appgen.dsl import AppDefinition, load_definition, load_definition_text, validate_definition
from appgen.gen.binding import Binding
from appgen.gen.generator import generate
from appgen.gen.render import GenerationError

ROOT = Path(__file__).parent.parent
FIXTURE = ROOT / "tests" / "fixtures" / "totals.yaml"

BASE = dedent(
    """\
    version: 0
    app: { name: books, title: Books }
    entities:
      Entry:
        display_field: memo
        fields:
          memo: { type: string, required: true }
          limit_amount: { type: decimal, scale: 2, min: 0 }
        relations:
          lines: { kind: one_to_many, target: Line, inverse: entry }
          tags: { kind: many_to_many, target: Tag }
        rules:
          balanced:
            kind: compare
            field: sum(lines.debit)
            op: eq
            other: sum(lines.credit)
            message: The debits and the credits must balance.
          {more_rules}
      Line:
        fields:
          memo: { type: string }
          debit: { type: decimal, scale: 2, min: 0, default: 0 }
          credit: { type: decimal, scale: 2, min: 0, default: 0 }
        relations:
          entry: { kind: many_to_one, target: Entry, required: true, inverse: lines }
      Tag:
        fields:
          name: { type: string }
    operations:
      create_entry: { kind: create, entity: Entry, lines: [lines] }
      update_entry: { kind: update, entity: Entry, lines: [lines] }
    """
)


def definition_text(more_rules: str = "") -> str:
    """Return the base definition with more rules of the entity `Entry`."""
    indented = "".join(f"      {line}\n" for line in more_rules.splitlines())
    return BASE.replace("      {more_rules}\n", indented)


def problems(text: str) -> list[tuple[str, str]]:
    definition = load_definition_text(text, "app.yaml")
    return [(d.code, d.message) for d in validate_definition(definition)]


def files_of(definition: AppDefinition, binding: Binding) -> dict[str, str]:
    return {f.path: f.content for f in generate(definition, binding).files}


def test_a_compare_rule_compares_the_totals_of_the_lines() -> None:
    within = "within: { kind: compare, field: sum(lines.debit), op: lte, other: limit_amount, "
    assert problems(definition_text(within + "message: Over. }")) == []
    assert (
        problems(
            definition_text(
                "lines: { kind: compare, field: count(lines), op: gte, "
                "other: limit_amount, message: Few. }"
            )
        )
        == []
    )


@pytest.mark.parametrize(
    ("rule", "expected"),
    [
        (
            "{ kind: compare, field: count(tags), op: eq, other: count(lines), message: X }",
            (
                "unsuitable-field",
                "The total 'count(tags)' of a compare rule needs a one_to_many relation, but "
                "'Entry.tags' is many_to_many.",
            ),
        ),
        (
            "{ kind: compare, field: count(lines), op: eq, other: memo, message: X }",
            ("unsuitable-field", "A compare rule cannot compare a 'integer' with a 'string'."),
        ),
        (
            "{ kind: compare, field: sum(lines.memo), op: eq, other: limit_amount, message: X }",
            (
                "unsuitable-field",
                "The total 'sum(lines.memo)' needs an 'integer' or a 'decimal' field, but "
                "'Line.memo' is 'string'.",
            ),
        ),
        (
            "{ kind: compare, field: sum(liens.debit), op: eq, other: limit_amount, message: X }",
            ("unknown-reference", "The entity 'Entry' has no relation 'liens'."),
        ),
        (
            "{ kind: compare, field: sum(lines), op: eq, other: limit_amount, message: X }",
            (
                "invalid-value",
                "The total 'sum(lines)' is not valid: The function 'sum' takes a field of a "
                "relation, not 'lines', for example sum(lines.amount).",
            ),
        ),
    ],
    ids=["many-to-many", "types", "text-field", "relation", "no-field"],
)
def test_a_total_of_a_compare_rule_adds_a_number_field_of_the_lines(
    rule: str, expected: tuple[str, str]
) -> None:
    assert problems(definition_text(f"bad: {rule}")) == [expected]


def test_the_seed_records_keep_the_rules_with_their_seed_lines() -> None:
    seed = dedent(
        """\
        seed:
          Entry:
            records:
              rent: { memo: Rent }
              short: { memo: Short }
          Line:
            records:
              rent_debit: { entry: rent, debit: 500.1 }
              rent_credit: { entry: rent, credit: 500.1 }
              short_debit: { entry: short, debit: 20 }
              short_credit: { entry: short, credit: 19.5 }
        """
    )
    definition = load_definition_text(definition_text() + seed, "app.yaml")
    [problem] = validate_definition(definition)
    assert problem.code == "invalid-record"
    assert problem.message == (
        "The record does not keep the rule 'balanced': The debits and the credits must balance."
    )
    assert problem.hint == "The seed records of the lines give the totals of the rule."
    assert problem.element_id == "seed.Entry.records.short"


def test_the_fastapi_repository_checks_the_rules_with_totals_after_the_lines() -> None:
    files = files_of(load_definition(FIXTURE), fastapi.BINDING)
    repository = files["app/features/journal_entries/repository.py"]
    assert (
        "async def check_totals(session: AsyncSession, record: JournalEntry) -> None:" in repository
    )
    assert '    await session.refresh(record, ["sum_lines_debit", "sum_lines_credit"])' in (
        repository
    )
    assert 'if not compare(record.sum_lines_debit, "eq", record.sum_lines_credit):' in repository
    assert 'if not compare(record.sum_lines_debit, "lte", record.debit_limit):' in repository
    # create and update check the rules; the rules without totals stay out of check_rules.
    assert repository.count("    await check_totals(session, record)\n") == 2
    assert "async def check_rules(" not in repository
    create = files["app/features/journal_entries/create_journal_entry.py"]
    lines = create.index("await repository.write_lines(session, record, data.lines)")
    check = create.index("await repository.check_totals(session, record)")
    assert lines < check < create.index("await commit(session)")
    assert "from app.core.rules import compare" in repository
    assert "app/core/rules.py" in files


def test_a_total_that_only_the_rules_use_is_a_deferred_column_property() -> None:
    models = files_of(load_definition(FIXTURE), fastapi.BINDING)["app/models.py"]
    # The computed field total_debit uses sum(lines.debit): the queries read it.
    assert (
        "JournalEntry.sum_lines_debit = column_property(\n"
        '    totals.total("sum", JournalLine, JournalLine.debit, '
        "JournalLine.entry_id == JournalEntry.id),\n)"
    ) in models
    assert (
        "JournalEntry.sum_lines_credit = column_property(\n"
        '    totals.total("sum", JournalLine, JournalLine.credit, '
        "JournalLine.entry_id == JournalEntry.id),\n"
        "    deferred=True,\n)"
    ) in models
    assert "# @trace entities.JournalEntry.rules.balanced\nJournalEntry.sum_lines_credit" in models


def test_the_fastapi_test_samples_keep_the_rules_with_totals() -> None:
    model = python_app(load_definition(FIXTURE))
    entry = model.entities["JournalEntry"]
    line = model.entities["JournalLine"]
    samples = {f.name: f.sample for f in [*entry.fields, *line.fields]}
    # One to three lines of 1 and 1 keep the balance, and 3 stays within 5.
    assert (samples["debit"], samples["credit"], samples["debit_limit"]) == ('"1"', '"1"', '"5"')


def test_the_fastapi_tests_send_lines_that_keep_and_break_each_rule() -> None:
    files = files_of(load_definition(FIXTURE), fastapi.BINDING)
    create = files["tests/features/journal_entries/test_create_journal_entry_lines.py"]
    assert (
        "async def test_create_journal_entry_keeps_the_rule_balanced(\n"
        "    client: AsyncClient, session: AsyncSession\n"
        ") -> None:\n"
        "    payload = await journal_entry_input(session)\n"
        '    payload["lines"] = [\n'
        '        await lines_item(session, debit="1", credit="0"),\n'
        '        await lines_item(session, debit="1", credit="2"),\n'
        "    ]\n"
    ) in create
    assert (
        '        await lines_item(session, debit="1", credit="1"),\n'
        '        await lines_item(session, debit="1", credit="0"),\n'
        "    ]\n"
    ) in create
    assert (
        '    assert response.json()["detail"] == "The debits and the credits must balance."'
        in create
    )
    assert "test_create_journal_entry_checks_the_rule_within_limit" in create
    update = files["tests/features/journal_entries/test_update_journal_entry_lines.py"]
    assert "async def test_update_journal_entry_checks_the_rule_balanced(" in update
    assert "    assert await _lines_of(session, record.id) == []" in update


def test_a_total_of_a_rule_cannot_have_the_name_of_a_member() -> None:
    text = definition_text().replace(
        "      memo: { type: string, required: true }\n",
        "      memo: { type: string, required: true }\n      sum_lines_debit: { type: integer }\n",
    )
    definition = load_definition_text(text, "app.yaml")
    with pytest.raises(GenerationError, match="needs the attribute 'sum_lines_debit'"):
        python_app(definition)
    with pytest.raises(GenerationError, match="needs the key 'sumLinesDebit'"):
        generate(definition, nextjs.BINDING)


def test_the_nextjs_repository_checks_the_rules_at_the_end_of_the_transaction() -> None:
    files = files_of(load_definition(FIXTURE), nextjs.BINDING)
    entry = files["src/entities/journal-entry/api/journal-entry-repository.ts"]
    assert (
        "  totalRules: [\n"
        "    { // @trace entities.JournalEntry.rules.balanced begin\n"
        '      field: "sumLinesDebit",\n'
        '      op: "eq",\n'
        '      other: "sumLinesCredit",\n'
    ) in entry
    assert '      other: "debitLimit",\n' in entry
    # Only the subquery of the credits is in ruleTotals: the computed field reads the debits.
    rule_totals = entry[entry.index("ruleTotals:") :]
    assert "sumLinesCredit: total(" in rule_totals
    assert "sumLinesDebit" not in rule_totals
    repository = files["src/shared/db/repository.ts"]
    assert repository.count("await this.checkTotals(tx, ") == 2
    assert "await checkAtEnd(tx, async (db) => {" in repository
    client = files["src/shared/db/client.ts"]
    assert "export async function checkAtEnd(" in client
    assert "const result = await checks.run(pending, work);" in client


def test_without_transactions_the_nextjs_repository_checks_the_rules_now() -> None:
    text = definition_text().replace(
        "operations:\n"
        "  create_entry: { kind: create, entity: Entry, lines: [lines] }\n"
        "  update_entry: { kind: update, entity: Entry, lines: [lines] }\n",
        "",
    )
    files = files_of(load_definition_text(text, "app.yaml"), nextjs.BINDING)
    repository = files["src/shared/db/repository.ts"]
    assert "const row = await this.totalsRow(tx, id);" in repository
    assert "checkAtEnd" not in repository
    assert "checkAtEnd" not in files["src/shared/db/client.ts"]
