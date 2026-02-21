# Copilot Instructions

## Project

**rc_mail_assistant** is a Python AI assistant that helps Repair Café volunteers draft email responses to event-visit requests, using past responses as context.

## Development Workflow (Speckit)

All features follow the Speckit pipeline. **Do not start implementing before completing the spec and plan stages.**

### Starting a new feature

Run the feature creation script to create a branch and scaffold a spec:

```bash
.specify/scripts/bash/create-new-feature.sh "Your feature description"
# Optional flags: --short-name <name>, --number N
```

This creates:
- A git branch named `###-feature-name` (e.g., `001-draft-email`)
- `specs/###-feature-name/spec.md` from the spec template

### Pipeline order

| Stage | Command | Output |
|---|---|---|
| Specify | `speckit.specify` | `specs/###/spec.md` |
| Clarify | `speckit.clarify` | Updated `spec.md` |
| Plan | `speckit.plan` | `specs/###/plan.md`, `research.md`, `data-model.md`, `contracts/` |
| Tasks | `speckit.tasks` | `specs/###/tasks.md` |
| Implement | `speckit.implement` | Source code |
| Analyze | `speckit.analyze` | Consistency check |

### Key paths

- `specs/` — per-feature documentation (spec, plan, tasks, contracts)
- `.specify/memory/constitution.md` — project principles that govern all architecture decisions; check this before designing anything
- `.specify/templates/` — source-of-truth templates for specs, plans, tasks

## Conventions

- **Branch names**: `###-kebab-case-name` (3-digit zero-padded number + short descriptor)
- **Spec structure**: User stories must be independently testable P1/P2/P3 slices; each must deliver standalone value
- **Constitution gate**: Every plan must pass a constitution check before entering Phase 0 research (see `plan-template.md`)
- **`.specify/scripts/bash/`** scripts are auto-approved in VS Code terminal — invoke them directly without confirmation prompts
