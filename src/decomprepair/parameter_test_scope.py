"""A parameter's early flag test computed in a one-shot scope, so the parameter outranks its neighbours for a saved register.

GCC 2.x hands the saved registers to pseudos in order of `floor_log2(refs) * refs / live length` (global.c), taking each
one's lowest free register, and flow.c counts a reference once per loop it sits in (`reg_n_refs += loop_depth`), so a
`do { } while (0);` is one reference more for every pseudo it names at no instruction cost (`argument_weight_scope`
does that for a parameter's first call, `loop_weight_scope` for counters). A function with many stack-passed
parameters is decided by it: a parameter that is read once, early, for a flag test (`if ((arg15 << 0x18) != 0)`) has two
references over a live range of 28 instructions (0.071) and loses to a parameter the switch arms read five times over
120 (0.083), so the target's order (the flag first, taking `$s2`, the other `$s3`) is not reachable from the plain
`if`. Three things made it hard for a one-edit search:

- the scope has to hold the *computation* of the flag and not the `if`: a scope around the whole `if`/`else` is also a
  loop whose `else` arm ends in the loop's exit jump, and jump.c's "if (foo) bar; else break;" rule then turns the
  arms around and moves one out of line (the second block after the jump table), so the whole function shifts;
- the scope must hold nothing else (a scope around the following stores freezes them in place: sched.c hangs the loop
  note on the next insn), and the compare with zero stays outside, so the flag is the bare `sll`;
- the flag needs a local of its own (an `int`), whose single set and single use cost no instruction.

A KMC GCC 2.7.2 N64 object spawner (`gcc-2.7.2-kmc -G0 -mips3 -mgp32 -mfp32 -O2`, 713 instructions, sixteen parameters:
the registers `$s2` and `$s3` exchanged between the sixteenth and the fourth, and `$s3`/`$s4`/`$s5` after them) matched
once `do { flag = arg15 << 0x18; } while (0); if (flag != 0)` opened the body: with the switch arms written plainly
the scope alone took the 40-odd register rows to 8 (1370 -> 1230), and with the other steps of the match to 0. The
priorities are read from `-dl -dg` (the flag's 3 references over 28 instructions, 0.107, against the fourth parameter's
5 over 120, 0.083); why the original source has this allocation is a hypothesis, the judge decides.

`variants` takes, for each parameter used at most three times in the body, the first `if (cond)` (not an `else if`)
whose condition names it, the condition having no `&&`, `||`, `?:`, comma or call, and writes the condition's
value (the left side of a trailing `!= 0` or `== 0`, else the whole condition) into a new `int` local inside
`do { } while (0);` right before the `if`, which then tests the local the same way. At most 8 proposals."""
import re

from .integer_repair_support import IDENT, edit, view
from .pattern_repairs import close

FAMILY = 'parameter_test_scope'
FAMILIES = (FAMILY,)
LIMIT = 8
USES = 3
_IF = re.compile(r'(?<![\w.])if\s*\(')
_ZERO = re.compile(r'^(?P<lhs>.*?)\s*(?P<op>!=|==)\s*0\s*$', re.S)


def _parameters(part):
    head = part.clean[:part.opening]
    if '(' not in head or ')' not in head:
        return []
    signature = head[head.rindex('(') + 1:head.rindex(')')]
    names = []
    for piece in signature.split(','):
        found = re.search(rf'({IDENT})\s*(?:\[[^\]]*\])?\s*$', piece)
        if found and found[1] != 'void':
            names.append(found[1])
    return names


def _flat(text):
    """Whether no `&&`, `||`, `?` or `,` sits at the top level of the expression `text`."""
    depth = 0
    for index, char in enumerate(text):
        depth += char in '([' ; depth -= char in ')]'
        if depth == 0 and (text.startswith(('&&', '||'), index) or char in '?,'):
            return False
    return True


def _strip(text):
    """`text` without one pair of parentheses that spans all of it."""
    text = text.strip()
    while text.startswith('(') and close(text, 0, '(', ')') == len(text):
        text = text[1:-1].strip()
    return text


def _fresh(clean, stem):
    name, number = stem, 0
    while re.search(rf'\b{re.escape(name)}\b', clean):
        number += 1
        name = f'{stem}{number}'
    return name


def variants(source, name):
    """Proposals: the first flag test of each rarely used parameter computed in a one-shot scope."""
    part = view(source, name)
    if not part:
        return []
    clean, body_at = part.clean, part.opening + 1
    out = []
    for parameter in _parameters(part):
        uses = [hit.start() for hit in re.finditer(rf'(?<![\w.>]){re.escape(parameter)}\b', clean[body_at:part.end])]
        if not 1 <= len(uses) <= USES:
            continue
        for hit in _IF.finditer(clean, body_at, part.end):
            if clean[body_at:hit.start()].rstrip()[-1:] not in ('', ';', '{', '}'):
                continue
            end = close(clean, hit.end() - 1, '(', ')')
            if not end:
                continue
            condition = source[hit.end():end - 1]
            if not re.search(rf'(?<![\w.>]){re.escape(parameter)}\b', condition) or not _flat(clean[hit.end():end - 1]):
                continue
            expression = _strip(condition)
            zero = _ZERO.match(expression)
            lhs, op = (_strip(zero['lhs']), zero['op']) if zero else (expression, None)
            if not lhs or not re.search(rf'(?<![\w.>]){re.escape(parameter)}\b', lhs):
                break
            if re.search(rf'(?<![\w.>])(?!sizeof\b){IDENT}\s*\(', lhs):
                continue  # a call is a different scope question (argument_weight_scope)
            flag = _fresh(clean, f'{parameter}_flag')
            line = clean.rfind('\n', 0, hit.start()) + 1
            indent = source[line:hit.start()] if not source[line:hit.start()].strip() else ''
            test = f'{flag} {op} 0' if op else flag
            scope = f'do {{ {flag} = {lhs}; }} while (0);\n{indent}'
            declare = f'\n    int {flag};'
            out.append(edit(source, [(hit.start(), hit.start(), scope), (hit.end(), end - 1, test),
                                     (part.opening + 1, part.opening + 1, declare)]))
            break
    return [(FAMILY, text) for text in dict.fromkeys(out)][:LIMIT]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'order': 99}  # the registry: no caller wiring (registry.py)
