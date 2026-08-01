---
name: code-review
description: Perform systematic code review against best practices
version: 1.0.0
category: development
tags: [review, code-quality, best-practices]
author: LAAP
platform: all
---

# Code Review Skill

When performing a code review, follow these steps:

1. **Understand the context**: Read the file and understand what it's trying to accomplish
2. **Check correctness**: Verify the logic is sound, edge cases are handled
3. **Check safety**: Look for security vulnerabilities, injection risks, unsafe patterns
4. **Check style**: Verify consistent naming, formatting, and code organization
5. **Check completeness**: Verify tests, documentation, and error handling

## Guidelines

- Be constructive and specific in feedback
- Prioritize issues: correctness > safety > performance > style
- Provide concrete examples of what to change
- For each issue, explain the "why" not just the "what"

## Output Format

```
## Review: <file>
### Correctness Issues
- Issue: description
  Fix: suggested change

### Safety Concerns
- Issue: description

### Suggestions
- Suggestion: description
```
