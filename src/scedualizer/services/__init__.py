"""Pure business-logic services.

These modules are intentionally decoupled from Streamlit and SQL so they can be
unit-tested in isolation. They operate on plain data (rows / dataclasses) and
return new data, making conflict detection, recommendation, weekly-hours
calculation, export, and billing deterministic and testable.
"""
