---
name: django-multiline-comment-trap
description: A multi-line {# ... #} in a Django template is not a comment and renders as text — Django's lexer has no re.DOTALL
metadata:
  type: reference
---

Django's template lexer is:

```
tag_re = ({%.*?%}|{{.*?}}|{#.*?#})
```

with **`re.DOTALL` NOT set**. So `.` never matches a newline, and a `{# … #}`
comment that **spans more than one line is never recognised as a comment token
at all** — every line of it is emitted as literal text into the rendered page.

Single-line `{# … #}` is fine. Anything longer must be
`{% comment %}…{% endcomment %}`.

**Why it survives review and tests:** template tests almost always assert that
expected strings are *present*. Leaked developer prose is caught only by an
assertion in the other direction. Add one:

```python
for delimiter in ("{#", "#}", "{%", "{{", "}}"):
    self.assertNotIn(delimiter, html)
```

Check for false positives from CSS first — `@media`/`@page` nesting can put
braces adjacent, though on luffy-school-saas's report card it did not.

Also: **do not write `{#` or `#}` literally inside a template**, even in prose
warning about this, because the file is then one edit away from the bug.

Found on luffy-school-saas 2026-09-02 by `/code-review high`, on a card that
would have printed fifteen lines of prose under the school name. See
[[luffy-open-work-state]].
