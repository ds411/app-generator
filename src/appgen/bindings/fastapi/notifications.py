"""The notifications of the FastAPI app: the notices of the users (ADR 0041).

`app/core/notifications.py` has the table `notices`, the text of each
notification, and the endpoints of the notices of the signed-in user.
The repository of each entity with a notification adds the notices of a
change in the transaction of the change, after the events and the
change log. A `text` field with mentions (ADR 0043) gives a notice to
each user that a new or a changed text mentions for the first time.
"""

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from appgen.bindings.fastapi.pysource import LINE_LENGTH, call, literal, string
from appgen.bindings.shared.i18n import I18nPlan
from appgen.bindings.shared.notices import MENTION, MENTION_TEXT
from appgen.dsl.model import AppDefinition
from appgen.gen.naming import constant
from appgen.gen.render import GenerationError

if TYPE_CHECKING:
    from appgen.bindings.fastapi.model import PyEntity, PyWorkflow

TABLE = "notices"
"""The table of the notices."""


@dataclass(slots=True)
class PyNoticeValue:
    """A value in braces of the text of a notification: a field, or a `many_to_one` relation."""

    name: str
    attr: str
    """The attribute of the field, or the foreign key attribute of the relation."""
    target: str | None = None
    """The model of the record of a relation, or None for a field."""
    label: str | None = None
    """The attribute of the display field of the record of a relation, or None (its ID)."""

    def args(self) -> tuple[str, list[str]]:
        """Return the function and the arguments that give the value as text."""
        if self.target is not None and self.label is not None:
            return "record_text", [
                "session",
                f"{self.target}.{self.label}",
                f"{self.target}.id",
                f"record.{self.attr}",
            ]
        return "text_value", [f"record.{self.attr}"]


@dataclass(slots=True)
class PyReceiver:
    """A receiver path of a notification: relations to the user entity."""

    path: str
    """The path in the definition, for example `project.members`."""
    attrs: list[str]
    """The attributes of the relations of the path."""
    ids: list[str]
    """The element IDs of the relations of the path."""
    direct: str | None = None
    """The foreign key attribute of a path with one many-to-one step, else None."""
    required: bool = False
    """True for a direct path of a required relation: each record has a receiver."""
    setup: list[str] = field(default_factory=list[str])
    """The statements of the tests that store the records of the path to a user (`user_id`),
    and return the values of a new record of the entity with the user at the end of the path."""
    key: str = ""
    """The key of the input of the first relation of the path, for the tests."""

    @property
    def function(self) -> str:
        """The function of the tests that makes a user a receiver through the path."""
        return self.path.replace(".", "_") + "_receiver"

    def code(self, model: str) -> str:
        """Return the item of the list of the users: the foreign key, or the users of a query."""
        if self.direct is not None:
            return f"record.{self.direct}"
        path = ", ".join(string(a) for a in self.attrs)
        path = f"({path},)" if len(self.attrs) == 1 else f"({path})"
        return f"*await path_users(session, {model}, record.id, {path})"


