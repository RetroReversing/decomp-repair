"""A global scalar passed to a call, read into a local on the line before the call.

Matched on a KMC gcc 2.7.2 (`-G0 -mips3 -mgp32 -mfp32 -O2`) probe handler, 700 -> 280 on the exact judge. Three of its
calls passed a global word as the second of eleven arguments, `show(0, gMessageFlags, buffer, -1, -1, 1, 0, 0, 6, 0, 60)`,
and the target loads that word with the first scheduler's pick of the argument moves in front of the constants'. Written
inside the call, the load is emitted with the register arguments, after the stack arguments' stores, and the second
scheduler leaves it behind the buffer's address (`lui $a2` before `lui $a1`); read into a local on the line before, the
load is a pseudo of its own that the first scheduler hoists to where the target has it, and the moves of the other
arguments follow in the target's order.

call_global_stage
    `f(a, G, b);` becomes `T G_stage; ... G_stage = G; f(a, G_stage, b);` for a statement that is a call to a function (not a macro)
    whose argument is exactly the name of an `extern` integer scalar of this file or header (never a local, a parameter,
    an array, a pointer to be dereferenced or a `volatile` word) when every other argument has no call, `++`, `--` or
    assignment in it. One child per call that passes such a global, and one child with all of them when there are two
    or more. One local per global, shared by every call that stages it (a local of its own per call scored 700 where
    the shared one scored 280: three sets of one pseudo are not three pseudos). The copy is made with the arguments' order unchanged: the read happens before the other arguments are
    evaluated, so the other arguments are not allowed to write the global. Hypothesis from the match, not from the
    compiler source: a load held in a pseudo is scheduled where the load's latency wants it, a load that is part of the
    call's own argument moves is not.

The exact judge decides every child; nothing here proves it is the compiler's reason.
"""
import re

from .integer_repair_support import IDENT, INTEGER, edit, split_args, view

FAMILY = 'call_global_stage'
FAMILIES = (FAMILY,)
LIMIT = 8
_EXTERN = re.compile(rf'\bextern\s+(?P<type>{INTEGER})\s+(?P<name>{IDENT})\s*;')
_IMPURE = re.compile(rf'\+\+|--|(?<![=!<>])=(?!=)|\b(?!(?:sizeof)\b){IDENT}\s*\(')
_NOT_A_CALL = {'if', 'while', 'for', 'switch', 'return', 'sizeof', 'else', 'do'}


def _words(source, header, clean_body):
    """{name: type} of the `extern` integer words that are not volatile and are not shadowed in the function."""
    found = {}
    for text in (header, source):
        for hit in _EXTERN.finditer(text):
            found[hit['name']] = ' '.join(hit['type'].split())
    shadowed = set(re.findall(rf'\b(?:{INTEGER}|void|struct\s+{IDENT}|{IDENT})\s*\**\s+({IDENT})\s*(?=[;=,\[)])', clean_body))
    return {name: kind for name, kind in found.items() if name not in shadowed}


def plain_calls(part, skip=()):
    """[(statement start, closing paren, callee, [(arg start, arg end)])] of the plain call statements of a function:
    `f(...);` directly in a block, never a name in `skip` (the library's own macros and the words it stages)."""
    clean = part.clean
    found = []
    for hit in re.finditer(rf'(?<![\w.>])(?P<callee>{IDENT})\s*\(', clean[part.opening + 1:part.end - 1]):
        callee = hit['callee']
        start = part.opening + 1 + hit.start()
        opening = part.opening + 1 + hit.end() - 1
        if callee in _NOT_A_CALL or callee in skip:
            continue
        before = clean[:start].rstrip()
        if not before or before[-1] not in ';{}':
            continue
        depth, end = 0, -1
        for k in range(opening, part.end):
            depth += clean[k] == '('
            depth -= clean[k] == ')'
            if depth == 0:
                end = k
                break
        if end < 0 or not re.match(r'\s*;', clean[end + 1:]):
            continue
        found.append((start, end, callee, [(opening + 1 + a, opening + 1 + b) for a, b in split_args(clean[opening + 1:end])]))
    return found


def _statements(part, words):
    """[(statement start, statement end, [(arg start, arg end, global name)], callee)] of the calls that pass a word."""
    found = []
    for start, end, callee, spans in plain_calls(part, words):
        names = [re.fullmatch(rf'\s*({IDENT})\s*', part.clean[a:b]) for a, b in spans]
        staged = [(a + m.start(1), a + m.end(1), m[1]) for (a, b), m in zip(spans, names) if m and m[1] in words]
        others = [part.clean[a:b] for (a, b), m in zip(spans, names) if not (m and m[1] in words)]
        if not staged or any(_IMPURE.search(other) for other in others):
            continue
        found.append((start, end + 2, staged, callee))
    return found


def variants(source, name, header=''):
    part = view(source, name)
    if not part:
        return []
    words = _words(source, header, part.body)
    if not words:
        return []
    calls = _statements(part, words)[:LIMIT]
    taken = set(re.findall(IDENT, source + header))

    def edits(items):
        changes, declared = [], {}
        for start, _, staged, callee in items:
            first = source.rfind('\n', 0, start) + 1
            alone = not source[first:start].strip()
            lines = ''
            for a, b, word in staged:
                fresh = f'{word}_stage'
                if fresh in taken:
                    return None
                declared[fresh] = f'\n  {words[word]} {fresh};'
                lines += (source[first:start] if alone else '') + f'{fresh} = {word};' + ('\n' if alone else ' ')
                changes.append((a, b, fresh))
            changes.append((first if alone else start, first if alone else start, lines))
        changes.append((part.opening + 1, part.opening + 1, ''.join(declared.values())))
        return edit(source, changes)

    children = []
    for item in calls:
        text = edits([item])
        if text:
            children.append((FAMILY, text))
    if len(calls) > 1:
        text = edits(calls)
        if text:
            children.append((FAMILY, text))
    return children


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'header')}
