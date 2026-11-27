"""`v = *p + K;` in every arm of a `switch` and one `*p = v;` after it, written as `*p += K;` in each arm.

m2c merges the store every arm ends with into one statement after the `switch`:

    switch (c) {
    default:
        v = (f32) widths[c] + *x;
        break;
    case 32:
        v = *x + 14.0f;
        break;
    }
    *x = v;

The game wrote `*x += widths[c];` in one arm and `*x += 14.0f;` in the other; cross-jumping merges the identical
stores back, so the instructions have one store either way, but the load of `*x` comes first and the sum lands in its
register only with the compound form. On an N64 text-drawing loop (SN64 GCC 2.8.1, `-G0 -mips3 -O2 -mfp32`) the merged
form was 15 (three registers) and this one 0. Storing `*p = X;` in each arm alone (`switch_arm_store` does that for a
global) left it at 15, so the two are one child here.

The same program, or nothing: `v` has the type `p` points to (a narrower one truncated before the store); every arm that stores ends `v = E; break;` with `E` being `*p + K`, `K + *p` or
`*p - K` for one `p`; the other arms leave with `goto` or `return`; `*p = v;` is the first statement after the
`switch`; `v` appears nowhere else but its declaration; `K` neither calls, assigns, steps nor reads through `p`; the
`switch` has a `default` (an unmatched value would have stored too)."""
import re

from .csource import _blank, find
from .pattern_repairs import close

FAMILY = 'switch_arm_accumulate'
FAMILIES = (FAMILY,)
IDENT = r'[A-Za-z_]\w*'
_STORE = re.compile(rf'\s*\*\s*({IDENT})\s*=\s*({IDENT})\s*;[ \t]*\n?')
_EFFECT = re.compile(rf'\b(?!sizeof\b){IDENT}\s*\(|\+\+|--|(?<![=!<>])=(?!=)')


def _added(expression, pointer):
    """(operator, K) when `expression` is the old `*pointer` plus or minus K."""
    text = expression.strip()
    own = rf'\*\s*{pointer}\b(?!\s*[\[(.]|\s*->)'
    for pattern, operator in ((rf'{own}\s*([+-])\s*(.+)', None), (rf'(.+?)\s*(\+)\s*{own}', '+')):
        hit = re.fullmatch(pattern, text, re.S)
        if not hit:
            continue
        sign, other = (hit[1], hit[2]) if operator is None else (hit[2], hit[1])
        other = other.strip()
        flat, depth = '', 0
        for char in other.replace('->', '.'):
            depth += char in '(['
            if depth == 0:
                flat += char
            depth -= char in ')]'
            if depth == 0 and char in ')]':
                flat += ')'
        # a second top-level `+`, `-` or looser operator would regroup under `+=` (floats are not associative)
        if (re.search(r'[\w)]\s*(?:[+\-<>&|^?,]|[=!]=)', flat) or _EFFECT.search(other)
                or re.search(rf'(?<![\w.>]){pointer}\b', other)):
            continue
        return sign, other
    return None


def _arms(clean, brace, stop):
    """The `v = E; break;` spans of the switch's arms as (v, (start, end), (E start, E end)), or None unless every
    arm ends that way or leaves by `goto`/`return`."""
    found, floor, depth, at = [], brace + 1, 0, brace + 1
    leave = re.compile(r'\b(?:break|return\b[^;{}]*|goto\s+\w+)\s*;')
    while at < stop:
        depth += clean[at] == '{'
        depth -= clean[at] == '}'
        hit = leave.match(clean, at) if depth == 0 else None
        if hit and not (clean[at - 1].isalnum() or clean[at - 1] == '_'):
            if hit[0].startswith('break'):
                assign = re.search(rf'(?:^|[;:{{}}])\s*(({IDENT})\s*=(?!=)\s*([^;{{}}]+);)\s*$', clean[floor:at])
                if not assign:
                    return None
                found.append((assign[2], (floor + assign.start(1), floor + assign.end(1)),
                              (floor + assign.start(3), floor + assign.end(3))))
            floor = at = hit.end()
            continue
        at += 1
    return found if depth == 0 and not clean[floor:stop].strip() else None


def variants(source, name):
    """[(family, source)] with each arm adding into `*p` itself, or []."""
    span = find(source, name)
    if not span:
        return []
    clean = _blank(source)
    start, end = span
    opening = clean.find('{', start, end)
    if opening < 0 or re.search(r'\b(?:asm|__asm__)\b|(?m:^[ \t]*#)', clean[opening:end]):
        return []
    for head in re.finditer(r'\bswitch\s*\(', clean[opening:end]):
        paren = close(clean, opening + head.end() - 1, '(', ')')
        brace = clean.find('{', paren) if paren else -1
        stop = close(clean, brace, '{', '}') if brace >= 0 and not clean[paren:brace].strip() else None
        if not stop or not re.search(r'\bdefault\s*:', clean[brace:stop]):
            continue
        store = _STORE.match(clean, stop)
        arms = _arms(clean, brace, stop - 1) if store else None
        if not arms or len(arms) < 2 or {a[0] for a in arms} != {store[2]}:
            continue
        pointer, value = store[1], store[2]
        # a narrower carrier truncated the sum before the store: only one that has the pointee's own type
        kind = re.search(rf'(?m)(?:^|[;{{])[ \t]*({IDENT})\s+{value}\s*;', clean[opening:end])
        if not kind or not re.search(rf'(?<![\w]){kind[1]}\s*\*\s*{pointer}\b', clean[start:end]):
            continue
        if len(re.findall(rf'(?<![\w.>]){value}\b', clean[opening:end])) != len(arms) + 2:
            continue
        edits = []
        for _, (first, last), (e_start, e_end) in arms:
            added = _added(source[e_start:e_end], pointer)
            if not added:
                break
            edits.append((first, last, f'*{pointer} {added[0]}= {added[1]};'))
        else:
            tail = store.end()
            line = clean.rfind('\n', 0, stop) + 1
            lead = len(clean[stop:store.end()]) - len(clean[stop:store.end()].lstrip())
            at = stop + lead
            at_line = clean.rfind('\n', 0, at) + 1
            if at_line > line and not clean[at_line:at].strip():
                edits.append((at_line, tail, ''))
            else:
                edits.append((at, tail, ''))
            text = source
            for first, last, new in sorted(edits, reverse=True):
                text = text[:first] + new + text[last:]
            return [(FAMILY, text)]
    return []


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'order': 41}
