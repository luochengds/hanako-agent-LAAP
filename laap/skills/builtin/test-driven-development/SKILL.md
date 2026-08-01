---
name: test-driven-development
description: Red-Green-Refactor TDD workflow for writing reliable code
version: 1.0.0
category: development
tags: [testing, tdd, quality]
platform: all
---

# Test-Driven Development Skill

Follow the Red-Green-Refactor cycle:

## RED Phase
1. Understand the requirement
2. Write a test that defines the expected behavior
3. Run the test — it should FAIL (red)

## GREEN Phase
1. Write the minimum code to make the test pass
2. Don't optimize yet — just make it work
3. Run the test — it should PASS (green)

## REFACTOR Phase
1. Clean up the code while keeping tests green
2. Remove duplication, improve naming, simplify logic
3. Run the test again to confirm it still passes

## Principles
- One test at a time
- Test behaviors, not implementations
- Keep tests fast and independent
- Use descriptive test names
