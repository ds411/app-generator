"""The effective UI states of a view (ADR 0003).

A view shows its own state, else the state in `ui.defaults.states`, else
the built-in state of this module.
"""

from appgen.dsl.model import AppDefinition
from appgen.dsl.ui.common import LoadingState, State, States
from appgen.dsl.ui.views import View

BUILT_IN_STATES = States(
    loading=LoadingState(indicator="skeleton"),
    empty=State(title="No records yet", icon="inbox"),
    error=State(title="Something went wrong", icon="triangle-alert", action="retry"),
)
"""The states that apply when neither the view nor `ui.defaults.states` sets them."""


def effective_states(definition: AppDefinition, view: View) -> States:
    """Return the loading, empty, and error states that a view shows."""
    defaults = definition.ui.defaults if definition.ui else None
    layers = [view.states, defaults.states if defaults else None, BUILT_IN_STATES]
    found = [layer for layer in layers if layer is not None]
    loading = next(layer.loading for layer in found if layer.loading is not None)
    empty = next(layer.empty for layer in found if layer.empty is not None)
    error = next(layer.error for layer in found if layer.error is not None)
    return States(loading=loading, empty=empty, error=error)
