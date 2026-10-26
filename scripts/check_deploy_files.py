"""Validate the deployment files of an app against their schemas, without a cluster.

The FastAPI and the Next.js bindings write the files of each deployment
target of the key `x-fastapi-deploy` or `x-nextjs-deploy` (ADR 0013):
`deploy/kubernetes/` (Kustomize) and `deploy/knative/` (a Knative Service
that Google Cloud Run accepts). The script generates the two examples
with both targets, one with the Redis store of the rate limit (and for
FastAPI, tests/fixtures/files.yaml with the files in a bucket and in a
folder), and checks each file of `deploy/`:

- A Kubernetes object: the JSON schema of the Kubernetes API, strict, so
  that an unknown field is an error (yannh/kubernetes-json-schema).
- The Knative Service: the JSON schema of the Knative CRD
  (datreeio/CRDs-catalog).
- The Kustomization: the schema of SchemaStore. Its resources and env
  files must exist (`secret.env` as `secret.example.env`).
- Each environment variable is a setting of the app: a field of
  `Settings` in `app/core/config.py` (FastAPI), or a `process.env` value
  that the code reads, or `HOSTNAME` and `PORT` of the server (Next.js).
  The files of the Knative target set the same variables as the files of
  the Kubernetes target.
- With gcloud installed: the Knative Service converts to the messages of
  the Cloud Run API without an unknown field, as in `gcloud run services
  replace`. Without gcloud, the script skips this step.

The script downloads the schemas once, into a cache folder. Run it from
the repository root:

    uv run scripts/check_deploy_files.py {fastapi,nextjs}

Environment variables:
    KUBERNETES_VERSION    The version of the Kubernetes schemas (default v1.34.0).
    APPGEN_SCHEMA_CACHE   The folder of the schemas (default ~/.cache/appgen/schemas).
"""

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import urllib.request
from collections.abc import Iterator
from pathlib import Path
from typing import Any, cast

import yaml
from jsonschema import Draft7Validator
from jsonschema.validators import validator_for

from appgen.bindings.fastapi import model as fastapi
from appgen.bindings.nextjs import model as nextjs
from appgen.dsl import load_definition_text
from appgen.gen import find_binding, generate

EXAMPLES: dict[str, tuple[tuple[str, dict[str, str], dict[str, str]], ...]] = {
    binding: (
        ("examples/project-tracker/app.yaml", {model.DEPLOY_KEY: "[kubernetes, knative]"}, {}),
        (
            "examples/room-booking/app.yaml",
            {model.DEPLOY_KEY: "[kubernetes, knative]", model.RATE_LIMIT_STORE_KEY: "redis"},
            {},
        ),
    )
    for binding, model in (("fastapi", fastapi), ("nextjs", nextjs))
}
# The files of the file fields (ADR 0027) in an S3 bucket, and in a folder.
FILES = "tests/fixtures/files.yaml"
for binding, model in (("fastapi", fastapi), ("nextjs", nextjs)):
    EXAMPLES[binding] += (
        (FILES, {model.DEPLOY_KEY: "[kubernetes, knative]"}, {}),
        (
            FILES,
            {model.DEPLOY_KEY: "[kubernetes, knative]"},
            {"  kind: s3\n  bucket_env: LIBRARY_BUCKET\n": "  kind: local\n"},
        ),
    )
"""The definitions of each binding, the keys that the script adds to their `app` section, and
the texts that it replaces."""
NEXTJS_SERVER_SETTINGS = {"HOSTNAME", "PORT"}
"""The settings that the standalone server of Next.js reads, not the code of the app."""
KUBERNETES_SCHEMAS = "https://raw.githubusercontent.com/yannh/kubernetes-json-schema/master"
CRDS_CATALOG = "https://raw.githubusercontent.com/datreeio/CRDs-catalog/main"
KNATIVE_SERVICE_SCHEMA = f"{CRDS_CATALOG}/serving.knative.dev/service_v1.json"
KUSTOMIZATION_SCHEMA = "https://json.schemastore.org/kustomization.json"

