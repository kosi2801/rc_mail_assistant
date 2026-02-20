# AI Workflow Guide — Repair Cafe Mail Assistant

This document defines how AI (GitHub Copilot CLI using Claude Sonnet 4.5) is used in this project to prevent architectural drift, maintain restart safety, and ensure long-term maintainability.

This file is operational guidance for development. It is NOT part of the project Constitution.

---

# 1. Core Rule

Before generating or modifying code:

> ALWAYS read:
>
> - CONSTITUTION.md
> - SPECIFICATION.md
> - CLARIFICATIONS.md
> - PLAN.md (current milestone section)

If the requested implementation conflicts with the Constitution, the Constitution wins.

---

# 2. Architecture Generation Prompt Template

Use this prompt when:

- Creating a new module
- Designing a new subsystem
- Refactoring structure
- Adding new adapters (LLM, Mail, DB, Vector, Job system)

---

## Architecture Prompt Template

```
You are working inside the Repair Cafe Mail Assistant project.

Before generating code:
1. Read CONSTITUTION.md
2. Read SPECIFICATION.md
3. Ensure compliance with:
   - Manual sync only (no auto-send)
   - Privacy-first (text only, no attachments stored)
   - Modular adapter architecture
   - Restart-safe background jobs
   - Raspberry Pi 5 (8GB RAM) constraints

Task:
[Describe feature/module here]

Requirements:
- Must be modular and replaceable
- Must not tightly couple to specific LLM backend
- Must support Ollama and llama.cpp abstraction layer
- Must tolerate Docker restarts
- Must use minimal dependencies

Deliver:
1. High-level design explanation (short)
2. Module boundaries
3. Data flow diagram (text form)
4. Python interfaces/classes
5. Only then provide implementation code

If you detect architectural violations, explain before coding.
```

---

# 3. Spec-Lock Enforcement Prompt

Use this prompt when:

- Adding new features
- Modifying existing flows
- After large changes
- When unsure if change violates architecture

---

## Spec-Lock Validation Prompt

```
Review the following code/module against the project Constitution and Specification.

Check for violations in:

1. Manual sync rule
2. No automatic outbound sending
3. Text-only storage (no attachment persistence)
4. Restart safety of jobs
5. Modular adapter boundaries
6. LLM backend abstraction consistency
7. Raspberry Pi memory constraints
8. Unnecessary dependencies

For each violation found:
- Explain the issue
- Explain why it violates project rules
- Propose a compliant fix

If no violations exist, explicitly confirm compliance.
```

---

# 4. Restart-Safety Validation Prompt

Use when:

- Creating or modifying background jobs
- Adding embedding generation
- Adding sync logic
- Modifying database write flows

```
Analyze this implementation for restart safety.

Assume:
- Docker shuts down nightly at 02:00
- Power loss can occur mid-operation

Check:
- Are DB writes transactional?
- Are job states persisted?
- Can in_progress jobs be safely re-queued?
- Is duplicate processing prevented?
- Is idempotency ensured?

If unsafe, propose concrete changes.
```

---

# 5. LLM Adapter Consistency Prompt

Use when:

- Editing LLM adapter
- Adding model configuration
- Changing prompt builder

```
Validate that this LLM integration:

- Does not depend on Ollama-specific features
- Can be swapped with llama.cpp without breaking interface
- Does not exceed reasonable context for small quantized models
- Keeps prompt concise and structured
- Separates prompt building from inference execution

If tight coupling exists, refactor toward adapter abstraction.
```

---

# 6. Refactor Safety Prompt

Use before large refactors.

```
Before refactoring:
1. Identify architectural invariants from Constitution
2. Identify coupling between modules
3. Identify persistence boundaries

After refactoring:
- Confirm invariants are preserved
- Confirm DB schema compatibility
- Confirm background jobs remain restart-safe
- Confirm manual sync behavior unchanged
```

---

# 7. Copilot CLI Usage Strategy

## When generating new files

Use structured prompts rather than inline short instructions.

Example:

```
copilot chat
```

Paste the Architecture Prompt Template with your feature description.

---

## When editing existing code

Ask Copilot to:

- "Refactor for modularity"
- "Validate against Constitution"
- "Check restart safety"

Avoid vague prompts like:

- "Improve this"
- "Optimize this"

Be constraint-specific.

---

# 8. Milestone Discipline Rule

For each milestone:

1. Implement only tasks listed in PLAN.md
2. Do not introduce unrelated improvements
3. Validate milestone against VALIDATION.md acceptance tests

No opportunistic architecture changes mid-milestone.

---

# 9. Model Usage Philosophy

Claude Sonnet 4.5 is used for:

- Architecture reasoning
- Module boundary enforcement
- Large refactors
- Structured code generation

Do NOT rely on AI memory across sessions. Always re-provide context or reference spec files explicitly.

---

# 10. Golden Rule

The AI assists development. It does not define architecture.

The Constitution defines architecture.

If conflict occurs → follow Constitution.

---

End of AI workflow guide.

