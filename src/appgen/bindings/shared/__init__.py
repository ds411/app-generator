"""Templates and helpers that the front-end bindings (Next.js and React) share.

`TEMPLATE_DIR` holds the shadcn/ui component templates (`shadcn/`), the
theme templates (`theme/`), the entity templates (`src/`), and the shared
UI code (`ui/`, see `appgen.bindings.shared.ui`). A binding adds it to
`Binding.shared_template_dirs`, so that its templates and its output
rules can use the shared templates by name, for example
`shadcn/button.tsx.j2`. The entity templates need the template globals
of `typescript.HELPERS`, and the UI templates those of `ui.HELPERS`.
"""

from pathlib import Path

TEMPLATE_DIR = Path(__file__).parent / "templates"
"""The folder of the shared templates."""