@dataclass(slots=True)
class PyNotification:
    """A notification of an entity (ADR 0041): the change, the receivers, and the text."""

    name: str
    id: str
    entity: str
    """The model of the entity."""
    kind: str
    """`created`, `changed`, or `transition`."""
    text: str
    receivers: list[PyReceiver]
    values: list[PyNoticeValue]
    attrs: list[str] = field(default_factory=list[str])
    """`changed`: the attributes of the fields and the foreign keys of the relations."""
    fields: list[str] | None = None
    """`changed`: the names of `fields`, or None for all."""
    workflow: PyWorkflow | None = None
    """`transition`: the workflow of the transition."""
    before: list[str] = field(default_factory=list[str])
    """`transition`: the states before the transition."""
    after: str = ""
    """`transition`: the state after the transition."""
    transition: str = ""
    """`transition`: the name of the transition."""
    user_entity: str = ""
    """The user entity of `auth`: the receivers are its records."""

    @property
    def has_receiver(self) -> bool:
        """True if each record has a receiver: a direct path of a required relation."""
        return any(r.required for r in self.receivers)

    @property
    def direct_receiver(self) -> PyReceiver | None:
        """The first receiver path with one many-to-one step, or None."""
        return next((r for r in self.receivers if r.direct is not None), None)

    def receivers_call(self, indent: int) -> str:
        """Return the statement of the tests that finds the users of the receiver paths."""
        paths: list[str] = []
        for receiver in self.receivers:
            attrs = [string(a) for a in receiver.attrs]
            paths.append(f"({attrs[0]},)" if len(attrs) == 1 else f"({', '.join(attrs)})")
        return call("users = await ", "receivers", ["session", "record", *paths], indent)

    def sample_values(self) -> dict[str, str]:
        """Return values of the text for the tests: a text for each name in braces."""
        return {v.name: f"<{v.name}>" for v in self.values}

    def sample_text(self, text: str | None = None) -> str:
        """Return the text, or a translation of it, with the values of `sample_values`."""
        text = self.text if text is None else text
        for name, value in self.sample_values().items():
            text = text.replace("{" + name + "}", value)
        return text

    def sample_translation(self, i18n: I18nPlan | None) -> tuple[str, str] | None:
        """Return the first other language that translates the text, and the translation.

        The translation has the values of `sample_values`. None: no language
        translates the text.
        """
        if i18n is None:
            return None
        for language in i18n.others:
            if self.text in language.text:
                return language.code, self.sample_text(language.text[self.text])
        return None

    @property
    def constant(self) -> str:
        """The constant of the attributes that a notification `changed` watches."""
        return f"{constant(self.name)}_FIELDS"

    def constant_code(self) -> str:
        """Return the constant of the attributes that the notification watches."""
        return literal(self.attrs, f"{self.constant} = ")

    def condition(self) -> str:
        """Return the condition of a change of a record (`before`) that gives the notices."""
        if self.kind == "changed":
            return f"changed(record, before, {self.constant})"
        assert self.workflow is not None
        attr = self.workflow.attr
        if len(self.before) == 1:
            before = f'before["{attr}"] == {string(self.before[0])}'
        else:
            states = ", ".join(string(s) for s in self.before)
            before = f'before["{attr}"] in ({states})'
        return f"record.{attr} == {string(self.after)} and {before}"

    def body(self, indent: int) -> str:
        """Return the statements that add the notices. The first line has no indent."""
        users = [r.code(self.entity) for r in self.receivers]
        lines = [_items("users = ", "[", "]", users, indent)]
        if self.values:
            lines.append(_values(self.values, indent))
            values = "values"
        else:
            values = "{}"
        args = ["session", string(self.name), string(self.entity), "record.id", "users", values]
        lines.append(call("", "add_notices", args, indent))
        return ("\n" + " " * indent).join(lines)

    def summary(self) -> str:
        """Return the change that gives the notices, for the README."""
        if self.kind == "created":
            return f"A new {self.entity}"
        if self.kind == "changed":
            fields = ", ".join(f"`{name}`" for name in self.fields or [])
            return (
                f"A change of {fields} of a {self.entity}"
                if fields
                else f"A change of a {self.entity}"
            )
        assert self.workflow is not None
        return f"The transition `{self.transition}` of the workflow `{self.workflow.name}`"


def _items(prefix: str, start: str, end: str, items: list[str], indent: int) -> str:
    """Return `<prefix><start><items><end>` on one line if it fits, else one item on each line."""
    one_line = f"{prefix}{start}{', '.join(items)}{end}"
    if indent + len(one_line) <= LINE_LENGTH:
        return one_line
    pad = " " * indent
    inner = "".join(f"{pad}    {item},\n" for item in items)
    return f"{prefix}{start}\n{inner}{pad}{end}"


def _values(values: list[PyNoticeValue], indent: int) -> str:
    """Return the statement of the values of the text: the dict `values`."""
    flat: list[str] = []
    for value in values:
        func, args = value.args()
        prefix = "await " if func == "record_text" else ""
        flat.append(f"{string(value.name)}: {prefix}{func}({', '.join(args)})")
    one_line = _items("values = ", "{", "}", flat, indent)
    if "\n" not in one_line:
        return one_line
    pad = " " * indent
    lines = ["values = {"]
    for value in values:
        func, args = value.args()
        prefix = f"{string(value.name)}: " + ("await " if func == "record_text" else "")
        lines.append(pad + "    " + call(prefix, func, args, indent + 4, ","))
    lines.append(pad + "}")
    return "\n".join(lines)


@dataclass(slots=True)
class PyMention:
    """A `text` field with mentions (ADR 0043): a new mention of a user gives a notice."""

    name: str
    """The name of the field."""
    id: str
    entity: str
    """The model of the entity."""
    attr: str
    """The attribute of the field."""
    label: str | None
    """The attribute of the display field of the entity, or None: the text has the ID."""
    user_entity: str
    """The model of the user entity of `auth`."""
    max_length: int | None = None
    """The most characters of the text, or None."""

    @property
    def two_mentions(self) -> bool:
        """True if the text can hold two mentions, for the tests: 90 characters."""
        return self.max_length is None or self.max_length >= 90

    def call(self, indent: int) -> str:
        """Return the statement of `mention` in the repository that adds the notices."""
        label = f"text_value(record.{self.label})" if self.label else "str(record.id)"
        args = [
            "session",
            f"{self.user_entity}.id",
            string(self.entity),
            "record.id",
            label,
            f"record.{self.attr}",
            f'None if before is None else before["{self.attr}"]',
        ]
        return call("await ", "add_mentions", args, indent)

    def sample(self) -> PyNotification:
        """Return the notices of the mentions as a notification, for the tests of the notices."""
        return PyNotification(
            name=MENTION,
            id=self.id,
            entity=self.entity,
            kind="mention",
            text=MENTION_TEXT,
            receivers=[],
            values=[PyNoticeValue(name="record", attr=self.label or "id")],
            user_entity=self.user_entity,
        )


