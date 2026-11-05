"""Orkiestrator (M3).

Deterministyczna pętla i maszyna stanów, NIE agent LLM (patrz docs/adr/0001).
Wybiera zadania gotowe w DAG-u, pilnuje limitów czasu i prób, zmienia statusy.
AI wołane jest tylko przez harness i w części weryfikacji.
"""
