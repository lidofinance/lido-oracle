---
applyTo: "**/*.py"
---

# Python Code Quality (Soft Guidelines)

Suggest improvements for code clarity and common anti-patterns. These are suggestions, not blocking requirements.

## Repo Context
- Python 3.14 is used in this repository
- `ruff`, `pyright`, and pytest already cover many mechanical issues; focus comments on readability, maintainability, and correctness gaps not already caught automatically

## Dangerous Patterns
- **WARN**: Recursion without clear base case or depth limits
- **WARN**: Dynamic attribute access that could cause AttributeError
- **WARN**: Use of `exec()` or `eval()` without clear justification
- **WARN**: Adding attributes to class instances not defined in class

## Code Clarity
- Suggest avoiding deeply nested conditionals (>3 levels)
- Warn when functions have too many parameters (>7-8)
- Check for meaningful variable names

## Common Anti-patterns
- **SUGGEST**: Avoid mutable default arguments in function definitions
- **SUGGEST**: Don't catch bare `except:` without re-raising
- **SUGGEST**: Avoid `import *` except in justified cases
- **SUGGEST**: Avoid local imports without clear justification
- **SUGGEST**: Avoid broad exception handling that turns provider, consensus, or contract errors into silent success paths
- **SUGGEST**: Prefer explicit domain types (`Gwei`, `Wei`, blockstamp types, module ids) when changes otherwise blur protocol units or boundaries

## Review Communication
- Always explain WHY something is flagged as problematic
- Provide specific examples of better approaches
- Reference relevant standards when suggesting changes
