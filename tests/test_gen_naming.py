import pytest

from appgen.gen.naming import camel, constant, kebab, pascal, snake, words


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("due_date", ["due", "date"]),
        ("ProjectTask", ["project", "task"]),
        ("project-tracker", ["project", "tracker"]),
        ("HTTPServer", ["http", "server"]),
        ("blue_600", ["blue", "600"]),
        ("Task", ["task"]),
    ],
)
def test_words_split_each_naming_convention(name: str, expected: list[str]) -> None:
    assert words(name) == expected


def test_the_conversions_give_the_conventions_of_the_languages() -> None:
    assert camel("due_date") == "dueDate"
    assert pascal("project_detail") == "ProjectDetail"
    assert kebab("ProjectTask") == "project-task"
    assert snake("ProjectTask") == "project_task"
    assert constant("task_status") == "TASK_STATUS"
    assert camel("") == ""
