# Documentation Guide

**Last Updated:** 2026-05-18

---

## Development Methodology

TokenBoard uses the `/make-*` command system for structured, phase-gated development. Each command produces a specific document type that flows into the next stage.

### Lifecycle

```
/make-research   →  /make-architect   →  /make-implement   →  /make-archive
(per idea)          (per feature)        (per feature)        (periodic)
docs/proposals/     docs/architecture/   docs/implementation/ docs/completed/ → docs/archive/
```

### Available Commands

| Command | Purpose |
|---------|---------|
| `/make-research` | Investigate an idea, produce `PROPOSAL-{Name}.md` with optional mockups |
| `/make-architect` | Plan a feature, produce `ARCHITECTURE-{Name}.md` |
| `/make-implement` | Execute phase-gated implementation, produce `IMPLEMENTATION-{Name}.md` |
| `/make-bug` | Dedicated bugfix investigation workflow |
| `/make-resolve` | Resolve a GitHub issue with guided planning + implementation |
| `/make-feedback` | Process user feedback into scored GitHub Issues |
| `/make-archive` | Move shipped docs from `completed/` to `archive/` |
| `/make-about` | View project information (Infrastructure, Design System, Capabilities, Learnings) |
| `/make-help` | Full command reference |

### Quick Start

1. **Idea to explore?** → `/make-research`
2. **Planning a feature?** → `/make-architect`
3. **Ready to code?** → `/make-implement`
4. **Challenging bug?** → `/make-bug`
5. **Got user feedback?** → `/make-feedback`
6. **Working on an issue?** → `/make-resolve`
7. **Need help?** → `/make-help`

---

## Documentation Structure

```
TokenBoard/
├── CLAUDE.md                 ← Project context (auto-loaded by Claude)
├── .claude/rules/            ← Scoped rules that load when matching files are edited
└── docs/
    ├── README.md             ← This file
    ├── INDEX.md              ← Registry of all documents
    ├── _references/          ← Standing reference documents
    │   └── DESIGN-SYSTEM.md  ← Visual design language reference
    ├── proposals/            ← PROPOSAL-*.md
    │   └── mockups/          ← HTML mockups (one folder per proposal)
    ├── architecture/         ← ARCHITECTURE-*.md (active planning)
    ├── implementation/       ← IMPLEMENTATION-*.md (active execution)
    ├── completed/            ← Recently shipped (full docs)
    ├── archive/              ← Older features (summaries only)
    ├── debugging/            ← DEBUGGING-*.md
    └── feedback/             ← Feedback analysis
```

---

## Key Principles

1. **Phase-gated development** — Never skip testing checkpoints between phases.
2. **Schema reality check** — Verify models in [app/db.py](../app/db.py) before architecting; see [CLAUDE.md](../CLAUDE.md) for the checklist.
3. **Human verification gates** — AI builds; the user verifies before declaring a phase done. TokenBoard has no automated test suite, so manual checklists in CLAUDE.md are load-bearing.
4. **Single-user, single-process assumption** — Documented in CLAUDE.md; any deviation is a proposal-level decision.
