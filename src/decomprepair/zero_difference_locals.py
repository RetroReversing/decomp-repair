"""The differences a condition tests against zero, each named in a local before the `if`.

m2c writes a test on a register that holds a subtraction as the subtraction inside the condition:
`if (((p[2] == x0) && ((p[3] - y0) == 0)) || (((p[4] - x0) == 0) && ((p[5] - y0) == 0)))`. The target computes every
difference ahead of the first branch (`subu; subu; ...; bne`), which a short-circuit condition cannot do: the later
loads and subtractions only happen on the path that reaches them. The game kept the differences in locals (a pair of
edge vectors) and tested those.

zero_difference_locals
    Every `(A - B) == 0` (or `!= 0`) of one `if` condition becomes `zdiffN = A - B;` before the `if`, in the order the
    condition reads them, and the test `zdiffN == 0`.
zero_difference_locals_all
    The same, and the condition's plain `A == B` tests are named as differences too (the compiler folds
    `(A - B) == 0` back to a compare of A with B, but the load order changes).
zero_difference_locals_wide
    Either of the above with the narrow (`s16`/`u16`/`s8`/`u8`) locals the differences read declared `s32`, where
    every assignment to them is a load of that narrow type, so the value is the same.

A 20-instruction N64 triangle test (SN GCC 2.8.1, `-G0 -mips3 -O2`) was 1175 from its machine draft with `s32`
temporaries and exact (0) with the three differences named; with the draft's `s16` temporaries naming them alone was
55 and widening them as well is the `_wide` child. Naming only the second pair of differences was 655.

A difference is hoisted only when it is certain to be the same program: both operands are integer loads, locals or
literals (never floats, where `a - b == 0` and `a == b` differ), the condition has no call, assignment or increment,
and every pointer read through is already read by a statement before the `if` or by the condition's first test, so no
load is made unconditional that a guard was protecting. The judge decides.
"""
import re
from functools import lru_cache

from .integer_repair_support import IDENT, INTEGER, NUMBER, edit, view
from .pattern_repairs import close

FAMILY = 'zero_difference_locals'
EVERY = 'zero_difference_locals_all'
WIDE = 'zero_difference_locals_wide'
FAMILIES = (FAMILY, EVERY, WIDE)
LIMIT = 12
NARROW = r'(?:s8|u8|s16|u16|signed\s+char|unsigned\s+char|unsigned\s+short|short)'
KNOWN_CALLS = {'M2C_FIELD', 'sizeof'}
POINTER_CAST = re.compile(rf'\(\s*(?:(?:struct|union|const|unsigned|signed)\s+)*{IDENT}\s*\*+\s*\)')
INTEGER_CAST = re.compile(rf'^\(\s*{INTEGER}\s*\)\s*')


def _outer(text):
    """`text` without whitespace and the parentheses around all of it."""
    text = text.strip()
    while text.startswith('(') and close(text, 0, '(', ')') == len(text):
        text = text[1:-1].strip()
    return text


def _flat(text):
    """`text` with everything inside brackets blanked, so what is left is its top level."""
    while True:
        blanked = re.sub(r'([(\[])([^()\[\]]*)([)\]])', lambda m: '\0' + ' ' * len(m[2]) + '\0', text)
        if blanked == text:
            return text.replace('->', '..')
        text = blanked


def _lines(name, context):
    """The lines of `context` that name `name`: a declaration is searched for in these, not in a whole large header."""
    found, at = [], context.find(name)
    for hit in re.finditer(rf'{name}(?![\w])', context):
        if hit.start() >= at:
            start, at = context.rfind('\n', 0, hit.start()) + 1, context.find('\n', hit.end())
            at = len(context) if at < 0 else at
            found.append(context[start:at])
    return '\n'.join(found)


@lru_cache(maxsize=256)
def _integer_declared(name, context):
    """Whether every declaration of `name` in `context` is a plain integer (not a pointer, float or record)."""
    declared = re.findall(rf'(?:^|[;{{}},(]|\b(?:unsigned|signed|const|static|extern))\s*({IDENT})((?:\s*\*)*)\s*'
                          rf'(?:{IDENT}\s*(?:\[[^\]\n]*\])?\s*,\s*)*(?<![\w.>]){name}\s*(?=[;,=)\[:])', _lines(name, context), re.M)
    declared = [(kind, stars) for kind, stars in declared if kind not in ('return', 'goto', 'case', 'else')]
    return bool(declared) and all(re.fullmatch(r'[su](?:8|16|32)|char|short|int|long|signed|unsigned', kind)
                                  and not stars for kind, stars in declared)


