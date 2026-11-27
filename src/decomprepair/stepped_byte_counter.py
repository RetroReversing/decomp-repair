"""A word counter stepped by one and tested under a byte (or halfword) mask: declare the counter narrow, together.

m2c has no type for a counter that arrives in a register, so a `u8 n; ... if ((u8) --n == 0xFF) break;` comes back as
two word values and a mask:

    s32 v, t;                            u8 v;
    v = arg3;                    ->      v = arg3;
    for (;;) {                           for (;;) {
        t = v - 1;                           if (--v == 0xFF) break;
        v = t;
        if ((t & 0xFF) != 0xFF) ...

With word locals cse reads the test's `t` back as `v`, so the target's `addiu $v0,$a3,-1; move $a3,$v0;
andi $v0,$v0,0xff` comes out as `andi $v0,$a3,0xff`. Narrowing `v` alone or `t` alone, or folding `t` away with `v` still
a word, each scored worse than the draft on a 26-instruction N64 bit reader (sn-n64-281 -O2: 5 -> 105, 110, 110); the
two narrowed together, or the step folded into a narrow counter, were exact. `local_width_group` needs a cast on every
member and reads no `& 0xFF`, so neither was offered.

`stepped_byte_counter_fold` folds the step into the test on the narrow counter; `stepped_byte_counter_pair` keeps the
two statements and narrows the temporary with the counter; `stepped_byte_counter_test` narrows a counter whose step is
already one statement or part of the test. A counter that is a parameter is stepped through a narrow local copy of it.
Each is offered on the function with its `do { } while (0)` fences opened and, where that differs, also with its
scaffolding stripped (`scaffold_strip.plain`), since the search's fences around the step hide it. The exact judge decides.
"""
import re

from . import scaffold_strip
from .csource import _blank, find
from .pattern_repairs import close

FOLD = 'stepped_byte_counter_fold'
PAIR = 'stepped_byte_counter_pair'
TEST = 'stepped_byte_counter_test'
FAMILIES = (FOLD, PAIR, TEST)
LIMIT = 8

IDENT = r'[A-Za-z_]\w*'
_WORD = r'(?:s32|u32|int|unsigned\s+int|signed\s+int|long|unsigned\s+long)'
_MASKS = {0xFF: 'u8', 0xFFFF: 'u16'}
_BLOCK = re.compile(rf'(?<=[;{{}}])(\s*)\{{\s*({IDENT}\s*=(?!=)[^{{}};]*;)\s*\}}')
_PAIR = re.compile(rf'(?<![\w.>])(?P<temp>{IDENT})\s*=\s*(?P<value>{IDENT})\s*(?P<op>[-+])\s*1\s*;\s*'
                   rf'(?P=value)\s*=\s*(?P=temp)\s*;(?P<gap>\s*)(?=if\s*\()')
_SELF = re.compile(rf'(?<![\w.>])(?:(?P<a>{IDENT})\s*(?:\+\+|--)|(?:\+\+|--)\s*(?P<b>{IDENT})|'
                   rf'(?P<c>{IDENT})\s*=\s*(?P=c)\s*[-+]\s*1|(?P<d>{IDENT})\s*[-+]=\s*1)\s*;\s*(?=if\s*\()')


def _flat(source, name):
    """The function's single assignments taken out of the bare blocks opened fences leave."""
    for _ in range(16):
        span = find(source, name)
        if not span:
            return source
        clean = _blank(source)
        hit = next((m for m in _BLOCK.finditer(clean, *span)), None)
        if not hit:
            return source
        source = source[:hit.start()] + hit[1] + source[hit.start(2):hit.end(2)] + source[hit.end():]
    return source


def _masked(operand):
    """Every spelling of `operand` under a byte or halfword mask or cast; `kind` or `mask` says which width."""
    return re.compile(rf'(?:\(\s*(?P<kind>u8|u16|s8|s16)\s*\)\s*(?:\(\s*{operand}\s*\)|{operand}(?!\w))|'
                      rf'(?:\(\s*{operand}\s*\)|(?<![\w.>]){operand}(?!\w))\s*&\s*(?P<mask>0[xX][0-9A-Fa-f]+|\d+)[uU]?)')


def _width(hit):
    return hit['kind'] or _MASKS.get(int(hit['mask'], 0))


def _condition(clean, at):
    """The (start, end) inside the parentheses of the `if` at `at`."""
    paren = clean.find('(', at)
    end = close(clean, paren, '(', ')') if paren >= 0 else None
    return (paren + 1, end - 1) if end else None


def _body(source, name):
    span = find(source, name)
    if not span:
        return None
    clean = _blank(source)
    opening = clean.find('{', *span)
    return (clean, span, opening) if opening >= 0 and '#' not in clean[opening:span[1]] else None


