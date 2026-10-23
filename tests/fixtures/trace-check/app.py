# @trace app file
# The code folder of the trace check tests (tests/test_trace_report.py).


class Project:  # @trace entities.Project
    name: str  # @trace entities.Project.fields.name


class Task:  # @trace entities.Task
    title: str  # @trace entities.Task.fields.titel
    done: bool  # @trace:manual entities.Task.fields.done
