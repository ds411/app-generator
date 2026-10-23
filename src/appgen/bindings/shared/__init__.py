"""Templates and helpers that the front-end bindings (Next.js and React) share.

`TEMPLATE_DIR` holds the shadcn/ui component templates (`shadcn/`), the
theme templates (`theme/`), and the entity templates (`src/`). A binding
adds it to `Binding.shared_template_dirs`, so that its templates and its
output rules can use the shared templates by name, for example
`shadcn/button.tsx.j2`. The entity templates need the template globals
of `typescript.HELPERS`.
"""

from pathlib import Path

TEMPLATE_DIR = Path(__file__).parent / "templates"
"""The folder of the shared templates."""
