"""A constant assigned before an `if`, read only after a `goto` join, moved down to the join.

m2c writes a value two paths share as one variable assigned first: `v = 0xFF; if (c) { ...; if (!x) { v = 0xBF;
goto L; } <own stores> } else { L: <stores using v> }`. The assignment is then live across the whole condition and
the then-branch, and the compiler gives it a register of its own ($a0); where the game assigns it only on the
path that reaches the join (the `else`, and the `goto` path after its own assignment), it lives in $v0 and the
instruction sits in a branch delay slot. An N64 actor-update function's colour block (three byte stores of 0xFF or
0xBF) was 780 with the early assignment and exact with it moved to the label (with the stores typed `u8`, since a
constant above 0x7F stored through `s8 *` is `li -1`).

Offered when `V = K;` is directly followed by `if (...) {then} else {else}`, `then` only assigns V (before its `goto L`),
`L:` is a label inside the `else`, V is read nowhere before `L:`, and nothing reads V after the whole statement. Three
children, cheapest first: the assignment sunk to the label; that with a constant local (`int c = 0xFF;`) written as its
literal; and that with the `s8` byte stores of V or of a literal above 0x7F typed `u8`.
"""
import re

from .csource import _blank, find
from .pattern_repairs import close

FAMILY = 'join_initializer_sink'
FAMILIES = (FAMILY,)

IDENT = r'[A-Za-z_]\w*'
NUMBER = r'(?:0[xX][0-9a-fA-F]+|\d+)'
ASSIGN = re.compile(rf'(?m)^(?P<indent>[ \t]*)(?P<var>{IDENT})\s*=\s*(?P<value>{NUMBER}|{IDENT})\s*;[ \t]*\n')


def _int(text):
    try:
        return int(text, 0)
    except ValueError:
        return None


def _statement(clean, at):
    """(then_start, then_end, else_start, else_end, statement_end) of the `if (...) {..} [else {..}]` at `at`, else None."""
    m = re.compile(r'\s*if\s*\(').match(clean, at)
    if not m:
        return None
    paren = clean.rfind('(', m.start(), m.end())
    cond_end = close(clean, paren)
    if not cond_end:
        return None
    m = re.compile(r'\s*\{').match(clean, cond_end)
    if not m:
        return None
    then_start = m.end() - 1
    then_end = close(clean, then_start, '{', '}')
    if not then_end:
        return None
    m = re.compile(r'\s*else\s*\{').match(clean, then_end)
    if not m:
        return then_start, then_end, None, None, then_end  # no else
    else_start = m.end() - 1
    else_end = close(clean, else_start, '{', '}')
    return (then_start, then_end, else_start, else_end, else_end) if else_end else None


def _enclosing(clean, at, lo):
    """Start of the innermost `{` block around `at`, searching back no further than `lo`."""
    depth = 0
    for pos in range(at - 1, lo - 1, -1):
        if clean[pos] == '}':
            depth += 1
        elif clean[pos] == '{':
            if depth == 0:
                return pos
            depth -= 1
    return lo


def _assigned_before_goto(clean, var, region_start, goto_at):
    """True when the innermost block around a `goto` (inside `region_start..`) assigns `var` before it."""
    block = _enclosing(clean, goto_at, region_start)
    return re.search(rf'\b{var}\s*=(?!=)', clean[block:goto_at]) is not None


def _joins(clean, var, parts, statement_end, end):
    """(label_at, label_name, gotos_region) for each way the statement reaches a label V is then read from."""
    then_start, then_end, else_start, else_end, _ = parts
    found = []
    arms = ((else_start, else_end, then_start, then_end), (then_start, then_end, else_start, else_end))
    for inside_start, inside_end, goto_start, goto_end in (arms if else_start is not None else ()):
        label = re.search(rf'(?m)^[ \t]*({IDENT}):', clean[inside_start:inside_end])
        if label and f'goto {label[1]};' in clean[goto_start:goto_end]:
            # a join inside one arm, reached by a `goto` from the other: V must not be read anywhere else
            if not re.search(rf'\b{var}\b', clean[inside_start:inside_start + label.start()]) \
                    and not re.search(rf'\b{var}\b', clean[statement_end:end]):
                found.append((inside_start + label.start(), label[1], goto_start, goto_end, 'arm'))
    # a join after the whole statement (`if (c) {T; goto L;} [else {..}] M; L: R`): V is read only from L on
    tail = re.search(rf'(?m)^[ \t]*({IDENT}):', clean[statement_end:end])
    if tail and not re.search(r'\b(?:case|default)\b', tail[0]) and tail[1] not in ('default',):
        at = statement_end + tail.start()
        between = clean[statement_end:at]
        if (f'goto {tail[1]};' in clean[parts[0]:statement_end] and not re.search(rf'\b{var}\b', between)
                and not re.search(r'\b(?:goto|return)\b|[{}]', between)):
            found.append((at, tail[1], parts[0], statement_end, 'after'))
    return found


