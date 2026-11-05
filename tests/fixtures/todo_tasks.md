---
description: "Task list for todo app with login"
---

# Tasks: Todo app with login

**Input**: Design documents from `/specs/001-todo-login/`

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to

## Phase 1: Setup (Shared Infrastructure)

- [ ] T001 Create project structure in src/todo/__init__.py
- [ ] T002 [P] Configure pytest in pyproject.toml
- [ ] T003 [P] Configure ruff linting in ruff.toml

---

## Phase 2: Foundational (Blocking Prerequisites)

- [ ] T004 Setup SQLite database session in src/todo/db.py
- [ ] T005 [P] Create base User model in src/todo/models/user.py
- [ ] T006 [P] Setup FastAPI app and routing in src/todo/app.py

**Checkpoint**: Foundation ready

---

## Phase 3: User Story 1 - Log in (Priority: P1) 🎯 MVP

**Goal**: A user can log in with email and password.

### Tests for User Story 1

- [ ] T007 [P] [US1] Contract test for POST /login in tests/contract/test_login.py
- [ ] T008 [P] [US1] Integration test for login journey in tests/integration/test_login_flow.py

### Implementation for User Story 1

- [ ] T009 [P] [US1] Add password hashing in src/todo/security.py
- [ ] T010 [US1] Implement login service in src/todo/services/auth.py (depends on T009)
- [ ] T011 [US1] Implement POST /login endpoint in src/todo/api/login.py

---

## Phase 4: User Story 2 - Manage todos (Priority: P2)

### Tests for User Story 2

- [ ] T012 [P] [US2] Contract test for todo endpoints in tests/contract/test_todos.py

### Implementation for User Story 2

- [ ] T013 [P] [US2] Create Todo model in src/todo/models/todo.py
- [ ] T014 [US2] Implement todo service in src/todo/services/todos.py
- [ ] T015 [US2] Implement todo endpoints in src/todo/api/todos.py

---

## Phase 5: Polish & Cross-Cutting Concerns

- [ ] T016 [P] Documentation updates in docs/usage.md
- [ ] T017 Run quickstart.md validation

---

## Dependencies & Execution Order

- **Setup (Phase 1)**: No dependencies
- **User Stories (Phase 3+)**: All depend on Foundational phase completion
