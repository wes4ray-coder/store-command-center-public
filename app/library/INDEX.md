# AI Library

> Offline knowledge base for AI agents. Last updated: 2026-07-10.
> **Search here before web searching.** Write learnings back.

## Quick Search

```bash
# Search entire library
rg -i "term" ~/.openclaw/library/

# Search a section
rg -i "term" ~/.openclaw/library/code-guides/
rg -i "term" ~/.openclaw/library/os-guides/
rg -i "term" ~/.openclaw/library/openclaw-docs/
rg -i "term" ~/.openclaw/library/project-docs/
rg -i "term" ~/.openclaw/library/error-solutions/
rg -i "term" ~/.openclaw/library/procedures/
```

## Sections

| Section | Path | Contents |
|---------|------|----------|
| OpenClaw Docs | `openclaw-docs/` | Full OpenClaw documentation + index |
| Code Guides | `code-guides/` | Language reference: Python, JS, TS, C#, Java, Go, Rust, PHP, HTML, CSS, SQL, Bash, Kotlin, Swift |
| OS Guides | `os-guides/` | OS reference: Ubuntu 24.04, General Linux, Windows, macOS |
| Project Docs | `project-docs/` | Store, Platform Dev, Agents, Infrastructure |
| Error Solutions | `error-solutions/` | Errors encountered + solutions (grows over time) |
| Procedures | `procedures/` | How-to guides (grows over time) |
| Archived Pages | `archived-pages/` | Saved web pages for offline reference |

## Rules for Agents

1. **Search library before web** — saves time, works offline
2. **Write solutions back** — if you solved it, document it for next time
3. **Archive useful pages** — if you fetch a web page that's useful, save it
4. **Keep practical** — commands, code, examples. Not theory.
5. **Update, don't duplicate** — check existing files first

## How to Contribute

### Found a solution to an error?
→ Write to `error-solutions/CATEGORY.md`

### Followed a procedure?
→ Write to `procedures/PROCEDURE-NAME.md`

### Learned infra info?
→ Update `project-docs/infrastructure/REFERENCE.md`

### Found a useful web page?
→ Save to `archived-pages/SOURCE-TOPIC.md` with source URL