def python_notifications(definition: AppDefinition, entities: dict[str, PyEntity]) -> None:
    """Give the entities their notifications (ADR 0041) and their fields with mentions
    (ADR 0043).

    Raise GenerationError if an entity has the table of the notices.
    """
    auth = definition.auth
    mentions = auth is not None and any(
        f.mentions for e in definition.entities.values() for f in e.fields.values()
    )
    if not definition.notifications and not mentions:
        return
    for entity in entities.values():
        if entity.table == TABLE:
            raise GenerationError(
                f"The entity '{entity.name}' has the table '{TABLE}' of the notices. Give it "
                "another table with x-fastapi-table."
            )
    if auth is not None:
        users = entities[auth.user_entity].name
        for entity_name, entity in definition.entities.items():
            py_entity = entities[entity_name]
            label = _label_attr(definition, py_entity)
            for f in py_entity.fields:
                dsl = entity.fields[f.name]
                if dsl.mentions:
                    py_entity.mentions.append(
                        PyMention(
                            f.name, dsl.id, py_entity.name, f.attr, label, users, dsl.max_length
                        )
                    )
    for name, notification in definition.notifications.items():
        py_entity = entities[notification.entity]
        fields = {f.name: f for f in py_entity.fields}
        relations = {r.name: r for r in py_entity.relations}
        result = PyNotification(
            name=name,
            id=notification.id,
            entity=py_entity.name,
            kind=notification.event or "transition",
            text=notification.text,
            receivers=[_receiver(entities, py_entity, path) for path in notification.receivers],
            values=[],
            user_entity=definition.auth.user_entity if definition.auth else "",
        )
        for value in notification.values():
            f = fields.get(value)
            if f is not None:
                result.values.append(PyNoticeValue(name=value, attr=f.attr))
                continue
            relation = relations[value]
            assert relation.fk_attr is not None
            target = entities[relation.target]
            result.values.append(
                PyNoticeValue(
                    name=value,
                    attr=relation.fk_attr,
                    target=target.name,
                    label=_label_attr(definition, target),
                )
            )
        if notification.event == "changed":
            result.fields = notification.fields
            watched = notification.fields or [
                *(f.name for f in py_entity.fields),
                *(r.name for r in py_entity.relations if r.kind == "many_to_one"),
            ]
            for member in watched:
                f = fields.get(member)
                attr = f.attr if f is not None else relations[member].fk_attr
                assert attr is not None
                result.attrs.append(attr)
        parts = notification.transition_parts()
        if parts is not None:
            workflow_name, transition_name = parts
            workflow = next(
                w
                for n, w in definition.workflows.items()
                if w.entity == notification.entity
                and transition_name in w.transitions
                and workflow_name in (None, n)
            )
            transition = workflow.transitions[transition_name]
            result.workflow = next(w for w in py_entity.workflows if w.id == workflow.id)
            result.before = list(transition.from_)
            result.after = transition.to
            result.transition = transition_name
        py_entity.notifications.append(result)


def _receiver(entities: dict[str, PyEntity], entity: PyEntity, path: str) -> PyReceiver:
    """Return a receiver path (the validator checks that each step exists)."""
    current = entity
    attrs: list[str] = []
    ids: list[str] = []
    direct: str | None = None
    required = False
    steps = path.split(".")
    for step in steps:
        relation = next(r for r in current.relations if r.name == step)
        attrs.append(relation.attr)
        ids.append(relation.id)
        if len(steps) == 1 and relation.side == "fk":
            direct = relation.fk_attr
            required = relation.required
        current = entities[relation.target]
    return PyReceiver(path=path, attrs=attrs, ids=ids, direct=direct, required=required)


def _label_attr(definition: AppDefinition, entity: PyEntity) -> str | None:
    """Return the attribute of the display field of an entity, or None if it has no column."""
    name = definition.entities[entity.name].display_field
    f = next((f for f in entity.fields if f.name == name), None)
    return f.attr if f is not None else None
