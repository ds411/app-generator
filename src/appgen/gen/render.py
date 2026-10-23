"""Deterministic rendering with Jinja2.

The same definition and the same generator version must give the same
output, byte for byte. Thus the environment stops on a missing value,
the output has LF line endings and one final newline, and the context
has no clock or random values.
"""

from collections.abc import Sequence
from pathlib import Path, PurePosixPath

import jinja2

from appgen.gen.naming import NAMING_FILTERS


class GenerationError(Exception):
    """The generator cannot render a template, or the output is not valid."""


def make_environment(template_dir: Path, shared_dirs: Sequence[Path] = ()) -> jinja2.Environment:
    """Return a Jinja2 environment for the templates of a binding.

    The loader looks for a template in `template_dir` first, and then in
    each folder of `shared_dirs`, in order. The environment has the
    naming filters of `appgen.gen.naming`, for example `{{ name | camel }}`.
    """
    environment = jinja2.Environment(
        loader=jinja2.FileSystemLoader([template_dir, *shared_dirs]),
        undefined=jinja2.StrictUndefined,
        autoescape=False,
        trim_blocks=True,
        lstrip_blocks=True,
        keep_trailing_newline=True,
        newline_sequence="\n",
    )
    environment.filters.update(NAMING_FILTERS)
    return environment


def normalize_content(content: str) -> str:
    """Return the content with LF line endings and exactly one final newline."""
    content = content.replace("\r\n", "\n").replace("\r", "\n")
    return content.rstrip("\n") + "\n"


def normalize_path(path: str) -> str:
    """Return a rendered output path in POSIX form. Reject a path out of the output folder."""
    clean = PurePosixPath(path.strip().replace("\\", "/"))
    if not path.strip() or clean.is_absolute() or ".." in clean.parts:
        raise GenerationError(f"The output path {path!r} is not a relative path in the output.")
    return clean.as_posix()
