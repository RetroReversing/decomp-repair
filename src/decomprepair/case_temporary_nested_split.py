"""A switch's shared temporary split per case when the cases nest their first assignment or the switch has labels.

`case_temporary_repairs` splits a local that several cases of one switch use, one local per case, but only for a switch
with no label inside it and only when each case starts with the plain assignment `name = expression;` at the case's own
nesting level. m2c's state machines break both: a shared `goto block_29;` target sits inside one case, and the value is
assigned in the middle of a block (`{ marker = G; temp = marker->f; ... if (temp < 0.0f) ... }`) or inside a condition
(`if (((temp = x->f) <= 0.0f) || (temp >= 1.0f))`). One name is one pseudo register for the whole function, so the float
compare in one case gets the register the other case's longer-lived use outranks it for (`c.lt.s $f2,$f0` where the
target has `c.lt.s $f0,$f2`): a 349-instruction function, 320 -> 300 for one case's float local given a name of its own.

A case's uses of `name` are renamed (to `name_<case>`) only when, inside that case:
  - the first mention is an assignment `name = ...` (not `==`), so no value reaches the case from another one,
  - every later mention lies in the block that holds that first assignment (the assignment dominates them),
  - no label (`block_29:`) falls between the first and the last mention (a `goto` could enter in the middle and read a
    value another case set),
and `name` is not mentioned outside the switch, never has its address taken, and is declared once at the top of the
function without an initialiser. The labels of the switch's own cases are what delimit the cases.

`variants` gives, labelled `case_temporary_nested_split`: one local used by several cases renamed in all of them (the
first case keeps the original), and in each case alone.
"""
import re

from .case_temporary_repairs import DECLARATION, LABEL, _depth_at, _fresh, _identifiers, _mentions, _rename, _switches
from .csource import _blank, find
from .pattern_repairs import close

FAMILY = 'case_temporary_nested_split'
FAMILIES = (FAMILY,)
LIMIT = 24
OTHER_LABEL = re.compile(r'(?m)(?<![\w?:])(?!(?:case|default)\b)([A-Za-z_]\w*)[ \t]*:(?!:)[ \t]*(?:\n|;|\w|\})')


def _cases(clean, body, nested):
    """[(label text, start, end)] of the switch's own top-level case groups, labels inside them allowed."""
    start, finish = body
    labels = []
    for m in LABEL.finditer(clean, start + 1, finish):
        if any(a < m.start() < b for a, b in nested):
            continue
        if _depth_at(clean, start + 1, m.start()) != 0:
            return None
        labels.append(m)
    groups = []
    for k, m in enumerate(labels):
        stop = labels[k + 1].start() if k + 1 < len(labels) else finish
        groups.append((m.group().strip().rstrip(':').strip(), m.end(), stop))
    return groups


def _python_enclosing_block(clean, group_start, pos):
    """(open, close) of the innermost block holding `pos`, searching from the case's start; the case itself when none."""
    stack = []
    for k in range(group_start, pos):
        if clean[k] == '{':
            stack.append(k)
        elif clean[k] == '}' and stack:
            stack.pop()
    return stack[-1] if stack else None


_enclosing_block = _python_enclosing_block
try:  # the typed kernel (native_build.py), when it is built: same answers, the loop in C
    from . import _scan
except ImportError:
    _scan = None
if _scan is not None:
    def _enclosing_block(clean, group_start, pos):
        found = _scan.open_stack(clean, group_start, pos)
        if found is not NotImplemented:
            return found[-1] if found else None
        return _python_enclosing_block(clean, group_start, pos)


def _dominated(clean, name, start, stop):
    """True when the first mention of `name` in [start, stop) is an assignment that dominates the others."""
    pattern = _mentions(name)
    mentions = list(pattern.finditer(clean, start, stop))
    if not mentions:
        return None
    first = mentions[0]
    if not re.match(r'\s*=(?!=)', clean[first.end():stop]):
        return False
    if re.search(r'&\s*' + re.escape(name) + r'\b', clean[start:stop]):
        return False
    block = _enclosing_block(clean, start, first.start())
    last = mentions[-1]
    if block is not None:
        finish = close(clean, block, '{', '}')
        if not finish or last.end() > finish:
            return False
    if any(m.start() > first.start() and m.start() < last.end() for m in OTHER_LABEL.finditer(clean, start, stop)):
        return False
    return len(mentions) > 0


def variants(source, name):
    span = find(source, name)
    if not span:
        return []
    clean = _blank(source)
    opening = clean.find('{', span[0], span[1])
    end = close(clean, opening, '{', '}') if opening >= 0 else None
    if not end:
        return []
    declarations = {}
    for m in DECLARATION.finditer(clean, opening + 1, end):
        if _depth_at(clean, opening + 1, m.start()) == 0 and '(' not in m['type']:
            declarations.setdefault(m['name'], m)
    taken = _identifiers(source)
    switches = _switches(clean, opening, end)
    result = []

    def emit(text):
        if text != source and text not in [t for _, t in result] and len(result) < LIMIT:
            result.append((FAMILY, text))

    for body in switches:
        nested = [s for s in switches if body[0] < s[0] and s[1] < body[1]]
        groups = _cases(clean, body, nested)
        if not groups or len(groups) < 2:
            continue
        for var, decl in declarations.items():
            if decl.start() > body[0] or re.search(r'&\s*' + re.escape(var) + r'\b', clean[opening:end]):
                continue
            pattern = _mentions(var)
            outside = [(opening, decl.start()), (decl.end(), body[0]), (body[1], end)]
            if any(pattern.search(clean, a, b) for a, b in outside):
                continue
            used = []
            for k, (_, a, b) in enumerate(groups):
                verdict = _dominated(clean, var, a, b)
                if verdict is None:
                    continue
                if verdict is False:
                    used = None
                    break
                used.append(k)
            if not used or len(used) < 2:
                continue
            names = {k: _fresh(var, groups[k][0], k, taken) for k in used}
            if len(set(names.values())) != len(names):
                continue
            line = source[decl.start():decl.end()]
            cut = line.rindex(var)
            plans = [used[1:]] + [[k] for k in used]
            if len(used) == 2:
                plans = [[used[1]]] + [[used[0]]]
            for chosen in plans:
                text = source
                for k in sorted(chosen, reverse=True):
                    text = _rename(text, _blank(text), [(groups[k][1], groups[k][2])], var, names[k])
                lines = ''.join(line[:cut] + names[k] + line[cut + len(var):] for k in reversed(chosen))
                emit(text[:decl.end()] + lines + text[decl.end():])
    return result


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'order': 70}
