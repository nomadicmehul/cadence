---
name: Bug report
about: Something that should work doesn't
labels: bug
---

**What I tried**
<!-- Exact command or click path -->

**What I expected**

**What actually happened**
<!-- Stack trace, screenshot, console log -->

**Environment**
- OS:
- Python version (`python --version`):
- Auth: API key / Claude Code CLI / both
- App version (`git rev-parse --short HEAD`):

**If this is an analytics-import bug:**
Attach the .xlsx (with sensitive rows removed). The parser's column
detection is the most fragile part of the codebase.
