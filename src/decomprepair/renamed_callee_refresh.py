"""A call to a function the project has since renamed, rewritten to the name the target calls.

A saved candidate is C text; the project's symbol names are not part of it. When a function is given a real name
(`func_80008434` -> `appendProjectionViewportCommands`, by the app's rename) a candidate saved earlier still calls the old
one, the old name no longer links, and the judge scores the whole function as wrong at every call site (300 on an
842-instruction lighting function whose only difference was two such calls; the renamed source scored 0). Nothing in the
other families can reach it: no reshuffling of the body changes which symbol a `jal` names.

`variants` reads the function's own text and the target's assembly. A *stale* name is a callee the function calls (`f(...)`)
that the function does not define, that no `jal` of the target names and that the assembly never mentions at all (a name the
assembly uses as data, or a macro the project's header defines, is left alone). An *unclaimed* target is a `jal` target that the
function never calls by name. They are paired by call count: the stale name called K times with the unclaimed target
`jal`ed K times, when each count has exactly one of each (a guess between two equally frequent pairs would be a
coin flip, so none is offered). The pairing renames the name everywhere in the source, its prototype included, and is
offered as one child; a name the source already uses for another callee is never overwritten. This is a spelling of
which symbol is called, so a child that scores differently from its parent proves the pairing wrong (the judge decides)."""
import re

from .integer_repair_support import IDENT, view

FAMILY = 'renamed_callee_refresh'
FAMILIES = (FAMILY,)
_CALL = re.compile(rf'(?<![\w.>])({IDENT})[ \t]*\(')
_JAL = re.compile(r'\bjal[ \t]+([A-Za-z_?][\w$.?]*)')
_NOT_CALLS = {'if', 'while', 'for', 'switch', 'return', 'sizeof', 'else', 'do', 'case', 'defined', 'typeof', '__attribute__'}


def _called(body):
    """{name: number of call sites} for each `name(` in the function body that can be a callee."""
    counts = {}
    for hit in _CALL.finditer(body):
        if hit[1] not in _NOT_CALLS:
            counts[hit[1]] = counts.get(hit[1], 0) + 1
    return counts


def _defined(source):
    """The names the source gives a body (an inline helper, the function itself)."""
    return set(re.findall(rf'(?m)^[^\n;]*?\b({IDENT})[ \t]*\([^;{{}}]*\)[ \t\n]*\{{', source))


def _pairs(source, body, asm, name):
    targets = {}
    for hit in _JAL.finditer(asm):
        targets[hit[1].lstrip('?')] = targets.get(hit[1].lstrip('?'), 0) + 1
    calls = _called(body)
    defined = _defined(source) | {name}
    words = set(re.findall(r'[A-Za-z_]\w*', asm))
    stale = {n: k for n, k in calls.items() if n not in defined and n not in targets and n not in words}
    unclaimed = {n: k for n, k in targets.items() if n not in calls and n not in defined}
    pairs = []
    for count in sorted(set(stale.values())):
        old = [n for n, k in stale.items() if k == count]
        new = [n for n, k in unclaimed.items() if k == count]
        if len(old) == 1 and len(new) == 1 and not re.search(rf'\b{re.escape(new[0])}\b', source):
            pairs.append((old[0], new[0]))
    return pairs


def variants(source, name, asm=''):
    part = view(source, name)
    if not part or not asm:
        return []
    pairs = _pairs(source, part.clean[part.opening:part.end], asm, name)
    if not pairs:
        return []
    text = source
    for old, new in pairs:
        text = re.sub(rf'\b{re.escape(old)}\b', new, text)
    return [(FAMILY, text)] if text != source else []


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'asm'), 'archs': ('mips',), 'order': 10}
