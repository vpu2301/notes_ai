"""The meeting document: what the author typed, and what the invite knew.

Two pure modules, no I/O and no model:

* :mod:`user_notes` — the author's lines, their keys, and the transcript
  window each one was typed against.
* :mod:`agenda` — the agenda hiding in a calendar invite's description.

Nothing is re-exported here on purpose: ``agenda`` is imported by the
calendar parsers and ``user_notes`` pulls in the note repositories, so a
convenience import at package level would drag the second into the first.
Import the submodule you need.
"""
