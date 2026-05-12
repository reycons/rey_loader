# Project Assistant Contract

**Version:** 1.1  
**Reference:** See `docs/PROGRAMMING_CONTRACT.md` for complete standards

This file contains core rules. For detailed standards, use skills: `/python-standards`, `/sql-standards`, `/structure`

---

## 1. Accuracy First

- Do not guess, hallucinate, or invent syntax
- If uncertain, ask **one concise clarifying question**
- Prefer conservative, well-known approaches

---

## 2. Output Discipline

- Output **only what is requested**
- Do not add explanations unless explicitly requested
- Assume all code will be **copy-pasted into production**

---

## 3. Critical Python Rules

- Type hints on **all** function signatures, including explicit return types
- All functions and classes must have docstrings
- Comments **and** docstrings both required
- All code must comply with PEP 8, max 100 characters per line
- Explicit error handling — never silent failures
- Use `pathlib` for all file/path operations
- Forbidden: mutable default arguments, `global` keyword, `from x import *`
- Import order: stdlib → third-party → local (blank lines between groups)
- No commented-out code in production files

---

## 4. Critical SQL Rules

- Follow the SQL Contract exactly
- Optimize for large tables and predicate-driven queries
- No temp tables unless explicitly requested
- All procedures must be restart-safe
- No subqueries — use CTEs
- No string-formatted SQL — parameterized queries only

---

## 5. Change Control

When modifying existing code:

- Do **not** rewrite the entire script
- Show **only** the modified sections
- Include enough surrounding context to make changes unambiguous
- Preserve all surrounding formatting, comments, docstrings exactly
- Explain changes only if explicitly requested

---

## 6. Self-Check Before Output

Before delivering code, verify:

**Python:**
- [ ] Type hints and return types present
- [ ] Docstrings on all functions/classes
- [ ] No `print` statements (use logging)
- [ ] No mutable defaults, `global`, or wildcard imports
- [ ] Imports ordered correctly
- [ ] `pathlib` used for paths
- [ ] Exception chaining on re-raises: `raise X from original`

**SQL:**
- [ ] Tabs only (no spaces)
- [ ] Keywords UPPERCASE
- [ ] No subqueries (use CTEs)
- [ ] No `WHERE 1=1`
- [ ] Original table/column names preserved

---

## 7. Reset Clause

If context drifts:

- Discard prior assumptions
- Re-evaluate from scratch using this contract
- Reference `docs/PROGRAMMING_CONTRACT.md` for detailed rules

---

**For detailed rules:** Use `/python-standards`, `/sql-standards`, or `/structure`
