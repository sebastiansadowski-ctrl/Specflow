# Fikstury testowe

- `speckit_tasks_template.md`: oryginalny szablon `templates/tasks-template.md` z
  [github/spec-kit](https://github.com/github/spec-kit) (licencja MIT), commit `ec9a6f3b`.
  Zawiera placeholdery, więc parser musi go odrzucić. Symuluje model, który zostawił
  przykładowe zadania z szablonu.
- `todo_tasks.md`: poprawny plan dla aplikacji demo („lista zadań z logowaniem”),
  napisany w formacie Spec Kit.
- `speckit_constitution_template.md`, `speckit_spec_template.md`: szablony z Spec Kit
  **v1.3.0** (commit `34a0d38`, licencja MIT). Kontrole artefaktów muszą je odrzucić
  (nieuzupełnione pola, znaczniki `[NEEDS CLARIFICATION]`).
- `opencode/smoke.jsonl`: **nagranie z prawdziwego OpenCode 2.2.5** (model `openai/gpt-6.1-terra`,
  polecenie „utwórz hello.py”), zrobione `record.py` w kontenerze lab (M6b, etap 0). Test
  `test_opencode_smoke.py` sprawdza na nim mapowanie zdarzeń i raport agenta.
