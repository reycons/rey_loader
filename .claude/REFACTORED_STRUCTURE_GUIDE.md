# Refactored Contract Structure Guide

## Overview

Your programming contract has been split into **three layers** to maximize Claude Code's effectiveness while keeping individual files concise:

```
.
├── CLAUDE.md                          # Minimal core rules (loads every session)
├── .claude/skills/
│   ├── python-standards.md            # Detailed Python rules (/python-standards)
│   ├── sql-standards.md               # Detailed SQL rules (/sql-standards)
│   └── structure.md                   # Architecture rules (/structure)
└── docs/
    └── PROGRAMMING_CONTRACT.md        # Full authoritative reference
```

---

## Layer 1: CLAUDE.md (Always Loaded)

**File:** `CLAUDE.md` (project root)

**Purpose:** Core rules that load on every Claude Code session. Kept concise to avoid context bloat.

**Contains:**
- Accuracy First
- Output Discipline
- Critical Python rules (type hints, docstrings, forbidden patterns)
- Critical SQL rules (format, CTEs, no subqueries)
- Change Control (how to modify existing code)
- Self-Check checklist

**When to use:** Claude automatically reads this every session.

---

## Layer 2: Skills (Invoke Explicitly)

Skills are detailed guides that Claude pulls in when you invoke them. Use when you need detailed guidance.

### `/python-standards`

**File:** `.claude/skills/python-standards.md`

**Invoke in Claude Code:** `/python-standards`

**Contains:**
- Naming conventions (snake_case, PascalCase, UPPER_SNAKE_CASE)
- Type hints and docstrings details
- Code quality (style, imports, max line length)
- Forbidden patterns with examples
- Error handling and logging
- Resource management (context managers)
- Data handling (chunking, memory management)
- File operations (pathlib)
- Dependencies and virtual environments
- Testing with pytest

**When to use:**
- Writing or reviewing Python code
- Setting up test structure
- Configuring dependencies

Example prompt:
```
/python-standards

Write a function to process user records from a CSV file.
```

---

### `/sql-standards`

**File:** `.claude/skills/sql-standards.md`

**Invoke in Claude Code:** `/sql-standards`

**Contains:**
- SQL formatting (tabs, UPPERCASE, commas, semicolons)
- CTEs and subquery rules
- Aliasing conventions
- Prohibited patterns (WHERE 1=1, subqueries, inline IN lists)
- Performance optimization for large tables
- Stored procedures structure and rules
- Parameter usage (no string-formatted SQL)
- Chunking for large operations
- Testing and EXPLAIN plans

**When to use:**
- Writing SQL queries or procedures
- Optimizing queries
- Designing data operations

Example prompt:
```
/sql-standards

Write a query to find users with the most orders in the last 90 days.
```

---

### `/structure`

**File:** `.claude/skills/structure.md`

**Invoke in Claude Code:** `/structure`

**Contains:**
- Python project layout
- Configuration management (YAML, .env, ctx)
- Module and function placement rules
- Dependency direction
- Entry point (main.py) template
- Public API declaration (__all__)
- Security best practices
- Change control specifics
- gitignore requirements
- Testing structure
- Dependencies and requirements.txt

**When to use:**
- Setting up a new project structure
- Organizing modules
- Configuring the application
- Understanding where code belongs

Example prompt:
```
/structure

I'm creating a data processing application. Help me structure the project.
```

---

## Layer 3: Full Reference (Read When Needed)

**File:** `docs/PROGRAMMING_CONTRACT.md`

**Purpose:** Authoritative complete contract for deep dives or conflicts.

**When to use:**
- As a complete reference when you need the full picture
- To resolve ambiguities between skills
- For pre-output verification checklists (Section 10)
- When detailed context matters

**Access in Claude Code:**
```
@docs/PROGRAMMING_CONTRACT.md review my code against the complete contract
```

---

## How to Use in Claude Code

### Pattern 1: Quick Python Question

```
/python-standards

Should I use dataclasses or plain classes here?
```

### Pattern 2: SQL Optimization

```
/sql-standards

This query is slow on our 100M row table. How can I optimize it?
```

### Pattern 3: Project Setup

```
/structure

Create the folder structure and main.py for a data pipeline.
```

### Pattern 4: Full Contract Review

```
@docs/PROGRAMMING_CONTRACT.md

Review this code against the complete contract and suggest fixes.
```

### Pattern 5: Combining Multiple Skills

```
/python-standards /structure

Write a module to process records with proper architecture and coding standards.
```

---

## Key Advantages

✅ **CLAUDE.md is lean** — ~60 lines instead of 470  
✅ **Context-efficient** — Only essential rules load every session  
✅ **Skills are discoverable** — Type `/` and see available guides  
✅ **Clear organization** — Each skill has one purpose  
✅ **Complete reference** — Full contract still available when needed  
✅ **Doesn't overwhelm Claude** — Follows best practice from Anthropic docs  

---

## When to Invoke Each Skill

| Situation | Skill |
|-----------|-------|
| Writing Python functions | `/python-standards` |
| Creating unit tests | `/python-standards` |
| Writing SQL queries | `/sql-standards` |
| Optimizing queries | `/sql-standards` |
| Setting up new project | `/structure` |
| Organizing modules | `/structure` |
| Configuring the app | `/structure` |
| Complete review needed | `@docs/PROGRAMMING_CONTRACT.md` |

---

## Quick Reference: Files & Locations

```
Your project root/
├── CLAUDE.md                     ← Loads automatically (core rules)
├── .claude/
│   └── skills/
│       ├── python-standards.md   ← Invoke: /python-standards
│       ├── sql-standards.md      ← Invoke: /sql-standards
│       └── structure.md          ← Invoke: /structure
├── docs/
│   └── PROGRAMMING_CONTRACT.md   ← Reference: @docs/PROGRAMMING_CONTRACT.md
├── .env                          ← Local secrets (don't commit)
├── .gitignore
├── requirements.txt              ← All dependencies pinned
├── main.py                       ← Orchestration only
└── {project_name}/               ← Your app logic
```

---

## Setup Instructions

1. **Copy files to your project:**
   ```bash
   # Create directories
   mkdir -p .claude/skills
   mkdir -p docs
   
   # Copy the CLAUDE.md to project root
   # Copy python-standards.md, sql-standards.md, structure.md to .claude/skills/
   # Copy PROGRAMMING_CONTRACT.md to docs/
   ```

2. **Commit to git:**
   ```bash
   git add CLAUDE.md .claude/skills/ docs/PROGRAMMING_CONTRACT.md
   git commit -m "Add programming contract and standards"
   ```

3. **Start using in Claude Code:**
   - Ask Claude about code: `/python-standards write a function...`
   - Ask about architecture: `/structure help me organize...`
   - Ask about SQL: `/sql-standards optimize this query...`

---

## Notes

- **CLAUDE.md** is automatically loaded every session — this is the "always active" set of rules
- **Skills** are opt-in — invoke them when you need detailed guidance
- **Full contract** is your authoritative reference for edge cases or conflicts
- The split prevents "instruction overload" while keeping all rules accessible
- Claude can handle multiple skills in one prompt: `/python-standards /structure`

