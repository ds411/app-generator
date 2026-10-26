"""Files and images in the records: the field types `file` and `image`, and `storage`.

A file field holds one file of a record, for example the screenshot of a
task (ADR 0027). The apps keep the file in the storage of the section
`storage`: a local folder, or an S3-compatible service. The record keeps
the key of the file in the storage, its name, its size, and its media
type. More files for one record are a `one_to_many` relation to an
entity with a file field.

A seed record gives the value of a file field as the path of a local
file, from the folder of the definition. The loader reads each file
(`read_seed_files`), and the validator checks its size and its type.
"""

import hashlib
import re
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

from pydantic_core import PydanticCustomError

from appgen.dsl.apis import EnvName
from appgen.dsl.element import Element

if TYPE_CHECKING:
    from appgen.dsl.model import AppDefinition, Field

type StorageKind = Literal["local", "s3"]

FILE_TYPES = frozenset({"file", "image"})
"""The field types that hold a file."""
DEFAULT_MAX_SIZE = 10 * 1024 * 1024
"""The largest file of a file field without `max_size`: 10 MB."""
MAX_SEED_FILE_SIZE = 1024 * 1024
"""The largest file of a seed record: 1 MB. The apps keep the seed files in their code."""
DEFAULT_IMAGE_TYPES = ("image/png", "image/jpeg", "image/gif", "image/webp")
"""The media types of an `image` field without `types`."""
MEDIA_TYPE_PATTERN = r"^[a-z]+/([a-z0-9][a-z0-9.+-]*|\*)$"
"""A media type, for example `application/pdf`, or all types of a group, for example `image/*`."""
TOP_LEVEL_TYPES = frozenset({"application", "audio", "font", "image", "model", "text", "video"})
"""The top-level media types (IANA) of a file."""
S3_KEYS = ("bucket_env", "region_env", "endpoint_env", "access_key_env", "secret_key_env")
"""The keys of the section `storage` that only the kind `s3` takes."""
SECRET_KEYS = frozenset({"access_key_env", "secret_key_env"})
"""The keys of the variables that hold a secret."""

_SIZE = re.compile(r"^\s*([0-9]+(?:\.[0-9]+)?)\s*(B|KB|MB|GB)\s*$", re.IGNORECASE)
_UNITS = {"B": 1, "KB": 1024, "MB": 1024**2, "GB": 1024**3}
_EXTENSION_TYPES = {
    ".avif": "image/avif",
    ".csv": "text/csv",
    ".gif": "image/gif",
    ".jpeg": "image/jpeg",
    ".jpg": "image/jpeg",
    ".json": "application/json",
    ".md": "text/markdown",
    ".mp3": "audio/mpeg",
    ".mp4": "video/mp4",
    ".pdf": "application/pdf",
    ".png": "image/png",
    ".svg": "image/svg+xml",
    ".txt": "text/plain",
    ".webm": "video/webm",
    ".webp": "image/webp",
    ".zip": "application/zip",
}
"""The media type of a seed file by its extension. A fixed table, so that each machine gives the
same type."""


def size_input(value: object) -> object:
    """Return the number of bytes of a size: an integer, or a text with a unit, for example `5MB`.

    1 KB is 1024 bytes. A value that is not a size stays as it is, so that the model reports it.
    """
    if not isinstance(value, str):
        return value
    match = _SIZE.fullmatch(value)
    if match is None:
        raise PydanticCustomError(
            "size",
            "Expected a size: a number of bytes, or a number with B, KB, MB, or GB, for "
            "example '5MB'",
        )
    number, unit = match.groups()
    return round(float(number) * _UNITS[unit.upper()])


def size_schema(schema: dict[str, Any]) -> None:
    """Add the text form of a size (`5MB`) to the JSON Schema of the key."""
    text = {"type": "string", "pattern": _SIZE.pattern}
    schema["anyOf"] = [*schema.get("anyOf", []), text]


def format_size(size: int) -> str:
    """Return a size as a short text with a unit, for example `5 MB` or `1.5 KB`."""
    for unit in ("GB", "MB", "KB"):
        if size >= _UNITS[unit]:
            text = f"{size / _UNITS[unit]:.1f}".removesuffix(".0")
            return f"{text} {unit}"
    return f"{size} B"