def _operand(text, context):
    """(the pointer names it reads through, the local it is) of an integer operand, or None when it is not surely one."""
    text = _outer(text)
    while INTEGER_CAST.match(text):
        text = _outer(INTEGER_CAST.sub('', text))
    if re.fullmatch(NUMBER, text):
        return set(), None
    if re.fullmatch(IDENT, text):
        return (set(), text) if _integer_declared(text, context) else None
    field = re.fullmatch(rf'M2C_FIELD\s*\(\s*({IDENT})\s*,\s*{INTEGER}\s*\*\s*,\s*-?{NUMBER}\s*\)', text)
    if field:
        return {field[1]}, None
    deref = re.fullmatch(rf'\*\s*\(\s*{INTEGER}\s*\*\s*\)\s*(.+)', text, re.S)
    if deref:
        inner = POINTER_CAST.sub('', _outer(deref[1]))
        base = re.fullmatch(rf'\(?\s*({IDENT})\s*\)?\s*(?:\+\s*{NUMBER})?', _outer(inner))
        return ({base[1]}, None) if base else None
    member = re.fullmatch(rf'(.+?)(?:->|\.)\s*({IDENT})', text, re.S)
    if member and _integer_declared(member[2], context):
        base = _outer(POINTER_CAST.sub('', _outer(member[1])))
        base = re.sub(r'\[\s*' + NUMBER + r'\s*\]$', '', base)
        return ({base}, None) if re.fullmatch(IDENT, base) else None
    return None


def _split(inner, operator):
    """The two sides of the only top-level `operator` of `inner`, or None."""
    flat = _flat(inner)
    if operator == '-':
        if re.search(r'&&|\|\||[<>=!?,&|^]|\+', flat):
            return None
        found = [m.start() for m in re.finditer(r'(?<=[\w\0\]])\s*-(?![-=])', flat)]
        found = [flat.index('-', at) for at in found]
    else:
        if re.search(r'&&|\|\||[?,]', flat) or len(re.findall(r'==|!=', flat)) != 1:
            return None
        found = [re.search(r'==|!=', flat).start()]
    if len(found) != 1:
        return None
    return inner[:found[0]], inner[found[0] + len(operator):]


def _tests(condition, context):
    """The tests of `condition`: (start, end, replacement start, left, right, sign, bases, locals, is a difference)."""
    found = []
    for opening in re.finditer(r'\(', condition):
        start = opening.start()
        past = close(condition, start, '(', ')')
        if past is None:
            return []
        end = past - 1
        inner = condition[start + 1:end]
        zero = re.match(r'\s*([=!]=)\s*0(?![\w.])', condition[end + 1:])
        if zero:
            sides = _split(_outer(inner), '-')
            if sides:
                parts = [_operand(side, context) for side in sides]
                if all(parts):
                    found.append((start, end + 1 + zero.end(), sides[0].strip(), sides[1].strip(), zero[1],
                                  parts[0][0] | parts[1][0], {parts[0][1], parts[1][1]} - {None}, True))
                    continue
        compare = re.search(r'==|!=', _flat(inner))
        if compare:
            sides = _split(inner, compare[0])
            if sides and not any(re.fullmatch(r'0|NULL', _outer(side)) for side in sides):
                parts = [_operand(side, context) for side in sides]
                if all(parts):
                    found.append((start, end + 1, sides[0].strip(), sides[1].strip(), compare[0],
                                  parts[0][0] | parts[1][0], {parts[0][1], parts[1][1]} - {None}, False))
    return found


def _pure(condition):
    """No call, assignment or increment: evaluating part of it early changes nothing."""
    if re.search(r'\+\+|--|(?<![=!<>])=(?!=)|<<=|>>=|\bvolatile\b', condition):
        return False
    called = set(re.findall(rf'\b({IDENT})\s*\(', condition)) - KNOWN_CALLS
    return not called and not re.search(r'[\])]\s*\((?=[^()]*,)', condition)


