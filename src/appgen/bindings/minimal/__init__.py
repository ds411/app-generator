"""A minimal binding for the tests of the generator core.

It writes an index file and one text file for each entity, and covers only the app, the
entities, and the fields. All other elements become gaps.
"""

from pathlib import Path

from appgen.gen.binding import Binding, Output

BINDING = Binding(
    name="minimal",
    description="A minimal binding that writes an index and one text file for each entity.",
    template_dir=Path(__file__).parent / "templates",
    outputs=(
        Output(template="entity.txt.j2", path="entities/{{ name }}.txt", for_each="entity"),
        Output(template="index.txt.j2", path="index.txt"),
    ),
    covers=frozenset({"app", "entity", "field"}),
)
