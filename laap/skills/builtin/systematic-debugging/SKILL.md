---
name: systematic-debugging
description: Structured debugging approach for diagnosing and fixing issues
version: 1.0.0
category: development
tags: [debugging, troubleshooting]
platform: all
---

# Systematic Debugging Skill

Follow this structured approach when debugging issues:

## 1. Reproduce
- Get the exact error message/logs
- Understand the conditions that trigger the issue
- Note the environment (OS, versions, configuration)

## 2. Isolate
- Find the minimal reproduction case
- Use bisect or divide-and-conquer to narrow down
- Check recent changes that might have introduced the bug

## 3. Diagnose
- Read relevant code/source files carefully
- Check for common patterns: null pointers, race conditions, type errors
- Use tools: read_file, search_files, execute_command

## 4. Fix
- Propose a minimal fix
- Verify the fix doesn't break other functionality
- Add regression tests if applicable

## 5. Verify
- Confirm the fix resolves the original issue
- Run related tests
- Document the root cause and fix
