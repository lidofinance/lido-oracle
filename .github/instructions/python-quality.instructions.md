# Python Code Quality (Soft Guidelines)

Suggest improvements for code clarity and common anti-patterns. These are suggestions, not blocking requirements.

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

## Review Communication
- Always explain WHY something is flagged as problematic
- Provide specific examples of better approaches
- Reference relevant standards when suggesting changes