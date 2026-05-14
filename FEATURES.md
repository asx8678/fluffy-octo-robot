# Muse Filter Strategies

Real before/after examples from the test suite.

---

## Git — ~85% savings

### `git status`

**Before:**
```text
## main...origin/main [ahead 2, behind 1]
 M modified.py
 A added.py
 D deleted.py
?? untracked.py
?? another_untracked.md
```

**After (compact):**
```text
branch:main ↑2 ↓1  M:1 A:1 D:1 ?:2
```

### `git log`

**Before:**
```text
abc1234 fix: bug in parser
def5678 feat: new compression
ghi9012 chore: deps
```

**After:**
```text
3 commits
abc1234 fix: bug in parser
ghi9012 chore: deps
```

### `git diff`

**Before:**
```text
 src/core.py | 10 ++++++----
 tests/test_core.py | 5 +++++
 README.md | 2 +-
 3 files changed, 12 insertions(+), 5 deletions(-)
```

**After:**
```text
3 files changed, 12 insertions(+), 5 deletions(-)
```

---

## Test — ~90% savings

### `pytest`

**Before:**
```text
tests/test_x.py::test_foo PASSED
tests/test_x.py::test_bar FAILED
tests/test_x.py::test_baz SKIPPED
tests/test_x.py::test_qux PASSED

= 2 passed, 1 failed, 1 skipped in 0.5s =
```

**After (compact):**
```text
tests/test_x.py::test_bar FAILED
= 2 passed, 1 failed, 1 skipped in 0.5s =
```

### `cargo test`

**Before:**
```text
running 3 tests
test test_foo ... ok
test test_bar ... FAILED
test test_baz ... ok

test result: FAILED. 2 passed; 1 failed
```

**After:**
```text
test test_bar ... FAILED
test result: FAILED. 2 passed; 1 failed
```

---

## Lint — ~80% savings

### `ruff check .`

**Before:**
```text
file.py:5:1: E501 Line too long (120 > 88)
file.py:10:1: F841 Unused variable 'x'
other.py:3:1: E501 Line too long (100 > 88)
other.py:7:1: E501 Line too long (95 > 88)
```

**After:**
```text
E501: 2 files, 3 occurrences
F841: 1 files, 1 occurrences
```

### `golangci-lint`

**Before:**
```text
main.go:5:3: unusedParam unused parameter 'ctx' (unused-param)
pkg/util.go:10:1: lineLength line is 120 characters (line-length)
main.go:20:5: shadowDecl variable 'err' shadows declaration (shadow)
```

**After:**
```text
unused-param: 1 files, 1 occurrences
line-length: 1 files, 1 occurrences
shadow: 1 files, 1 occurrences
```

---

## Code — ~50% savings

### `cat file.py`

**Before:**
```python
import os
# This is a module

def foo():
    # helper
    return 1







# ... 50 more blank lines
```

**After:**
```python
import os

def foo():
    return 1
```

---

## Read — ~60% savings

### `grep` → grouped by file

**Before:**
```text
src/core.py:10:def foo():
src/core.py:25:def bar():
src/utils.py:5:import os
```

**After:**
```text
src/core.py: 2 matches
src/utils.py: 1 matches
```

### `find` → grouped by directory

**Before:**
```text
./src/core.py
./src/utils.py
./tests/test_core.py
./docs/
```

**After:**
```text
./src: 2 files
./tests: 1 files
./docs: 1 items
```
