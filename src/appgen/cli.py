"""The `appgen` command line interface."""

import json
from enum import StrEnum
from pathlib import Path
from typing import Annotated

import typer

from appgen import __version__
from appgen.dsl import Diagnostic, check_file
from appgen.dsl.schema import json_schema_text
from appgen.gen import (
    GenerationError,
    GenerationResult,
    ManifestError,
    ManualEditsError,
    UnknownBindingError,
    WriteReport,
    available_bindings,
    find_binding,
    read_manifest,
    write_result,
)
from appgen.gen import generate as generate_files
from appgen.gen.extensions import check_extensions
from appgen.skills import skill_names
from appgen.skills.install import (
    Plan,
    Scope,
    SkillsError,
    Target,
    apply,
    check_writable,
    plan_install,
    plan_uninstall,
    skills_folder,
    status,
)
from appgen.trace import (
    DEFAULT_IGNORE,
    check_traces,
    find_orphans,
    render,
    render_orphans,
    scan_text,
)


class OutputFormat(StrEnum):
    TEXT = "text"
    JSON = "json"


app = typer.Typer(
    name="appgen",
    help="Generate application code from a declarative YAML app definition.",
    no_args_is_help=True,
    add_completion=False,
)


skills_app = typer.Typer(
    name="skills",
    help="Install the agent skills of appgen for Claude Code and other agents.",
    no_args_is_help=True,
)
app.add_typer(skills_app)


def _print_version(value: bool) -> None:
    if value:
        typer.echo(f"appgen {__version__}")
        raise typer.Exit


@app.callback()
def main(
    version: Annotated[
        bool,
        typer.Option(
            "--version",
            callback=_print_version,
            is_eager=True,
            help="Show the version and exit.",
        ),
    ] = False,
) -> None:
    """Generate application code from a declarative YAML app definition."""


@app.command()
def schema(
    out: Annotated[
        Path | None,
        typer.Option("--out", "-o", help="Write the schema to this file, not to stdout."),
    ] = None,
) -> None:
    """Write the JSON Schema of the app definition DSL."""
    text = json_schema_text()
    if out is None:
        typer.echo(text, nl=False)
    else:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text, encoding="utf-8", newline="\n")