def _read_through(text, base):
    return bool(re.search(rf'M2C_FIELD\s*\(\s*{base}\s*,|(?<![\w.>]){base}\s*(?:->|\[)|'
                          rf'\*\s*\([^()]*\*\s*\)\s*\(*\s*{base}\b|\*\s*\)\s*{base}\s*\)\s*->|(?<![\w)\]])\s*\*\s*{base}\b',
                          text))


def _before(clean, opening, at):
    """The statements of the enclosing blocks that always run before offset `at`, nested blocks left out."""
    text = clean[opening + 1:at]
    while True:
        shorter = re.sub(r'\{[^{}]*\}', ';', text)
        if shorter == text:
            break
        text = shorter
    return ' '.join(piece for piece in re.split(r'[;{}]', text)
                    if not re.match(r'\s*(?:if|else|while|for|case|default|switch)\b', piece))


def _widen(source, clean, opening, end, names):
    """The edits that declare `s32` each narrow local in `names` that only ever holds a load of its own type."""
    edits = []
    body = clean[opening:end]
    for name in sorted(names):
        declared = re.search(rf'\b({NARROW})(\s+){name}\s*;', body)
        if not declared or re.search(rf'(?<![\w.>]){name}\s*(?:\+\+|--|[-+*/%&|^]=|<<=|>>=)|(?:\+\+|--)\s*{name}\b|'
                                     rf'(?<![&])&\s*{name}\b', body):
            continue
        kind = re.escape(declared[1])
        values = re.findall(rf'(?<![\w.>]){name}\s*=(?!=)\s*([^;]*);', body)
        if values and all(re.fullmatch(rf'(?:M2C_FIELD\s*\([^,]*,\s*{kind}\s*\*\s*,[^()]*\)|\*\s*\(\s*{kind}\s*\*\s*\)'
                                       r'.*)', value.strip(), re.S) for value in values):
            at = opening + declared.start(1)
            edits.append((at, at + len(declared[1]), 's32'))
    return edits


def variants(source, name, header=''):
    part = view(source, name)
    if not part or re.search(r'\b(?:volatile|asm|__asm__)\b', part.clean[part.opening:part.end]):
        return []
    clean, opening, end = part.clean, part.opening, part.end
    context = header + '\n' + clean
    taken = len(re.findall(r'\bzdiff\d+\b', clean))
    if taken:
        return []
    children = []
    for statement in re.finditer(r'\bif\s*\(', clean[opening:end]):
        at = opening + statement.start()
        start = opening + statement.end() - 1
        past = close(clean, start, '(', ')')
        if past is None or not clean[:at].rstrip().endswith((';', '{', '}')):
            continue
        condition = clean[start + 1:past - 1]
        if not _pure(condition):
            continue
        tests = _tests(condition, context)
        if not any(test[7] for test in tests):
            continue
        first = re.split(r'&&|\|\|', condition)[0]
        earlier = _before(clean, opening, at) + ' ; ' + first
        offset = start + 1
        for family, chosen in ((FAMILY, [test for test in tests if test[7]]), (EVERY, tests)):
            if family == EVERY and len(chosen) == sum(test[7] for test in tests):
                continue
            if not all(_read_through(earlier, base) for test in chosen for base in test[5]):
                continue
            indent = re.search(r'[ \t]*$', source[:at])[0]
            names = [f'zdiff{index}' for index in range(len(chosen))]
            sets = ''.join(f'{new} = {_term(source, offset, condition, test[2])} - '
                           f'{_term(source, offset, condition, test[3])};\n{indent}'
                           for new, test in zip(names, chosen))
            edits = [(opening + 1, opening + 1, ''.join(f'\n    s32 {new};' for new in names)), (at, at, sets)]
            edits += [(offset + test[0], offset + test[1], f'({new} {test[4]} 0)') for new, test in zip(names, chosen)]
            children.append((family, edit(source, edits)))
            wider = _widen(source, clean, opening, end, set().union(*(test[6] for test in chosen)))
            if wider:
                children.append((WIDE, edit(source, edits + wider)))
        if len(children) >= LIMIT:
            break
    return children[:LIMIT]


def _term(source, offset, condition, side):
    """`side` as the source spells it (comments and literals kept), in parentheses when it is itself an expression."""
    at = offset + condition.index(side)
    text = source[at:at + len(side)]
    return f'({text})' if re.search(r'[-+]', _flat(text)) and not text.startswith('*') else text


REPAIR = {
    'families': FAMILIES,
    'variants': variants,
    'needs': ('source', 'name', 'header'),
}
