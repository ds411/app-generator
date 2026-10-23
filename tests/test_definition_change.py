"""A change to the definition: the hand-written code stays, and the checker finds the drift.

The test generates each app of the project tracker, writes hand-written
code into an extension file, and then changes a copy of the definition:
it adds a field, renames an entity, and removes a page. After a new run,
the extension file keeps its code, and `appgen check` reports the traces
of the hand-written code to the renamed and the removed elements as
invalid, until the app developer updates them.
"""

import re
from pathlib import Path

import pytest

from appgen.dsl import AppDefinition, load_definition_text
from appgen.gen import find_binding, generate, write_result
from appgen.trace import check_traces

EXAMPLE = Path(__file__).parent.parent / "examples" / "project-tracker" / "app.yaml"

# An extension file of each app, and its comment prefix.
EXTENSION_FILES = {
    "nextjs": ("src/widgets/task-detail/ui/activity-tab.ext.tsx", "//"),
    "react": ("src/widgets/task-detail/ui/activity-tab.ext.tsx", "//"),
    "fastapi": ("app/features/tasks/complete_task_ext.py", "#"),
}

NEW_FIELD = "entities.Project.fields.priority"
RENAMED = ("entities.Comment", "entities.Remark")
REMOVED = "pages.people"


def change(text: str) -> str:
    """Add a field to Project, rename the entity Comment to Remark, and remove the page people."""
    project = (
        "    display_field: name\n    fields:\n"
        "      name: { type: string, required: true, max_length: 120 }\n      key:"
    )
    assert text.count(project) == 1
    text = text.replace(
        project,
        project.replace(
            "    fields:\n", "    fields:\n      priority: { type: integer, min: 1, max: 5 }\n"
        ),
    )
    text = re.sub(r"\bComment\b", "Remark", text)
    for block in (
        "  people:\n    path: /people\n    title: People\n    entity: Person\n"
        "    content: { view: person_cards }\n",
        "        team:\n          label: Team\n          collapsible: true\n          items:\n"
        "            people: { page: people, icon: users }\n",
    ):
        assert text.count(block) == 1
        text = text.replace(block, "")
    return text


def hand_written(header: str, prefix: str) -> str:
    """Return the extension file with hand-written code that uses Comment and the page people."""
    lines = header.replace("@trace:gap", "@trace:manual").splitlines()[:2]
    return "\n".join(
        [
            *lines,
            f"{prefix} Hand-written code: the activity of a task, from its comments.",
            f"{prefix} @trace:manual {RENAMED[0]}",
            f"{prefix} @trace:manual {REMOVED}",
            f"{prefix} @trace:manual entities.Task",
            "",
        ]
    )


@pytest.fixture(scope="module")
def changed() -> AppDefinition:
    return load_definition_text(change(EXAMPLE.read_text()), "changed.yaml")


@pytest.mark.parametrize("binding_name", sorted(EXTENSION_FILES))
def test_extension_code_stays_and_the_check_reports_the_drift(
    tmp_path: Path, changed: AppDefinition, binding_name: str
) -> None:
    binding = find_binding(binding_name)
    original = load_definition_text(EXAMPLE.read_text(), str(EXAMPLE))
    write_result(generate(original, binding), tmp_path, binding_name)
    path, prefix = EXTENSION_FILES[binding_name]
    extension = tmp_path / path
    code = hand_written(extension.read_text(), prefix)
    extension.write_text(code)
    assert check_traces(original, tmp_path).invalid == []

    result = generate(changed, binding)
    write_result(result, tmp_path, binding_name)

    # The new run keeps the hand-written code.
    assert extension.read_text() == code
    report = check_traces(changed, tmp_path)
    # The generated code follows the definition: the new field and the
    # renamed entity have traces, and no generated trace is invalid.
    covered = {e.element_id for e in report.coverage.elements if e.status == "covered"}
    assert {NEW_FIELD, RENAMED[1]} <= covered
    assert not [t for t in report.traces if t.element_id == RENAMED[0]]
    # The hand-written code still refers to the old elements.
    # Other extension files of the renamed entity (for example its
    # validation in the FastAPI app) are drift too.
    invalid = {(p.file, p.element_id) for p in report.invalid}
    assert {(path, RENAMED[0]), (path, REMOVED)} <= invalid
    assert {element_id for _, element_id in invalid} == {RENAMED[0], REMOVED}
    # The hint comes from the spelling of the IDs, so it cannot know a rename.
    assert all(p.code == report.invalid[0].code for p in report.invalid)
