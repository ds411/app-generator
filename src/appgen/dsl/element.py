"""The base class of the elements of an app definition, and the name types.

The model of the data part (`model.py`) and the model of the UI part
(`ui/`) both use this module.
"""

from collections.abc import Mapping
from types import MappingProxyType
from typing import Annotated, Any, Self, cast

from pydantic import (
    BaseModel,
    ConfigDict,
    ModelWrapValidatorHandler,
    PrivateAttr,
    StringConstraints,
    model_validator,
)

from appgen.dsl.diagnostics import Location

APP_NAME_PATTERN = r"^[a-z][a-z0-9-]*$"
ENTITY_NAME_PATTERN = r"^[A-Z][A-Za-z0-9]*$"
MEMBER_NAME_PATTERN = r"^[a-z][a-z0-9_]*$"
EXTENSION_PREFIX = "x-"

type AppName = Annotated[str, StringConstraints(pattern=APP_NAME_PATTERN)]
"""The name of the app, in kebab case, for example `project-tracker`."""
type EntityName = Annotated[str, StringConstraints(pattern=ENTITY_NAME_PATTERN)]
"""The name of an entity, in Pascal case, for example `Task`."""
type MemberName = Annotated[str, StringConstraints(pattern=MEMBER_NAME_PATTERN)]
"""The name of a field, relation, param, operation, page, or enum value, in snake case."""
type Text = Annotated[str, StringConstraints(min_length=1)]


def is_extension_key(key: str) -> bool:
    """Return true for an extension key: a key that starts with `x-` (ADR 0002)."""
    return key.startswith(EXTENSION_PREFIX)


class Element(BaseModel):
    """The base class of each element of an app definition."""

    model_config = ConfigDict(
        extra="forbid",
        strict=True,
        # Extension keys (ADR 0002). The loader keeps them in `extensions`.
        json_schema_extra={"patternProperties": {"^x-": {}}},
    )

    _location: Location | None = PrivateAttr(default=None)
    _value_locations: dict[str, Location] = PrivateAttr(default_factory=dict[str, Location])
    _id: str = PrivateAttr(default="")
    _extensions: dict[str, Any] = PrivateAttr(default_factory=dict[str, Any])

    @model_validator(mode="wrap")
    @classmethod
    def _keep_extensions(cls, data: Any, handler: ModelWrapValidatorHandler[Self]) -> Self:
        """Take the extension keys (`x-...`) out of the input, and keep them."""
        extensions: dict[str, Any] = {}
        if isinstance(data, dict):
            items = cast(dict[Any, Any], data).items()
            extensions = {k: v for k, v in items if isinstance(k, str) and is_extension_key(k)}
            data = {k: v for k, v in items if k not in extensions}
        element = handler(data)
        element._extensions = extensions
        return element

    @property
    def extensions(self) -> Mapping[str, Any]:
        """The extension keys of the element and their values. The DSL does not check them."""
        return MappingProxyType(self._extensions)

    @property
    def location(self) -> Location | None:
        """The position of the element in its source file, if it comes from a file."""
        return self._location

    def location_of(self, key: str) -> Location | None:
        """The position of the value of a key of the element, or else of the element."""
        return self._value_locations.get(key, self._location)

    @property
    def id(self) -> str:
        """The element ID, for example `entities.Task.fields.title` (ADR 0002).

        The root of the definition has the empty ID.
        """
        return self._id
