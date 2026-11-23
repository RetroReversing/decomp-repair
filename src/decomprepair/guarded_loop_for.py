"""A guarded do-while over a bound copied from an unsigned field, written as the counted `for` it came from.

Matched on a KMC gcc 2.7.2 (`-G0 -mips3 -mgp32 -mfp32 -O2`) scroll-window update that stood at 3427: two loops summed
the heights of the first `selected` and the first `count` rows. m2c wrote each as `bound = w->count; i = 0; if (bound)
{ do { total += w->rows[i++].height; } while (i < bound); }`. The target keeps the byte read once for the guard and
copies it for the loop test (`lbu $v0,0x19; beqz $v0; ... move $a0,$v0`), and has no copy of the counter before the
increment; the spelling that gives it is `for (i = 0; i < w->count; i++) total += w->rows[i].height;`, where the loop
pass hoists the loop-invariant byte load and cse folds the hoisted load into a move of the guard's. That alone
(3427 -> 3152, with the bound locals gone) is the first step of that match.

guarded_loop_for
    `b = P->f; ... i = 0; if (b) { do { S(i++) } while (i < b); }` becomes `... for (i = 0; i < P->f; i++) S(i)` when
    `f` is declared unsigned in the source or header (so the guard `b != 0` and the first test `0 < b` agree), the
    statements between the copy and the loop only assign locals, `b` is not read afterwards, and the body is one
    statement with exactly one `i++`. Hypothesis from the match, not from the compiler source: a bound read through the
    member is a loop-invariant load for loop.c, a local copy is a register the loop pass cannot move.

The exact judge decides every child; nothing here proves it is the compiler's reason.
"""
import re

from .csource import _blank
from .integer_repair_support import IDENT, INTEGER, edit, view
from .pattern_repairs import close

FAMILY = 'guarded_loop_for'
FAMILIES = (FAMILY,)
LIMIT = 6
_UNSIGNED = r'(?:u8|u16|u32|unsigned(?:\s+(?:char|short|int))?)'
_LOOP = re.compile(
    rf'(?P<i>{IDENT})\s*=\s*0\s*;\s*if\s*\(\s*(?P<b>{IDENT})\s*\)\s*\{{\s*do\s*\{{\s*(?P<body>[^{{}}]*?)\s*\}}\s*'
    rf'while\s*\(\s*(?P=i)\s*<\s*(?P=b)\s*\)\s*;\s*\}}')
_DECLARATION = re.compile(rf'(?m)^[ \t]*{INTEGER}\s+[^;=(]*;')
_COPY = rf'(?P<base>{IDENT})\s*->\s*(?P<field>{IDENT})'
_PLAIN = re.compile(rf'\s*{IDENT}\s*=(?!=)\s*[^;{{}}]*?\s*;')


def _names(text, name):
    return [m for m in re.finditer(rf'\b{re.escape(name)}\b', text) if not re.search(r'(?:->|\.)\s*$', text[:m.start()])]


def _enclosing(text, position, low, high):
    """(start, end) of the innermost `{ }` around `position`, or the whole function body."""
    stack = []
    for m in re.finditer(r'[{}]', text[low:position]):
        if m[0] == '{':
            stack.append(low + m.start())
        elif stack:
            stack.pop()
    if not stack:
        return low, high
    return stack[-1], close(text, stack[-1], '{', '}') or high


def _written_before_read(clean, start, low, high, name):
    """True when every read of `name` after `start` follows a write of it in a block that still encloses the read."""
    writes = []
    for m in _names(clean[start:high], name):
        at = start + m.start()
        if re.match(r'\s*=(?!=)', clean[start + m.end():]):
            writes.append(_enclosing(clean, at, low, high))
        elif not any(a <= at < b for a, b in writes):
            return False
    return True


def _unsigned_field(context, field):
    for hit in re.finditer(rf'\b(?P<type>{IDENT}(?:\s+{IDENT})?)\s+(?P<names>[^;{{}}]*\b{re.escape(field)}\b[^;{{}}]*);', context):
        if re.fullmatch(_UNSIGNED, re.sub(r'\s+', ' ', hit['type'])):
            return True
    return False


def _children(source, name, header):
    part = view(source, name)
    if not part or re.search(r'\b(?:volatile|goto|asm|__asm__)\b', part.body):
        return []
    context = _blank(header) + '\n' + _blank(source)
    clean, result = part.clean, []
    for loop in _LOOP.finditer(clean, part.opening + 1, part.end):
        i, b, body = loop['i'], loop['b'], loop['body'].strip()
        steps = re.findall(rf'\b{re.escape(i)}\s*\+\+', body)
        if len(steps) != 1 or re.search(rf'\+\+\s*{re.escape(i)}\b|\b{re.escape(i)}\s*(?:--|[-+*/&|^]?=(?!=))', body):
            continue
        if body.count(';') != 1 or not body.endswith(';') or re.search(r'\b(?:if|for|while|do|return|break|continue)\b', body):
            continue
        before = clean[part.opening + 1:loop.start()]
        copies = list(re.finditer(rf'\b{re.escape(b)}\s*=\s*{_COPY}\s*;', before))
        if len(copies) != 1 or not _unsigned_field(context, copies[0]['field']):
            continue
        copy = copies[0]
        between = before[copy.end():]
        if between.strip():
            statements = [s + ';' for s in between.strip().split(';') if s.strip()]
            if not all(_PLAIN.fullmatch(s) and not _names(s, b) and not re.search(IDENT + r'\s*\(', s) for s in statements):
                continue
        if not _written_before_read(clean, loop.end(), part.opening, part.end, b):
            continue
        earlier = _DECLARATION.sub(lambda m: ' ' * len(m.group(0)), before[:copy.start()])
        if any(not re.match(r'\s*=(?!=)', earlier[m.end():]) for m in _names(earlier, b)):
            continue
        bound = f'{copy["base"]}->{copy["field"]}'
        new_body = re.sub(rf'\b{re.escape(i)}\s*\+\+', i, body)
        base = part.opening + 1
        start = base + copy.start()
        line = source.rfind('\n', 0, start) + 1
        whole_line = not source[line:start].strip() and source[base + copy.end():base + copy.end() + 1] == '\n'
        removal = (line, base + copy.end() + 1, '') if whole_line else (start, base + copy.end(), '')
        loop_text = f'for ({i} = 0; {i} < {bound}; {i}++) {new_body}'
        result.append((FAMILY, edit(source, [removal, (loop.start(), loop.end(), loop_text)])))
    return result[:LIMIT]


def variants(source, name, header=''):
    return _children(source, name, header)


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'header')}
