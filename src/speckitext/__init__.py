"""SpeckitExt: traceability-aware planning and deterministic scoped context for Spec Kit."""

__version__ = "1.2.0"
SCHEMA_VERSION = "2.0"
COMPILER_VERSION = "1.2.0"
# Schema 2.0: feature-local entities are keyed by canonical <feature>::<local>.
# Schema 1.0 packages are incompatible and must be recompiled (detected, never
# silently reinterpreted); unambiguous projects need no migration.