@app.command()
def validate(
    file: Annotated[Path, typer.Argument(help="The app definition file (YAML).")],
    output_format: Annotated[
        OutputFormat,
        typer.Option("--format", "-f", help="The output format."),
    ] = OutputFormat.TEXT,
    binding_names: Annotated[
        list[str] | None,
        typer.Option(
            "--binding",
            "-b",
            help="A binding whose extension keys to check. Repeat it for more. "
            "Default: all bindings.",
        ),
    ] = None,
) -> None:
    """Validate an app definition. The exit code is 0 if it is valid, else 1."""
    definition, diagnostics = check_file(file)
    if definition is not None:
        try:
            bindings = [find_binding(n) for n in binding_names or available_bindings()]
        except UnknownBindingError as error:
            typer.echo(f"error: {error}", err=True)
            raise typer.Exit(code=1) from None
        diagnostics = sorted(
            [*diagnostics, *check_extensions(definition, bindings)], key=lambda d: d.location
        )
    if output_format is OutputFormat.JSON:
        report = {
            "file": str(file),
            "valid": not diagnostics,
            "diagnostics": [_diagnostic_json(d) for d in diagnostics],
        }
        typer.echo(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        for diagnostic in diagnostics:
            typer.echo(str(diagnostic))
        count = len(diagnostics)
        if count:
            typer.echo(f"{file}: {count} error{'s' if count > 1 else ''}.")
        else:
            typer.echo(f"{file}: valid.")
    if diagnostics:
        raise typer.Exit(code=1)


@app.command()
def check(
    definition_file: Annotated[Path, typer.Argument(help="The app definition file (YAML).")],
    code_folder: Annotated[
        Path,
        typer.Argument(help="The folder of the app code.", file_okay=False, exists=True),
    ],
    output_format: Annotated[
        OutputFormat,
        typer.Option("--format", "-f", help="The output format."),
    ] = OutputFormat.TEXT,
    min_coverage: Annotated[
        float | None,
        typer.Option(
            "--min-coverage",
            min=0,
            max=100,
            help="Fail if the coverage in percent is lower than this value.",
        ),
    ] = None,
    exclude_kinds: Annotated[
        list[str] | None,
        typer.Option(
            "--exclude-kind",
            help="Do not count the elements of this kind, and the elements under them, "
            "in the coverage, for example 'ui'. Repeat the option for more kinds.",
        ),
    ] = None,
    ignore: Annotated[
        list[str] | None,
        typer.Option(
            "--ignore",
            help="Also skip the paths that match this pattern (gitignore syntax). "
            "Repeat the option for more patterns.",
        ),
    ] = None,
    use_gitignore: Annotated[
        bool,
        typer.Option("--gitignore/--no-gitignore", help="Skip the paths in .gitignore files."),
    ] = True,
) -> None:
    """Check the traces in a code folder against an app definition.

    The report lists the invalid traces, the uncovered elements, and the
    open gaps, and gives the coverage. The exit code is 0 if the check
    passes, 1 if there is an invalid trace or the coverage is too low,
    and 2 if the definition or the output manifest is not valid.

    If the folder has an output manifest (`.appgen/manifest.json`), the
    check reads the generated files and their traces from it.
    """
    definition, diagnostics = check_file(definition_file)
    if definition is None or diagnostics:
        for diagnostic in diagnostics:
            typer.echo(str(diagnostic), err=True)
        typer.echo(f"{definition_file}: the app definition is not valid.", err=True)
        raise typer.Exit(code=2)
    try:
        report = check_traces(
            definition,
            code_folder,
            ignore=[*DEFAULT_IGNORE, *(ignore or [])],
            use_gitignore=use_gitignore,
            exclude_kinds=exclude_kinds or [],
            min_coverage=min_coverage,
        )
    except ManifestError as error:
        typer.echo(f"{code_folder}: {error}", err=True)
        raise typer.Exit(code=2) from None
    typer.echo(render(report, "json" if output_format is OutputFormat.JSON else "text"), nl=False)
    raise typer.Exit(code=report.exit_code)


@app.command()
def orphans(
    definition_file: Annotated[Path, typer.Argument(help="The app definition file (YAML).")],
    code_folder: Annotated[
        Path,
        typer.Argument(help="The folder of the app code.", file_okay=False, exists=True),
    ],
    output_format: Annotated[
        OutputFormat,
        typer.Option("--format", "-f", help="The output format."),
    ] = OutputFormat.TEXT,
) -> None:
    """List the extension files whose element does not exist any more.

    After a rename or a removal in the definition, `appgen generate`
    keeps the extension files of the old element. The command lists
    them, with the element that most likely replaces the old element, so
    that you can move or delete the hand-written code. It changes no
    file. The exit code is 0, or 2 if the definition or the output
    manifest is not valid, or if the folder has no output manifest.
    """
    definition, diagnostics = check_file(definition_file)
    if definition is None or diagnostics:
        for diagnostic in diagnostics:
            typer.echo(str(diagnostic), err=True)
        typer.echo(f"{definition_file}: the app definition is not valid.", err=True)
        raise typer.Exit(code=2)
    try:
        manifest = read_manifest(code_folder)
    except ManifestError as error:
        typer.echo(f"{code_folder}: {error}", err=True)
        raise typer.Exit(code=2) from None
    if manifest is None:
        typer.echo(f"{code_folder}: the folder has no output manifest of appgen.", err=True)
        raise typer.Exit(code=2)
    found = find_orphans(definition, code_folder, manifest)
    typer.echo(render_orphans(found, output_format.value), nl=False)


@app.command()
def generate(
    file: Annotated[Path, typer.Argument(help="The app definition file (YAML).")],
    binding_name: Annotated[
        str, typer.Option("--binding", "-b", help="The name of the binding, for example nextjs.")
    ],
    out: Annotated[Path, typer.Option("--out", "-o", help="The output folder of the app.")],
    force: Annotated[
        bool,
        typer.Option("--force", help="Overwrite generated files that have manual edits."),
    ] = False,
) -> None:
    """Validate an app definition, then generate the app for a binding.

    The exit code is 0 if the app is generated, else 1. If the definition
    is not valid, the command writes no file.
    """
    definition, diagnostics = check_file(file)
    if definition is None or diagnostics:
        for diagnostic in diagnostics:
            typer.echo(str(diagnostic), err=True)
        typer.echo(f"{file}: the definition is not valid, so no file is written.", err=True)
        raise typer.Exit(code=1)
    try:
        binding = find_binding(binding_name)
    except UnknownBindingError as error:
        typer.echo(f"error: {error}", err=True)
        raise typer.Exit(code=1) from None
    diagnostics = check_extensions(definition, [binding])
    if diagnostics:
        for diagnostic in diagnostics:
            typer.echo(str(diagnostic), err=True)
        typer.echo(f"{file}: the definition is not valid, so no file is written.", err=True)
        raise typer.Exit(code=1)
    try:
        result = generate_files(definition, binding)
        report = write_result(result, out, binding.name, force=force)
    except (UnknownBindingError, GenerationError, ManifestError, ManualEditsError) as error:
        typer.echo(f"error: {error}", err=True)
        raise typer.Exit(code=1) from None
    gap_files = _gap_files(result)
    unfilled = [gap.element_id for gap in result.gaps if not gap.path]
    typer.echo(f"Generated '{definition.app.name}' with the binding '{binding.name}' in {out}.")
    _echo_summary(report, gap_files, unfilled)
    if result.warnings:
        typer.echo(f"Warnings: {len(result.warnings)}")
        for warning in result.warnings:
            typer.echo(f"  {warning}")


def _gap_files(result: GenerationResult) -> dict[str, list[str]]:
    """Return the gap elements of each extension file that has gaps, by path.

    The gaps of a file are the elements of its gap rule, and the elements
    of the gap traces in its content: a stub of a custom element is an
    extension file with a gap trace (ADR 0005).
    """
    gaps: dict[str, list[str]] = {}
    for gap in result.gaps:
        if gap.path:
            gaps.setdefault(gap.path, []).append(gap.element_id)
    for file in result.files:
        if file.kind != "extension":
            continue
        traces, _ = scan_text(file.content, file.path)
        for trace in traces:
            if trace.kind == "gap" and trace.element_id not in gaps.get(file.path, []):
                gaps.setdefault(file.path, []).append(trace.element_id)
    return gaps


def _gaps_in(paths: list[str], gap_files: dict[str, list[str]]) -> dict[str, list[str]]:
    """Return the files of each gap element of a list of extension files."""
    gaps: dict[str, list[str]] = {}
    for path in paths:
        for element_id in gap_files.get(path, []):
            gaps.setdefault(element_id, []).append(path)
    return gaps


def _echo_summary(
    report: WriteReport, gap_files: dict[str, list[str]], unfilled: list[str]
) -> None:
    def section(title: str, paths: list[str]) -> None:
        typer.echo(f"{title}: {len(paths)}")
        for path in paths:
            typer.echo(f"  {path}")

    section("Files written", report.written)
    typer.echo(f"Files unchanged: {len(report.unchanged)}")
    section("Files deleted", report.deleted)
    created = _gaps_in(report.created_extensions, gap_files)
    typer.echo(f"Gaps created: {len(created)}")
    for element_id, paths in created.items():
        typer.echo(f"  {element_id} -> {', '.join(paths)}")
    kept = [e for e in _gaps_in(report.kept_extensions, gap_files) if e not in created]
    if kept:
        typer.echo(f"Gaps kept (extension files exist): {len(kept)}")
    other = [p for p in report.created_extensions if p not in gap_files]
    if other:
        section("Extension files created", other)
    if unfilled:
        section("Gaps without a gap file", unfilled)
    if report.orphaned_extensions:
        section("Orphaned extension files (their element is gone)", report.orphaned_extensions)


def _diagnostic_json(diagnostic: Diagnostic) -> dict[str, object]:
    return {
        "code": diagnostic.code,
        "message": diagnostic.message,
        "file": diagnostic.location.file,
        "line": diagnostic.location.line,
        "column": diagnostic.location.column,
        "element_id": diagnostic.element_id,
        "hint": diagnostic.hint,
    }


TargetsOption = Annotated[
    list[Target] | None,
    typer.Option(
        "--target",
        "-t",
        help="The agents: 'claude' (Claude Code, .claude/skills) or 'agents' (Codex and "
        "other agents, .agents/skills). Repeat it for more. Default: both.",
    ),
]
ScopeOption = Annotated[
    Scope | None,
    typer.Option(
        "--scope",
        "-s",
        help="'project' (the project folder), 'user' (the home folder), or 'system' "
        "(a system folder, needs root). Default: project.",
    ),
]
PathOption = Annotated[
    Path | None,
    typer.Option(
        "--path",
        help="Use this skills folder, not the folders of --target and --scope.",
        file_okay=False,
    ),
]
ProjectDirOption = Annotated[
    Path | None,
    typer.Option(
        "--project-dir",
        help="The project folder of the project scope. Default: the current folder.",
        file_okay=False,
    ),
]
ForceOption = Annotated[
    bool, typer.Option("--force", help="Also overwrite or remove the files that a person changed.")
]
DryRunOption = Annotated[
    bool, typer.Option("--dry-run", help="Show the changes, and write no file.")
]


@skills_app.command("install")
def skills_install(
    targets: TargetsOption = None,
    scope: ScopeOption = None,
    path: PathOption = None,
    project_dir: ProjectDirOption = None,
    force: ForceOption = False,
    dry_run: DryRunOption = False,
) -> None:
    """Install the skills into the skills folders of agents.

    Without options, the command writes the skills to ./.agents/skills/
    and ./.claude/skills/. Each installed skill gets a record file with
    the appgen version and the hash of each file. A second install of
    the same version changes no file, and an install of another version
    updates the files. The command does not overwrite a file that a
    person changed, unless --force. The exit code is 0, or 1 if a file
    has changes or a folder cannot be written.
    """
    folders = _skills_folders(targets, scope, path, project_dir)
    plans = [plan_install(skill, f, force=force) for f in folders for skill in skill_names()]
    _stop_at_changed_files(plans, "overwrite")
    _apply_plans(plans, dry_run, scope)
    for plan in plans:
        if not plan.changes:
            typer.echo(f"{plan.folder}: the skill '{plan.skill}' is up to date ({__version__}).")
            continue
        if dry_run:
            typer.echo(f"The install would change {plan.folder}:")
        else:
            typer.echo(f"Installed the skill of appgen {__version__} into {plan.folder}:")
        _echo_files(plan, dry_run)


@skills_app.command("list")
def skills_list(
    project_dir: ProjectDirOption = None,
    path: PathOption = None,
    output_format: Annotated[
        OutputFormat,
        typer.Option("--format", "-f", help="The output format."),
    ] = OutputFormat.TEXT,
) -> None:
    """List the skills folders of each target and scope, with the installed skills.

    The status of a skill is 'not installed', 'up to date', 'out of
    date' (another version of appgen installed it), or 'changed' (a
    person changed a file). With --path, the list also has that folder.
    The exit code is 0.
    """
    project = project_dir or Path.cwd()
    places: list[tuple[str, str, Path | None]] = []
    for target in Target:
        for scope in Scope:
            try:
                folder = skills_folder(target, scope, project_dir=project)
            except SkillsError:
                folder = None
            places.append((target.value, scope.value, folder))
    if path is not None:
        places.append(("", "path", path))
    rows: list[dict[str, object]] = []
    for target, scope, folder in places:
        for skill in skill_names():
            installed, problems = status(skill, folder) if folder else (None, [])
            if folder is None:
                state = "no folder on this platform"
            elif installed is None:
                state = "not installed"
            else:
                state = ", ".join(problems) or "up to date"
            rows.append(
                {
                    "skill": skill,
                    "target": target or None,
                    "scope": scope,
                    "folder": str(folder / skill) if folder else None,
                    "installed": installed,
                    "status": state,
                }
            )
    if output_format is OutputFormat.JSON:
        report = {"version": 1, "appgen": __version__, "skills": rows}
        typer.echo(json.dumps(report, indent=2, ensure_ascii=False))
        return
    columns = ["skill", "target", "scope", "installed", "status", "folder"]
    table = [columns, *([str(row[c] or "-") for c in columns] for row in rows)]
    widths = [max(len(row[i]) for row in table) for i in range(len(table[0]))]
    for row in table:
        typer.echo(
            "  ".join(cell.ljust(width) for cell, width in zip(row, widths, strict=True)).rstrip()
        )


@skills_app.command("uninstall")
def skills_uninstall(
    targets: TargetsOption = None,
    scope: ScopeOption = None,
    path: PathOption = None,
    project_dir: ProjectDirOption = None,
    force: ForceOption = False,
    dry_run: DryRunOption = False,
) -> None:
    """Remove the skills that appgen installed from the skills folders of agents.

    The command removes only the files that appgen installed, and keeps
    the files that a person added. It does not remove a file that a
    person changed, unless --force. The options select the folders as
    for 'appgen skills install'. The exit code is 0, or 1 if a file has
    changes or a folder cannot be written.
    """
    folders = _skills_folders(targets, scope, path, project_dir)
    plans = [plan_uninstall(skill, f, force=force) for f in folders for skill in skill_names()]
    _stop_at_changed_files(plans, "remove")
    _apply_plans(plans, dry_run, scope)
    for plan in plans:
        if not plan.changes:
            typer.echo(f"{plan.folder}: the skill '{plan.skill}' is not installed.")
            continue
        verb = "The uninstall would change" if dry_run else "Removed the skill from"
        typer.echo(f"{verb} {plan.folder}:")
        _echo_files(plan, dry_run)


def _skills_folders(
    targets: list[Target] | None, scope: Scope | None, path: Path | None, project_dir: Path | None
) -> list[Path]:
    if path is not None:
        if targets or scope is not None:
            typer.echo("error: give --path, or --target and --scope, not both.", err=True)
            raise typer.Exit(code=1)
        return [path]
    project = project_dir or Path.cwd()
    try:
        return [
            skills_folder(target, scope or Scope.PROJECT, project_dir=project)
            for target in sorted(set(targets or Target))
        ]
    except SkillsError as error:
        typer.echo(f"error: {error}", err=True)
        raise typer.Exit(code=1) from None


def _stop_at_changed_files(plans: list[Plan], verb: str) -> None:
    changed = [plan.folder / name for plan in plans for name in plan.changed]
    if not changed:
        return
    typer.echo(
        f"error: appgen does not {verb} files that a person changed, "
        "or that appgen did not install:",
        err=True,
    )
    for file in changed:
        typer.echo(f"  {file}", err=True)
    typer.echo(f"Move the changes, or run again with --force to {verb} the files.", err=True)
    raise typer.Exit(code=1)


def _apply_plans(plans: list[Plan], dry_run: bool, scope: Scope | None) -> None:
    try:
        for plan in plans:
            if plan.changes:
                check_writable(plan.folder)
        if dry_run:
            return
        for plan in plans:
            if plan.changes:
                apply(plan)
    except SkillsError as error:
        typer.echo(f"error: {error}", err=True)
        if scope is Scope.SYSTEM:
            typer.echo(
                "The system scope needs root, for example 'sudo appgen skills ...'.", err=True
            )
        raise typer.Exit(code=1) from None


def _echo_files(plan: Plan, dry_run: bool) -> None:
    for verb, files in (
        ("create" if dry_run else "created", plan.create),
        ("update" if dry_run else "updated", plan.update),
        ("delete" if dry_run else "deleted", plan.delete),
    ):
        for name in files:
            typer.echo(f"  {verb}: {name}")
    if plan.unchanged:
        typer.echo(f"  unchanged: {len(plan.unchanged)} files")
