"""Shared parts of the UI test definitions."""

UI_TOKENS = """\
  tokens:
    color:
      slate: { $value: "#64748b" }
      blue: { $value: "#2563eb" }
      primary: { $value: "#2563eb" }
    size:
      col_lg: { $value: 16rem }
      sidebar: { $value: 16rem }
      content: { $value: 80rem }
    spacing:
      4: { $value: 1rem }
      6: { $value: 1.5rem }
      8: { $value: 2rem }
    breakpoint:
      sm: { $value: 640px }
      md: { $value: 768px }
      lg: { $value: 1024px }
"""
"""The tokens that the UI test definitions use, below the `ui` key."""