def type_allows(types: Sequence[str], media_type: str) -> bool:
    """Return True if a list of media types allows a type. An empty list allows all types."""
    group = media_type.partition("/")[0]
    return not types or any(t == media_type or t == f"{group}/*" for t in types)


def media_type_of(path: str) -> str | None:
    """Return the media type of a file by its extension, or None for an unknown extension."""
    return _EXTENSION_TYPES.get(Path(path).suffix.lower())


class Storage(Element):
    """The storage of the files of the file fields: a local folder, or an S3-compatible service.

    Each key that ends with `_env` names the environment variable of a
    setting. With the kind `s3`, the apps use the local folder while the
    variable of the bucket has no value, for example on the machine of a
    developer and in the tests.
    """

    kind: StorageKind
    """`local` (a folder on the server) or `s3` (an S3-compatible service)."""
    folder_env: EnvName = "STORAGE_FOLDER"
    """The variable of the local folder."""
    bucket_env: EnvName = "STORAGE_BUCKET"
    """`s3`: the variable of the bucket."""
    region_env: EnvName = "STORAGE_REGION"
    """`s3`: the variable of the region."""
    endpoint_env: EnvName = "STORAGE_ENDPOINT"
    """`s3`: the variable of the URL of an S3-compatible service. Empty: Amazon S3."""
    access_key_env: EnvName = "STORAGE_ACCESS_KEY_ID"
    """`s3`: the variable of the access key ID."""
    secret_key_env: EnvName = "STORAGE_SECRET_ACCESS_KEY"
    """`s3`: the variable of the secret access key."""

    @property
    def variables(self) -> list[tuple[str, str]]:
        """The key and the environment variable of each setting of the kind."""
        keys = ("folder_env", *S3_KEYS) if self.kind == "s3" else ("folder_env",)
        return [(key, getattr(self, key)) for key in keys]


@dataclass(frozen=True, slots=True)
class SeedFile:
    """The file of a file field of a seed record, as the loader reads it."""

    path: str
    """The path in the definition, from the folder of the definition."""
    content: bytes | None
    """The content, or None if the loader cannot read the file."""
    error: str | None = None
    """Why the loader cannot read the file, or None."""

    @property
    def hash(self) -> str:
        """The SHA-256 hash of the content, as the output manifest records it."""
        return "sha256:" + hashlib.sha256(self.content or b"").hexdigest()

    @property
    def media_type(self) -> str | None:
        """The media type by the extension of the file, or None for an unknown extension."""
        return media_type_of(self.path)

    @property
    def name(self) -> str:
        """The name of the file, without the folders."""
        return Path(self.path).name


def read_seed_files(definition: AppDefinition, base_dir: Path) -> None:
    """Read the file of each file field of each seed record, from the folder of the definition.

    The record keeps each file by field name (`SeedRecord.files`). A value
    that is not a text stays out: the validator reports it.
    """
    for entity_name, seed in definition.seed.items():
        entity = definition.entities.get(entity_name)
        if entity is None:
            continue
        for record in seed.records.values():
            files: dict[str, SeedFile] = {}
            for name, value in record.values.items():
                field = entity.fields.get(name)
                if field is not None and field.type in FILE_TYPES and isinstance(value, str):
                    files[name] = _read_file(value, base_dir)
            record._files = files  # pyright: ignore[reportPrivateUsage]


def seed_files(definition: AppDefinition) -> Iterator[SeedFile]:
    """Yield the file of each file field of each seed record, in source order."""
    for seed in definition.seed.values():
        for record in seed.records.values():
            yield from record.files.values()


def file_fields(definition: AppDefinition) -> Iterator[Field]:
    """Yield each file field of each entity, in source order."""
    for entity in definition.entities.values():
        yield from (f for f in entity.fields.values() if f.type in FILE_TYPES)


def _read_file(path: str, base_dir: Path) -> SeedFile:
    if "://" in path:
        return SeedFile(path, None, "The file of a seed record must be a local file, not a URL.")
    try:
        return SeedFile(path, (base_dir / path).read_bytes())
    except FileNotFoundError:
        return SeedFile(path, None, f"The file '{path}' does not exist.")
    except IsADirectoryError:
        return SeedFile(path, None, f"The path '{path}' is a folder, not a file.")
    except OSError as error:
        return SeedFile(path, None, f"Cannot read the file: {error.strerror or error}.")
