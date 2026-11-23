"""A test of libultra's `osTvType` written as the game's `switch` over the three TV types (GCC 2.7.2, KMC, N64).

`osTvType` is 0 (PAL), 1 (NTSC) or 2 (MPAL). A search or m2c writes the game's switch as an `if`:

    x = 0;
    if (osTvType) {
        y = 0;
        x = y;
    } else {
        y = 0;
    }

and the game wrote

    x = 0;
    y = 0;
    switch (osTvType) {
    case 0:
        break;
    case 1:
    case 2:
        x = y;
        break;
    }

The two compile differently for a reason in jump.c: its store-flag rewrite of `x = a; if (c) x = b;` looks back for the
value `x` had (`reg_set_last`, rtlanal.c) and stops at a label. The `if` form is a candidate and becomes an `and`/`sltu`
sequence that cse then folds away with the branch; the switch's case labels stand between `x = 0` and the copy, so the
branch stays, cse keeps the copy (`move $s3,$s7` in the arm) and reorg puts the shared `y = 0` in the branch's delay slot.
Measured on a 556-instruction N64 split-screen setup routine (`gcc-2.7.2-kmc -G0 -mips3 -mgp32 -mfp32 -O2`), after
`cursor_deref_index`: 4335 -> 4065 (94 -> 62 differing rows; the prologue matched and two saved registers stopped
swapping), where every spelling of the `if` (both zeroes before it, the zero in each arm, `else` with a copy) stayed at
4335 or worse.

`variants` rewrites `if (osTvType) A else B` (also `!= 0`, `== 0` and `!osTvType` with the arms the other way round, and no
`else`): statements that open both arms identically are written once before the switch, `case 0:` runs what is left of
the PAL arm and `case 1: case 2:` the rest. A second child keeps the arms whole. The test must be `osTvType` itself, and
an arm may not contain `break`, `continue` or a `case` (they would change meaning inside a switch).
"""
import re

from .integer_repair_support import edit, view
from .pattern_repairs import close

FAMILY = 'tv_type_switch'
FAMILIES = (FAMILY,)
MAX_CHILDREN = 4

_IF = re.compile(r'\bif\s*\(')
_TEST = re.compile(r'\s*(?P<neg>!\s*)?osTvType\s*(?:(?P<op>[!=]=)\s*0\s*)?')
_FORBIDDEN = re.compile(r'\b(?:break|continue|case|default|switch)\b')


def _block(clean, at):
    """(start of the statement list, end of it, end of the whole arm) for the arm starting at `at`, or None."""
    m = re.match(r'\s*\{', clean[at:])
    if m:
        open_at = at + m.end() - 1
        shut = close(clean, open_at, '{', '}')
        return (open_at + 1, shut - 1, shut) if shut else None
    semi = clean.find(';', at)
    if semi < 0 or '{' in clean[at:semi] or re.match(r'\s*(?:if|while|for|do|switch)\b', clean[at:]):
        return None
    return at, semi + 1, semi + 1


def _statements(text):
    """The `;`-ended top-level statements of a straight run of code, or None if it holds anything else."""
    if '{' in text or '}' in text:
        return None
    out = [s.strip() + ';' for s in text.split(';')[:-1]]
    if text.split(';')[-1].strip():
        return None
    return [s for s in out if s != ';']


def _indent(source, at):
    line = source.rfind('\n', 0, at) + 1
    return re.match(r'[ \t]*', source[line:]).group()


def _switch(pad, common, pal, others):
    inner = pad + '  '
    lines = [pad + s if i else s for i, s in enumerate(common)]
    head = (('\n'.join(lines) + '\n' + pad) if common else '') + 'switch (osTvType) {\n'
    body = f'{pad}case 0:\n' + ''.join(f'{inner}{s}\n' for s in pal) + f'{inner}break;\n'
    body += f'{pad}case 1:\n{pad}case 2:\n' + ''.join(f'{inner}{s}\n' for s in others) + f'{inner}break;\n'
    return head + body + pad + '}'


def variants(source, name, header=''):
    part = view(source, name)
    if not part:
        return []
    clean = part.clean
    out = []
    for hit in _IF.finditer(clean, part.opening + 1, part.end):
        cond_open = hit.end() - 1
        cond_end = close(clean, cond_open)
        if not cond_end:
            continue
        test = _TEST.fullmatch(clean[cond_open + 1:cond_end - 1])
        if not test:
            continue
        then = _block(clean, cond_end)
        if not then:
            continue
        rest = re.match(r'\s*else\b', clean[then[2]:])
        other = _block(clean, then[2] + rest.end()) if rest else None
        if rest and not other:
            continue
        end = other[2] if other else then[2]
        if _FORBIDDEN.search(clean[cond_end:end]):
            continue
        a = _statements(source[then[0]:then[1]])
        b = _statements(source[other[0]:other[1]]) if other else []
        if a is None or b is None:
            continue
        zero_means_then = bool(test['neg']) != (test['op'] == '==')
        pal, others = (a, b) if zero_means_then else (b, a)
        common = []
        while pal and others and re.sub(r'\s+', '', pal[0]) == re.sub(r'\s+', '', others[0]):
            common.append(pal[0])
            pal, others = pal[1:], others[1:]
        pad = _indent(source, hit.start())
        whole_pal, whole_others = (a, b) if zero_means_then else (b, a)
        for text in (_switch(pad, common, pal, others), _switch(pad, [], whole_pal, whole_others)):
            child = edit(source, [(hit.start(), end, text)])
            if child != source and (FAMILY, child) not in out:
                out.append((FAMILY, child))
    return out[:MAX_CHILDREN]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'header')}