def _declared(clean, opening, end, var):
    """The one `word var;` declaration of a local, or None."""
    found = list(re.finditer(rf'(?<=[;{{}}])\s*(?P<type>{_WORD})\s+{var}\s*;', clean[:end]))
    found = [hit for hit in found if hit.start() >= opening]
    return found[0] if len(found) == 1 else None


def _narrow(source, name, var, kind):
    """`source` with the counter `var` narrow: its declaration retyped, or a parameter stepped through a narrow copy.
    Returns (source, the counter's name from here on), or None."""
    part = _body(source, name)
    if not part:
        return None
    clean, span, opening = part
    if re.search(rf'(?<![&\w])&\s*{var}\b', clean[opening:span[1]]):
        return None
    local = _declared(clean, opening, span[1], var)
    if local:
        return source[:local.start('type')] + kind + source[local.end('type'):], var
    if not re.search(rf'[(,]\s*{_WORD}\s+{var}\s*(?=[,)])', clean[span[0]:opening]):
        return None
    copy = f'{var}_{kind}'
    if re.search(rf'\b{copy}\b', clean):
        return None
    body = source[opening + 1:span[1]]
    uses = list(re.finditer(rf'(?<![\w.>])(?<!->){var}\b', clean[opening + 1:span[1]]))
    for hit in reversed(uses):
        body = body[:hit.start()] + copy + body[hit.end():]
    return source[:opening + 1] + f'\n    {kind} {copy} = {var};' + body + source[span[1]:], copy


def _pairs(source, name):
    """`t = v - 1; v = t; if (.. (t & 0xFF) ..)` written as the narrow counter."""
    part = _body(source, name)
    if not part:
        return
    clean, span, opening = part
    for hit in _PAIR.finditer(clean, opening, span[1]):
        temp, value, op = hit['temp'], hit['value'], hit['op']
        where = _condition(clean, hit.end())
        if temp == value or not where:
            continue
        tests = list(_masked(temp).finditer(clean, *where))
        declared = _declared(clean, opening, span[1], temp)
        if len(tests) != 1 or not declared or not _width(tests[0]):
            continue
        test, kind = tests[0], _width(tests[0])
        # the declaration, the step's two names and the test: any other use needs the temporary as it is
        if len(re.findall(rf'(?<![\w.>]){temp}\b', clean[opening:span[1]])) != 4:
            continue
        # fold: the step moves into the test
        text = source[:hit.start()] + source[hit.start('gap') + len(hit['gap']):test.start()]
        text += f'{op}{op}{value}' + source[test.end():]
        text = text[:declared.start()] + text[declared.end():]
        narrowed = _narrow(text, name, value, kind)
        if narrowed:
            yield FOLD, narrowed[0]
        # pair: both statements stay, both values narrow
        text = source[:test.start()] + temp + source[test.end():]
        text = text[:declared.start('type')] + kind + text[declared.end('type'):]
        narrowed = _narrow(text, name, value, kind)
        if narrowed:
            yield PAIR, narrowed[0]


def _tests(source, name):
    """A counter stepped inside the masked test, or by the statement before it."""
    part = _body(source, name)
    if not part:
        return
    clean, span, opening = part
    found = []  # (counter, the test's match)
    for guard in re.finditer(r'\bif\s*\(', clean[opening:span[1]]):
        where = _condition(clean, opening + guard.start())
        if not where:
            continue
        for hit in _masked(rf'(?:\+\+|--)\s*{IDENT}').finditer(clean, *where):
            found.append((re.search(rf'(?:\+\+|--)\s*({IDENT})', hit[0])[1], hit))
    for step in _SELF.finditer(clean, opening, span[1]):
        var = step['a'] or step['b'] or step['c'] or step['d']
        where = _condition(clean, step.end())
        hit = where and _masked(var).search(clean, *where)
        if hit:
            found.append((var, hit))
    for var, hit in found:
        kind = _width(hit)
        if not kind:
            continue
        inner = re.search(rf'(?:\+\+|--)?\s*{var}', source[hit.start():hit.end()])[0].strip()
        text = source[:hit.start()] + inner + source[hit.end():]
        narrowed = _narrow(text, name, var, kind)
        if narrowed:
            yield TEST, narrowed[0]


def variants(source, name, header=''):
    bases = []
    opened = _flat(scaffold_strip.unfence(source, name) or source, name)
    bases.append(opened)
    plain = scaffold_strip.plain(source, name, header)
    if plain:
        bases.append(_flat(plain, name))
    out, seen = [], {source}
    for base in dict.fromkeys(bases):
        for family, text in (*_pairs(base, name), *_tests(base, name)):
            if text not in seen:
                seen.add(text)
                out.append((family, text))
    return out[:LIMIT]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'header'), 'order': 70}  # the registry
