"""An early `return K;` guard written as the guard block around the rest, with the same `return K;` after it.

Matched on a KMC gcc 2.7.2 (`-G0 -mips3 -mgp32 -mfp32 -O2`) voice-picker that opened with `if (disabled) return -1;`
and later had `if (best == -1) return -1;` before the commit of its pick. The target has one shared `return -1` block
(`addiu $v0,$zero,-1` at the end) that the guards jump to, and the branch that tests the pick against -1 compares
against the register that block's first insn also loads; the guard blocks written as `if (!disabled) { ... } return -1;`
and `if (best != -1) { ... }` gave that layout (5240 -> 4855 for the first, and the last 10 points of the match for
the second, where the block's own closing brace is followed by the function's `return -1;`).

early_return_guard_block
    `if (C) { return K; } REST` becomes `if (!C) { REST }` plus `return K;` when `REST` is everything up to the end of
    the enclosing block, ends in a `return` of its own (so it never falls out of the block), and `K` is a name or a
    number; the enclosing block is the function body (then `return K;` is added after the new block) or an `if` block
    that is itself followed by `return K;` (then nothing is added). `C` is negated by inverting its one top-level
    comparison, a leading `!` is dropped, and anything else is wrapped in `!( )`. Labels inside `REST` stay with it.

The exact judge decides every child; nothing here proves it is the compiler's reason.
"""
import re

from .c_scan import close, enclosing_block, header_before, normal
from .integer_repair_support import edit, view

FAMILY = 'early_return_guard_block'
FAMILIES = (FAMILY,)
LIMIT = 6
_IF = re.compile(r'\bif\s*\(')
_RETURN = re.compile(r'\breturn\s+(-?\s*[A-Za-z_0-9]\w*)\s*;')
_FLIP = {'==': '!=', '!=': '==', '<': '>=', '>=': '<', '>': '<=', '<=': '>'}
_COMPARE = re.compile(r'(==|!=|<=|>=|(?<![<>-])<(?![<=])|(?<![<>-])>(?![>=]))')


def _negate(condition):
    """The condition's opposite: its one top-level comparison inverted, a leading `!` dropped, or `!( )` around it."""
    text = condition.strip()
    depth, found = 0, []
    for hit in re.finditer(r'[()&|?,]|' + _COMPARE.pattern, text):
        if hit[0] == '(':
            depth += 1
        elif hit[0] == ')':
            depth -= 1
        elif hit[0] in '&|?,':
            if depth == 0:
                return f'!({text})'
        elif depth == 0:
            found.append(hit)
    if len(found) == 1:
        hit = found[0]
        return text[:hit.start()] + _FLIP[hit[0]] + text[hit.end():]
    if not found and re.fullmatch(r'![\w.]+', text):
        return text[1:]
    if not found and re.fullmatch(r'[\w.]+', text):
        return '!' + text
    return f'!({text})'


def _ends_with_return(text):
    """True when the last statement of `text` is a `return ...;` that is a statement of its own."""
    for hit in re.finditer(r'\breturn\b[^;{}]*;', text):
        if text[hit.end():].strip():
            continue
        before = text[:hit.start()].rstrip()
        return not before or before[-1] in ';{}:'
    return False


def _children(source, clean, low, high):
    out = []
    for hit in _IF.finditer(clean, low, high):
        opening = hit.end() - 1
        closing = close(clean, opening, '(', ')')
        if closing < 0 or re.search(r'\belse\s*$', clean[:hit.start()]):
            continue
        guard = re.match(r'\s*(?:\{\s*)?return\s+(-?\s*[A-Za-z_0-9]\w*)\s*;(\s*\})?', clean[closing + 1:])
        if not guard or bool(re.match(r'\s*\{', clean[closing + 1:])) != bool(guard[2]):
            continue
        value = normal(guard[1])
        end = closing + 1 + guard.end()
        if re.match(r'\s*else\b', clean[end:]):
            continue
        owner = enclosing_block(clean, hit.start(), low)
        if owner < 0:
            owner_close, add_return = close(clean, low - 1), True
        else:
            owner_close = close(clean, owner)
            if owner_close < 0 or not header_before(clean, owner).startswith('if'):
                continue
            follow = re.match(r'\s*else\b|\s*return\s+(-?\s*[A-Za-z_0-9]\w*)\s*;', clean[owner_close + 1:])
            if not follow or not follow[1] or normal(follow[1]) != value:
                continue
            add_return = False
        rest = clean[end:owner_close]
        if not rest.strip() or not _ends_with_return(rest):
            continue
        negated = _negate(source[opening + 1:closing])
        rest_source = source[end:owner_close]
        indent = re.match(r'[ \t]*', source[source.rfind('\n', 0, hit.start()) + 1:hit.start()])[0]
        tail = f'\n{indent}return {value};' if add_return else ''
        trail = rest_source[len(rest_source.rstrip()):]
        new = f'if ({negated})\n{indent}{{{rest_source.rstrip()}\n{indent}}}{tail}{trail}'
        out.append((hit.start(), owner_close, new))
    return out


def variants(source, name, header=''):
    part = view(source, name)
    if not part:
        return []
    return [(FAMILY, edit(source, [item])) for item in _children(source, part.clean, part.opening + 1, part.end)[:LIMIT]]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'header')}
