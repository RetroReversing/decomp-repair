"""A command loop's skipped result copy given a wider result and a byte flag, and one arm that sets the flag itself.

The shape is the one `switch_default_join_skip` writes: the default sets the tested flag and jumps past the copy of
the arms' result into it,

    switch (op) {
        case 1: if (a && (t = p->x, result = 0, t != 0)) { ...; } else { goto release; } break;
        ...
        default: done = 0; goto test;
    }
    done = result;
    test:
    if (done & 0xFF) break;

In the target (KMC GCC 2.7.2, a 1315-instruction sound-sequence interpreter) the flag is in `$a0`, the default's
`move $a0, $zero` falls into the test and nineteen arms jump to the test with their own `move $a0, $zero` in the
delay slot, none merged. Three compiler facts decide it:

- global.c's `find_reg` takes the lowest free register (or a copy preference): the flag lives only from the
  default's zero and the copy to the test, conflicts with nothing and inherits `$v0` preferences, so it never gets
  `$a0` unless it is live across a value in `$v0`/`$v1`. An arm that sets the flag itself inside its test
  (`(t = p->x, done = 0, t != 0)`) and jumps straight to the test makes it live there (it takes `$a0`).
- Once both are in `$a0` the copy is a no-op that jump2 deletes. If the result and the flag are the same width the
  default's `(set (reg:QI a0) 0)` equals every arm's, the arms cross-jump into the default's zero, whose label is
  the (old) case label, and the next sweep merges the arms through `jump_chain` (22100). A word result (`s32`)
  against a byte flag (`u8`) makes the arms' zeros `(set (reg:SI a0) 0)`: `rtx_renumbered_equal_p` keeps them
  apart from the default's, the arms cross-jump into another arm's zero at a new label, and nothing merges.
- The copy from the word result into the byte flag is a truncation (no instruction), not a zero extension (the
  `s32` flag of the other order costs an `andi`).

Together: 785 -> 670 (the result type alone or the arm alone were no better). Children: the widened result with the
byte flag, alone and with each arm whose test sets the result to zero rewritten to set the flag and go to the test.
The cross-jump and allocation rules are read from jump.c and global.c; proposals only, the judge decides."""
import re

FAMILIES = ('join_skip_width_conflict',)
FAMILY = FAMILIES[0]
LIMIT = 6

_SKIP = re.compile(r'\n([ \t]*)default:\s*\n[ \t]*(\w+) = 0;\s*\n[ \t]*goto (\w+);\s*\n[ \t]*\}\s*\n'
                   r'[ \t]*\2 = (\w+);\s*\n[ \t]*\3:')
_NARROW = ('u8', 's8', 'unsigned char', 'signed char', 'char')
_WIDE = ('s32', 'u32', 'int', 'unsigned int', 'long')


def _decl(text, name):
    """The type of the one declaration of `name` (`T name;`), as (match start, end, type)."""
    found = list(re.finditer(r'(?m)^([ \t]*)((?:unsigned |signed )?\w+) ' + re.escape(name) + r';', text))
    if len(found) != 1:
        return None
    m = found[0]
    return m.start(2), m.end(2), m[2]


def _python_close(text, at, open_='{', shut='}'):
    depth = 0
    for i in range(at, len(text)):
        if text[i] == open_:
            depth += 1
        elif text[i] == shut:
            depth -= 1
            if depth == 0:
                return i
    return -1


_close = _python_close
try:  # the typed kernel (native_build.py), when it is built: same answers, the loop in C
    from . import _scan
except ImportError:
    _scan = None
if _scan is not None:
    def _close(text, at, open_='{', shut='}'):
        found = _scan.close_if(text, at, open_, shut, -1)
        return _python_close(text, at, open_, shut) if found is NotImplemented else found


def _arm_rewrites(text, result, flag, label, switch_at):
    """Arms whose `if` test assigns `result = 0` in a comma expression and whose statement ends in `break;`."""
    out = []
    for m in re.finditer(r'\b' + re.escape(result) + r' = 0(?=,)', text[:switch_at]):
        start = text.rfind('if (', 0, m.start())
        if start < 0:
            continue
        cond_end = _close(text, start + 3, '(', ')')
        if cond_end < m.end():
            continue
        brace = re.compile(r'\s*\{').match(text, cond_end + 1)
        if not brace:
            continue
        then_end = _close(text, brace.end() - 1)
        tail = re.compile(r'\s*else\s*\{').match(text, then_end + 1)
        after = then_end + 1
        if tail:
            after = _close(text, tail.end() - 1) + 1
        brk = re.compile(r'\s*break;').match(text, after)
        if not brk or then_end < 0:
            continue
        line = text.rfind('\n', 0, then_end) + 1
        last = text[:line].rstrip('\n')
        indent = re.match(r'[ \t]*', last[last.rfind('\n') + 1:])[0]
        new = (text[:m.start()] + flag + ' = 0' + text[m.end():line] + indent + 'goto ' + label + ';\n'
               + text[line:after] + text[brk.end():])
        out.append(new)
    return out


def variants(source, name=None, header=None):
    skip = _SKIP.search(source)
    if not skip:
        return []
    flag, label, result = skip[2], skip[3], skip[4]
    if not re.search(r'if \(\(?' + re.escape(flag) + r'\)? & 0xFF\)|if \(' + re.escape(flag) + r'\)', source):
        return []
    rd, fd = _decl(source, result), _decl(source, flag)
    if not rd or not fd:
        return []
    edits = []
    if rd[2] in _NARROW:
        edits.append((rd[0], rd[1], 's32'))
    if fd[2] in _WIDE:
        edits.append((fd[0], fd[1], 'u8'))
    if not edits:
        return []
    typed = source
    for a, b, t in sorted(edits, reverse=True):
        typed = typed[:a] + t + typed[b:]
    out = [typed]
    switch_at = _SKIP.search(typed).start()
    out.extend(_arm_rewrites(typed, result, flag, label, switch_at))
    return [(FAMILY, s) for s in out[:LIMIT] if s != source]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'header')}  # the registry: no caller wiring (registry.py)
