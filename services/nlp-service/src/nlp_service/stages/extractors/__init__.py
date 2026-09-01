"""Focused extractors behind the single ``field_extraction`` stage.

One stage, one module per field-type family: ``choice`` for
choice/multi_choice, ``numeric_date`` for numeric/date binding.
"""

from .choice import extract_choice, extract_multi_choice

__all__ = ["extract_choice", "extract_multi_choice"]
