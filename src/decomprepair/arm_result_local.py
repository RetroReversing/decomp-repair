"""A local updated in place by each arm of an `if` / `else if` / `else`, stored once: a result local of its own.

Matched on a KMC gcc 2.7.2 (`-G0 -mips3 -mgp32 -mfp32 -O2`) scroll-window update that stood at 2155: a field was read
into a local, nudged by one of three compound assignments (`v -= 8;`, `v -= quarter;`, `v += 8;`) chosen by a clamp on
the step, and stored back. The target keeps the field value (`$v1`) beside the new value (`$v0`): each arm writes the
result register with one `addiu` or `subu` in a branch delay slot and the store follows the join. Writing the arms
into a separate result local instead of updating the local in place gave that shape and dropped the score from
2155 to 1380 in one step.

arm_result_local
    `v = load; if (c1) v -= a; else if (c2) v -= b; else v += d; dst = v;` becomes `if (c1) r = v - a; else if (c2)
    r = v - b; else r = v + d; dst = r;` with a new local `r` of the same type, declared beside `v`. Every arm must be a
    single compound assignment to `v`, the chain must end in a plain `else` (so `r` is set on every path), and `v` must
    not be read after the store. Hypothesis from the match, not from the compiler source: updating `v` in place makes
    it a multi-set pseudo that keeps the copy of its first value live through every arm, while a result local is set
    once per path.

The exact judge decides every child; nothing here proves it is the compiler's reason.
"""
import re

from .integer_repair_support import IDENT, INTEGER, edit, view
from .pattern_repairs import close

FAMILY = 'arm_result_local'
FAMILIES = (FAMILY,)
LIMIT = 4
_ARM = re.compile(rf'(?P<lead>\s*(?:\{{\s*)?)(?P<v>{IDENT})\s*(?P<op>[-+*&|^]|<<|>>)=\s*(?P<x>[^;{{}}]+?)\s*;(?P<trail>\s*(?:\}}\s*)?)')
_IF = re.compile(r'\bif\s*\(')


def _declaration(part, name):
    """(match in the body, type) of `type name;` or `type name = ...;` as a statement of its own, else None."""
    base = part.opening + 1
    found = re.search(rf'(?m)^[ \t]*(?P<type>{INTEGER})\s+{re.escape(name)}\b(?:\s*=[^;,]*)?;', part.clean[base:part.end])
    return (base + found.start(), base + found.end(), re.sub(r'\s+', ' ', found['type'])) if found else None


def _operand(x):
    x = x.strip()
    return x if re.fullmatch(rf'-?(?:{IDENT}|\d+)', x) else f'({x})'


def _fresh(part):
    taken = set(re.findall(IDENT, part.clean[part.opening:part.end]))
    return next((c for c in ('result', 'result_value', 'arm_result') if c not in taken), None)


def _chain(clean, start, limit):
    """The arms of the `if` chain that begins at `start` as [(condition span or None, statement span)], and its end."""
    arms = []
    at = start
    while True:
        head = _IF.match(clean, at)
        condition = None
        if head:
            stop = close(clean, head.end() - 1)
            if stop is None:
                return None
            condition = (head.end(), stop - 1)
            at = stop
        arm = _ARM.match(clean, at)
        if not arm or arm.end() > limit:
            return None
        arms.append((condition, arm))
        at = arm.end()
        if condition is None:
            return arms, at
        tail = re.match(r'\s*else\b', clean[at:limit])
        if not tail:
            return None
        at += tail.end()
        while clean[at:at + 1].isspace():
            at += 1


def _children(source, name):
    part = view(source, name)
    if not part or re.search(r'\b(?:volatile|goto|asm|__asm__)\b', part.body):
        return []
    clean, result = part.clean, []
    for head in _IF.finditer(clean, part.opening + 1, part.end):
        if re.search(r'\belse\s*$', clean[:head.start()]):
            continue
        chain = _chain(clean, head.start(), part.end)
        if not chain:
            continue
        arms, end = chain
        if len(arms) < 2:
            continue
        v = arms[0][1]['v']
        if any(arm['v'] != v for _, arm in arms):
            continue
        store = re.compile(rf'\s*(?P<dst>[^;={{}}\n]+?)\s*=\s*{re.escape(v)}\s*;').match(clean, end)
        declared = _declaration(part, v)
        fresh = _fresh(part)
        if not store or not declared or not fresh or '==' in store['dst'] or re.search(r'[<>!]', store['dst'].replace('->', '')):
            continue
        # `v` is not read after the store (a write is fine), nor inside another arm's expression
        later = clean[store.end():part.end]
        if any(not re.match(r'\s*=(?!=)', later[m.end():]) for m in re.finditer(rf'\b{re.escape(v)}\b', later)):
            continue
        if any(re.search(rf'\b{re.escape(v)}\b', arm['x']) for _, arm in arms):
            continue
        edits = []
        for _, arm in arms:
            text = f'{arm["lead"]}{fresh} = {v} {arm["op"]} {_operand(arm["x"])};{arm["trail"]}'
            edits.append((arm.start(), arm.end(), text))
        edits.append((store.start('dst'), store.end(), f'{store["dst"]} = {fresh};'))
        indent = re.match(r'[ \t]*', source[source.rfind('\n', 0, declared[0]) + 1:declared[0]])[0]
        edits.append((declared[1], declared[1], f'\n{indent}{declared[2]} {fresh};'))
        result.append((FAMILY, edit(source, edits)))
    return result[:LIMIT]


def variants(source, name):
    return _children(source, name)


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}
