please create a rule based on the input given.
The rule file should be created in the ./.cursor/rules/ directory with a .mdc extension.
please sinff the formatting of cursor rules files and set approraite rule headers

the rule headers are created at the top of the rule file

e.g. 1 Awlays applies the rule
```
---
alwaysApply: true
---
```

e.g. 2 Applies the rule intelligently based on the description
```
---
description: rule for working in python
alwaysApply: false
---
```

e.g. 3 Applies the rule whenever working with the list of files types mentioned
```
---
globs: potato.tsx
alwaysApply: false
---
```

e.g. 4 Applies manually when the rule is explicitly mentioned
```
---
alwaysApply: false
---
```