CLOUD_RUN_PARSE = """
import sys
from apitools.base.protorpclite import messages
from googlecloudsdk.api_lib.util import apis, messages as messages_util
from googlecloudsdk.core import yaml

def unknown(message, path):
    found = [path + "." + name for name in message.all_unrecognized_fields()]
    for field in message.all_fields():
        value = message.get_assigned_value(field.name)
        if isinstance(field, messages.MessageField) and value is not None:
            for item in value if field.repeated else [value]:
                found += unknown(item, path + "." + field.name)
    return found

service = yaml.load(sys.stdin.read())
try:
    run = apis.GetMessagesModule("run", "v1")
    message = messages_util.DictToMessageWithErrorCheck(service, run.Service)
except Exception as error:
    sys.exit(str(error))
sys.exit("\\n".join(unknown(message, "Service")) or None)
"""
"""Convert a Knative Service to the Cloud Run API messages with the Python of gcloud."""


class CheckError(Exception):
    """A failed check."""


def log(message: str) -> None:
    print(f"deploy-files: {message}", flush=True)


def schema(url: str) -> dict[str, Any]:
    """Return a JSON schema, from the cache or downloaded."""
    default = Path.home() / ".cache" / "appgen" / "schemas"
    cache = Path(os.environ.get("APPGEN_SCHEMA_CACHE", default))
    path = cache / f"{hashlib.sha256(url.encode()).hexdigest()[:16]}-{url.rsplit('/', 1)[-1]}"
    if not path.exists():
        with urllib.request.urlopen(url, timeout=60) as response:
            data: bytes = response.read()
        json.loads(data)
        cache.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    return json.loads(path.read_text())


def schema_url(api_version: str, kind: str) -> str:
    """Return the URL of the JSON schema of a kind."""
    if (api_version, kind) == ("serving.knative.dev/v1", "Service"):
        return KNATIVE_SERVICE_SCHEMA
    if (api_version, kind) == ("kustomize.config.k8s.io/v1beta1", "Kustomization"):
        return KUSTOMIZATION_SCHEMA
    group, _, version = api_version.rpartition("/")
    name = "-".join([kind.lower(), *([group.split(".")[0]] if group else []), version])
    kubernetes = os.environ.get("KUBERNETES_VERSION", "v1.34.0")
    return f"{KUBERNETES_SCHEMAS}/{kubernetes}-standalone-strict/{name}.json"


def validate(document: dict[str, Any], where: str) -> None:
    """Validate one YAML document against the schema of its kind."""
    url = schema_url(str(document.get("apiVersion")), str(document.get("kind")))
    found = schema(url)
    validator = validator_for(found, default=Draft7Validator)(found)
    errors = sorted(validator.iter_errors(document), key=lambda e: list(e.absolute_path))
    if errors:
        lines = [f"/{'/'.join(map(str, e.absolute_path))}: {e.message}" for e in errors[:10]]
        raise CheckError(f"{where} does not match {url}:\n  " + "\n  ".join(lines))


def settings(binding: str, files: dict[str, str]) -> set[str]:
    """Return the environment variables of the settings of the app."""
    if binding == "nextjs":
        code = "".join(c for path, c in files.items() if path.endswith((".ts", ".tsx")))
        # `process.env.NAME`, or `env.NAME` of a function that takes the environment.
        return set(re.findall(r"\benv\.([A-Z_][A-Z0-9_]*)", code)) | NEXTJS_SERVER_SETTINGS
    config = files["app/core/config.py"].split("class Settings", 1)[1]
    return {name.upper() for name in re.findall(r"(?m)^    (\w+): ", config)}


def environment(path: str, content: str, document: dict[str, Any] | None) -> Iterator[str]:
    """Return the names of the environment variables that a file sets."""
    if path.endswith(".env"):
        yield from re.findall(r"(?m)^([A-Z_][A-Z0-9_]*)=", content)
        return
    spec = cast(dict[str, Any], (document or {}).get("spec") or {})
    pod = cast(dict[str, Any], spec.get("template") or {}).get("spec") or {}
    for container in cast(list[dict[str, Any]], pod.get("containers") or []):
        yield from (env["name"] for env in container.get("env") or [])