def variants(source, name, _depth=0):
    span = find(source, name)
    if not span:
        return []
    clean = _blank(source)
    opening = clean.find('{', span[0], span[1])
    end = close(clean, opening, '{', '}') if opening >= 0 else None
    if not end:
        return []
    result = []
    firsts = []
    for hit in ASSIGN.finditer(clean, opening, end):
        var, value = hit['var'], hit['value']
        # the `if` may follow other simple statements that never mention V (no braces, labels or jumps)
        at = hit.end()
        parts = _statement(clean, at)
        while not parts:
            step = re.compile(rf'[ \t]*(?!if\b)(?!{IDENT}:)[^{{}};\n]*;[ \t]*\n').match(clean, at)
            if not step or re.search(rf'\b{var}\b|\b(?:goto|return)\b', step[0]):
                break
            at = step.end()
            parts = _statement(clean, at)
        if not parts:
            continue
        statement_end = parts[4]
        cond = clean[at:parts[0]]
        if re.search(rf'\b{var}\b', cond):
            continue  # read in the condition
        for label_at, label, goto_start, goto_end, kind in _joins(clean, var, parts, statement_end, end):
            gotos = [m.start() for m in re.finditer(rf'goto {label};', clean[goto_start:goto_end])]
            if (len(re.findall(rf'goto {label};', clean[opening:end])) != len(gotos)
                    or any(not _assigned_before_goto(clean, var, goto_start, goto_start + g) for g in gotos)):
                continue  # another jump to the label, or a goto that doesn't assign V first
            then = clean[goto_start:goto_end]
            if kind == 'arm' and any(not re.match(r'\s*=(?!=)', then[m.end():]) for m in re.finditer(rf'\b{var}\b', then)):
                continue  # the arm with the goto reads V
            indent = re.match(r'[ \t]*', clean[label_at:])[0]
            sunk = (source[:hit.start()] + source[hit.end():at] + source[at:label_at]
                    + indent + f'{var} = {value};\n' + source[label_at:])
            literal = _literal(source, clean, opening, end, value)
            children = [sunk]
            if literal is not None:
                lit = _uses(sunk.replace(f'{var} = {value};', f'{var} = {literal};', 1), value, literal)
                children.append(lit)
            children.append(_unsigned_stores(children[-1], name, var))
            for child in children:
                if child != source and (FAMILY, child) not in result:
                    result.append((FAMILY, child))
            firsts.append(children[0])
            break
    if _depth < 2:  # several constants: the next one's sink applied to each first sink
        for first in firsts:
            for _, child in variants(first, name, _depth + 1):
                if child != source and (FAMILY, child) not in result:
                    result.append((FAMILY, child))
    return result[:12]


def _literal(source, clean, opening, end, value):
    """The number a constant local stands for (`int c = 0xFF;`), or the number itself."""
    if re.fullmatch(NUMBER, value):
        return None
    decl = re.search(rf'(?m)^[ \t]*(?:int|s32|u32|u8|u16|s16)\s+{re.escape(value)}\s*=\s*({NUMBER})\s*;', clean[opening:end])
    return decl[1] if decl else None


def _uses(text, name, literal):
    """Every other read of the constant local written as its literal, once the early assignment is gone."""
    return re.sub(rf'(=\s*){re.escape(name)}(\s*;)', rf'\g<1>{literal}\2', text)


def _unsigned_stores(text, name, var):
    """`*((s8 *) (...)) = V;` or `= 0xFF;` (above 0x7F) typed `u8`: the compiler loads the constant as 255, not -1."""
    def fix(m):
        value = m['value']
        if value != var and not ((n := _int(value)) is not None and 0x7F < n <= 0xFF):
            return m[0]
        return m[0].replace('s8', 'u8', 1)
    return re.sub(rf'\*\s*\(\s*\(\s*s8\s*\*\s*\)[^;=]*\)\s*=\s*(?P<value>{NUMBER}|{IDENT})\s*;', fix, text)
