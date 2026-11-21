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
    """(then_start, then_end, else_start, else_end) of the `if (...) {..} else {..}` starting at `at`, else None."""
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
        return None
    else_start = m.end() - 1
    else_end = close(clean, else_start, '{', '}')
    return (then_start, then_end, else_start, else_end) if else_end else None


def variants(source, name):
    span = find(source, name)
    if not span:
        return []
    clean = _blank(source)
    opening = clean.find('{', span[0], span[1])
    end = close(clean, opening, '{', '}') if opening >= 0 else None
    if not end:
        return []
    result = []
    for hit in ASSIGN.finditer(clean, opening, end):
        var, value = hit['var'], hit['value']
        parts = _statement(clean, hit.end())
        if not parts:
            continue
        then_start, then_end, else_start, else_end = parts
        stop = else_end
        if re.search(rf'\b{var}\b', clean[hit.end():then_start]) or re.search(rf'\b{var}\b', clean[stop:end]):
            continue  # read in the condition, or after the join
        then = clean[then_start:then_end]
        if any(not re.match(r'\s*=(?!=)', then[m.end():]) for m in re.finditer(rf'\b{var}\b', then)):
            continue  # the then-branch reads it
        label = re.search(rf'(?m)^[ \t]*({IDENT}):', clean[else_start:else_end])
        if not label or f'goto {label[1]};' not in then:
            continue
        label_at = else_start + label.start()
        if re.search(rf'\b{var}\b', clean[else_start:label_at]):
            continue
        indent = re.match(r'[ \t]*', clean[label_at:])[0]
        sunk = source[:hit.start()] + source[hit.end():label_at] + indent + f'{var} = {value};\n' + source[label_at:]
        if sunk == source:
            continue
        children = [sunk]
        literal = _literal(source, clean, opening, end, value)
        if literal is not None:
            children.append(sunk.replace(f'{var} = {value};', f'{var} = {literal};', 1))
            children[-1] = _uses(children[-1], value, literal)
        children.append(_unsigned_stores(children[-1], name, var))
        for child in children:
            if child != source and (FAMILY, child) not in result:
                result.append((FAMILY, child))
        break
    return result


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
