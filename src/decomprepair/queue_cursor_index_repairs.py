"""m2c's cursors over a work queue on the stack, written back as the indexed accesses the counter already names.

A breadth-first walk keeps its pending objects in a local array, a write position that grows as objects are found and a
read position that follows. m2c writes each position twice, as a counter and as a pointer that steps with it:

    var_s2 = sp10;                              var_s5 = &sp10[var_s3];
    do { ...                                    do {
        *var_s2++ = node;                           item = *var_s5;
        count++;                                    ...
    } while (more);                                 var_s3++;  var_s5++;
                                                } while (var_s3 < end);

gcc 2.7.2 derives the address from the counter itself (`queue[count++] = node`, `queue[i]`) and keeps one pseudo
register for it instead of two, so the explicit pointers change which registers the saved values get and where the
loop steps are scheduled. A breadth-first walk over three levels (an N64 function) went from 2158 to 1658 with the
pointers written as `sp10[count]` and `sp10[i]`, the first of the edits that reached an exact match.

Offered for each pointer that is set to the array's start (the counter is then zero: its `count = 0;` is the last write
before) or to `&array[counter]`, and is then only ever stored through as `*p++ = value;` right before `counter++;`,
read as `*p`, or stepped as `p++;` beside `counter++;`, with the counter changed only by those steps. Every use of the
pointer must be in the block that sets it.
"""
import re

from .integer_repair_support import IDENT, edit, view

FAMILY = 'queue_cursor_index'
FAMILIES = (FAMILY,)
NM = r'(?<![\w.>])(?<!->)'
COUNT_STEP = rf'(?:({IDENT})\s*\+\+|\+\+\s*({IDENT})|({IDENT})\s*\+=\s*1)\s*;'


def _declaration_types(part):
    """Names of the local arrays."""
    found = set()
    for decl in re.finditer(rf'(?:(?<=[;{{}}])|^)\s*(?:(?:unsigned|signed|const|struct)\s+)*{IDENT}\s+([^;(){{}}=]*);', part.body):
        for item in re.finditer(rf'\**\s*({IDENT})\s*\[', decl[1]):
            found.add(item[1])
    return found


def _python_block_end(clean, at, limit):
    depth = 0
    for pos in range(at, limit):
        if clean[pos] == '{':
            depth += 1
        elif clean[pos] == '}':
            if depth == 0:
                return pos
            depth -= 1
    return None


_block_end = _python_block_end
try:  # the typed kernel (native_build.py), when it is built: same answers, the loop in C
    from . import _scan
except ImportError:
    _scan = None
if _scan is not None:
    def _block_end(clean, at, limit):
        found = _scan.enclosing_end(clean, at, limit, None)
        return _python_block_end(clean, at, limit) if found is NotImplemented else found


def _counter_moves(text, n):
    return len(re.findall(rf'{NM}{n}\s*(?:\+\+|--|\+=|-=|=(?!=))|(?:\+\+|--)\s*{n}\b|&\s*{n}\b', text))


