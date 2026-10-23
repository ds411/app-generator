"""A minimal binding for the tests of the generator core.

It writes an index file, a JSON file (a file type without comments), and
one Markdown file for each entity, with traces. It covers only the app, the
entities, and the fields. All other elements become gaps.
"""

from pathlib import Path

from appgen.gen.binding import Binding, Output

BINDING = Binding(
    name="minimal",
    description="A minimal binding that writes an index and one Markdown file for each entity.",
    template_dir=Path(__file__).parent / "templates",
    outputs=(
        Output(template="entity.md.j2", path="entities/{{ name }}.md", for_each="entity"),
        Output(template="index.md.j2", path="index.md"),
        Output(template="app.json.j2", path="app.json"),
    ),
    covers=frozenset({"app", "entity", "field"}),
)