def check_kustomization(folder: str, document: dict[str, Any], files: dict[str, str]) -> None:
    """Check that the resources and the env files of a Kustomization exist."""
    names = list(document.get("resources") or [])
    generators = [*document.get("configMapGenerator", []), *document.get("secretGenerator", [])]
    for generator in generators:
        names += [n if n != "secret.env" else "secret.example.env" for n in generator["envs"]]
    missing = [name for name in names if f"{folder}/{name}" not in files]
    if missing:
        raise CheckError(f"{folder}/kustomization.yaml names files that do not exist: {missing}")


def check_cloud_run(path: str, content: str) -> None:
    """Convert a Knative Service to the Cloud Run API messages, as gcloud does."""
    gcloud = shutil.which("gcloud")
    if gcloud is None:
        log(f"skip the Cloud Run check of {path}: gcloud is not installed")
        return
    info = subprocess.run(
        [gcloud, "info", "--format=value(installation.sdk_root,basic.python_location)"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.split()
    root, python = Path(info[0]), info[1]
    paths = os.pathsep.join(str(root / "lib" / p) for p in ("", "third_party"))
    result = subprocess.run(
        [python, "-c", CLOUD_RUN_PARSE],
        input=content,
        capture_output=True,
        text=True,
        env={**os.environ, "PYTHONPATH": paths},
        check=False,
    )
    if result.returncode != 0:
        problem = (result.stderr.strip().splitlines() or ["no output"])[-5:]
        raise CheckError(f"Cloud Run does not accept {path}:\n  " + "\n  ".join(problem))


def check(binding: str, example: str, keys: dict[str, str], changes: dict[str, str]) -> None:
    source = Path(example)
    text = source.read_text()
    lines = "".join(f"  {key}: {value}\n" for key, value in keys.items())
    text, count = re.subn(r"(?m)^app:\n", f"app:\n{lines}", text, count=1)
    if count != 1:
        raise CheckError(f"{source} has no 'app:' line.")
    for old, new in changes.items():
        if old not in text:
            raise CheckError(f"{source} has no text {old!r}.")
        text = text.replace(old, new)
    # The path of the example, so that the loader finds the OpenAPI documents of `apis`.
    result = generate(load_definition_text(text, str(source)), find_binding(binding))
    files = {f.path: f.content for f in result.files}
    deploy = sorted(path for path in files if path.startswith("deploy/"))
    keys_text = ", ".join(f"{k}: {v}" for k, v in keys.items())
    changed = f" and {len(changes)} changed texts" if changes else ""
    log(f"{example} with {keys_text}{changed}: {len(deploy)} files")
    known = settings(binding, files)
    targets: dict[str, set[str]] = {}
    for path in deploy:
        content = files[path]
        documents: list[Any] = [None]
        if path.endswith(".yaml"):
            documents = [d for d in yaml.safe_load_all(content) if d is not None]
            for document in documents:
                validate(document, path)
                if document["kind"] == "Kustomization":
                    check_kustomization(path.rsplit("/", 1)[0], document, files)
                if document["apiVersion"].startswith("serving.knative.dev/"):
                    check_cloud_run(path, content)
        for document in documents:
            names = set(environment(path, content, document))
            unknown = sorted(names - known)
            if unknown:
                raise CheckError(f"{path} sets variables that are not settings: {unknown}")
            targets.setdefault(path.split("/")[1], set()).update(names)
    if len(targets) > 1 and len(set(map(frozenset, targets.values()))) > 1:
        kubernetes, knative = targets["kubernetes"], targets["knative"]
        raise CheckError(
            f"The targets set other variables: only Kubernetes {sorted(kubernetes - knative)}, "
            f"only Knative {sorted(knative - kubernetes)}."
        )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("binding", choices=sorted(EXAMPLES))
    binding = parser.parse_args().binding
    try:
        for example, keys, changes in EXAMPLES[binding]:
            check(binding, example, keys, changes)
    except (CheckError, OSError, subprocess.CalledProcessError) as error:
        print(f"deploy-files: failed: {error}", file=sys.stderr)
        return 1
    log("passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