def _rewrite(clean, lo, hi, arrays, cursor, array, index, start, end):
    """The edits that turn one cursor into indexed accesses, or None when it does anything else."""
    stop = _block_end(clean, end, hi)
    if stop is None:
        return None
    region = clean[end:stop]
    stores = list(re.finditer(rf'{NM}\*\s*{cursor}\s*\+\+\s*=(?!=)([^;{{}}]*);\s*{COUNT_STEP}', region))
    n = index
    if n == '0':
        names = {s[2] or s[3] or s[4] for s in stores}
        if len(names) != 1:
            return None
        n = names.pop()
        before = clean[lo:start]
        writes = list(re.finditer(rf'{NM}{n}\s*(?:=(?!=)|\+\+|\+=|-=|--)|(?:\+\+|--)\s*{n}\b|&\s*{n}\b', before))
        # the counter is zero where the cursor is set to the array's start: its last write before is `n = 0;`
        if not writes or not re.match(rf'{n}\s*=\s*0\s*;', before[writes[-1].start():]):
            return None
    if n in arrays or n == cursor or not re.fullmatch(IDENT, n):
        return None
    if any((s[2] or s[3] or s[4]) != n for s in stores):
        return None
    edits, spans = [], []
    for s in stores:
        # the counter's own step stays: it is the next statement
        edits.append((end + s.start(), end + s.end(1) + 1, f'{array}[{n}] ={s[1]};'))
        spans.append((s.start(), s.end(1) + 1))
    steps = list(re.finditer(rf'(?<![\w.>*])(?<!->){cursor}\s*\+\+\s*;|\+\+\s*{cursor}\s*;|{NM}{cursor}\s*\+=\s*1\s*;', region))
    for step in steps:
        paired = re.match(r'\s*' + COUNT_STEP.replace(IDENT, n), region[step.end():]) \
            or re.search(COUNT_STEP.replace(IDENT, n) + r'\s*$', region[:step.start()])
        if not paired:
            return None
        edits.append((end + step.start(), end + step.end(), ''))
        spans.append((step.start(), step.end()))
    for use in re.finditer(rf'{NM}{cursor}\b', region):
        if any(a <= use.start() < b for a, b in spans):
            continue
        before, after = region[:use.start()].rstrip(), region[use.end():]
        if not before.endswith('*') or before[-2:-1].isalnum() or before[-2:-1] in ')]_' \
                or re.match(r'\s*(?:\+\+|--|\[|[-+*/&|^<>]?=(?!=))', after):
            return None
        edits.append((end + len(before) - 1, end + use.end(), f'{array}[{n}]'))
    if _counter_moves(region, n) != len(stores) + len(steps) or not stores and not steps and not edits:
        return None
    return edits


def variants(source, name, header=''):
    part = view(source, name)
    if not part or re.search(r'\b(?:asm|__asm__|goto|setjmp|longjmp)\b|^\s*#', part.body, re.M):
        return []
    arrays = _declaration_types(part)
    if not arrays:
        return []
    lo, hi, clean = part.opening + 1, part.end - 1, part.clean
    names = '|'.join(map(re.escape, arrays))
    edits, cursors = [], set()
    for hit in re.finditer(rf'(?:(?<=[;{{}}])|^)\s*(?P<c>{IDENT})\s*=\s*(?:&\s*(?P<a>{names})\s*\[\s*(?P<x>{IDENT}|0)\s*\]|(?P<b>{names}))\s*;', clean[lo:hi]):
        cursor = hit['c']
        if cursor in arrays:
            continue
        found = _rewrite(clean, lo, hi, arrays, cursor, hit['a'] or hit['b'], hit['x'] or '0', lo + hit.start(), lo + hit.end())
        if found is not None:
            edits += found + [(lo + hit.start(), lo + hit.end(), '')]
            cursors.add(cursor)
    if not cursors:
        return []
    rewritten = edit(clean, edits)
    drops = []
    for cursor in cursors:
        mentions = list(re.finditer(rf'{NM}{cursor}\b', rewritten[lo:hi]))
        declaration = re.search(rf'(?:(?<=[;{{}}])|^)\s*((?:(?:unsigned|signed|const|struct)\s+)*{IDENT})\s+([^;(){{}}=\[\]]*\b{cursor}\b[^;(){{}}=\[\]]*);', part.body)
        if len(mentions) != 1 or not declaration:
            return []  # the pointer is still used somewhere the rewrite did not reach
        drops.append((cursor, declaration))
    by_declaration = {}
    for cursor, declaration in drops:
        items = by_declaration.setdefault(declaration.start(), (declaration, [i.strip() for i in declaration[2].split(',')]))[1]
        items[:] = [i for i in items if not re.fullmatch(rf'\**\s*{cursor}', i)]
    for declaration, items in by_declaration.values():
        edits.append((lo + declaration.start(), lo + declaration.end(),
                      f'{declaration[1]} {", ".join(items)};' if items else ''))
    return [(FAMILY, edit(source, edits))]
