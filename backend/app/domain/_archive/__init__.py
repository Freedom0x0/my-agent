"""Archived DSL helpers — superseded by the MCP handler layer (see plan §7).

Kept around only because executor.py still uses `ConfirmationRequired`,
`InvalidPlanError`, `expected_confirmation_token`, `HIGH_IMPACT_KINDS` for the
legacy execute_plan path (used by /api/executions). The MCP / MiniMax path
bypasses this entirely.
"""
