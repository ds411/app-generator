"""Read YAML into plain Python data, and keep the source position of each node."""

from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import cast

import yaml
from yaml.constructor import SafeConstructor
from yaml.nodes import MappingNode, Node, ScalarNode, SequenceNode

from appgen.dsl.diagnostics import DefinitionError, Diagnostic, Location

type DataPath = tuple[str | int, ...]
"""The keys and list positions from the root of a document to a node."""


@dataclass(slots=True)
class SourceMap:
    """The positions of the nodes of one YAML document."""

    file: str
    root: Location
    keys: dict[DataPath, Location] = field(default_factory=dict[DataPath, Location])
    values: dict[DataPath, Location] = field(default_factory=dict[DataPath, Location])

    def element(self, path: DataPath) -> Location:
        """Return the location of an element: its key, or the nearest parent."""
        for prefix in _prefixes(path):
            if prefix in self.keys:
                return self.keys[prefix]
            if prefix in self.values:
                return self.values[prefix]
        return self.root

    def value(self, path: DataPath) -> Location:
        """Return the location of a value, or of the nearest node that exists."""
        for prefix in _prefixes(path):
            if prefix in self.values:
                return self.values[prefix]
            if prefix in self.keys:
                return self.keys[prefix]
        return self.root


@dataclass(slots=True)
class YamlDocument:
    """The plain data of a YAML document and its source map."""

    data: object
    source_map: SourceMap


class YamlError(DefinitionError):
    """The YAML text cannot be read. The diagnostics give the reasons."""


def read_yaml_file(path: Path) -> YamlDocument:
    """Read a YAML file. Raise YamlError if the file is not valid YAML."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as error:
        diagnostic = Diagnostic(
            code="file-error",
            message=f"Cannot read the file: {error.strerror or error}.",
            location=Location(str(path), 1, 1),
        )
        raise YamlError([diagnostic]) from error
    return read_yaml(text, str(path))


def read_yaml(text: str, file: str = "<string>") -> YamlDocument:
    """Read YAML text. Raise YamlError if the text is not valid YAML."""
    try:
        node = cast(Node | None, yaml.compose(text, Loader=yaml.SafeLoader))  # pyright: ignore[reportUnknownMemberType]
    except yaml.MarkedYAMLError as error:
        mark = error.problem_mark or error.context_mark
        location = _location(file, mark) if mark else Location(file, 1, 1)
        problem = error.problem or error.context or "invalid YAML"
        diagnostic = Diagnostic(
            code="yaml-syntax",
            message=f"YAML syntax error: {problem}.",
            location=location,
        )
        raise YamlError([diagnostic]) from error
    except yaml.YAMLError as error:
        diagnostic = Diagnostic(
            code="yaml-syntax",
            message=f"YAML syntax error: {error}.",
            location=Location(file, 1, 1),
        )
        raise YamlError([diagnostic]) from error

    source_map = SourceMap(file=file, root=Location(file, 1, 1))
    if node is None:
        return YamlDocument(data=None, source_map=source_map)
    builder = _Builder(source_map)
    data = builder.build(node, ())
    if builder.diagnostics:
        raise YamlError(builder.diagnostics)
    return YamlDocument(data=data, source_map=source_map)


class _Builder:
    def __init__(self, source_map: SourceMap) -> None:
        self.source_map = source_map
        self.constructor = SafeConstructor()
        self.diagnostics: list[Diagnostic] = []

    def build(self, node: Node, path: DataPath) -> object:
        self.source_map.values[path] = _location(self.source_map.file, node.start_mark)
        if isinstance(node, MappingNode):
            return self._mapping(node, path)
        if isinstance(node, SequenceNode):
            return [self.build(item, (*path, index)) for index, item in enumerate(node.value)]
        return self.constructor.construct_object(node, deep=True)  # pyright: ignore[reportUnknownMemberType]

    def _mapping(self, node: MappingNode, path: DataPath) -> dict[str, object]:
        result: dict[str, object] = {}
        for key_node, value_node in node.value:
            key_location = _location(self.source_map.file, key_node.start_mark)
            if not isinstance(key_node, ScalarNode):
                self.diagnostics.append(
                    Diagnostic(
                        code="invalid-key",
                        message="A mapping key must be a plain value, not a list or a mapping.",
                        location=key_location,
                    )
                )
                continue
            # Use the text of the key, so that keys such as "on" or "1"
            # stay names and do not become booleans or numbers.
            key = str(key_node.value)
            key_path = (*path, key)
            if key in result:
                first = self.source_map.keys[key_path]
                self.diagnostics.append(
                    Diagnostic(
                        code="duplicate-key",
                        message=f"The key '{key}' occurs more than one time in this mapping.",
                        location=key_location,
                        hint=f"The first occurrence is at {first}.",
                    )
                )
                continue
            self.source_map.keys[key_path] = key_location
            result[key] = self.build(value_node, key_path)
        return result


def _location(file: str, mark: yaml.Mark) -> Location:
    return Location(file, mark.line + 1, mark.column + 1)


def _prefixes(path: DataPath) -> Iterator[DataPath]:
    for end in range(len(path), -1, -1):
        yield path[:end]
