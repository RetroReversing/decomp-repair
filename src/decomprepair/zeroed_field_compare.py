"""A zero test of a limit written as the comparison with the counter that was just cleared.

    obj->done = 0;                              obj->done = 0;
    obj->made = 0;                              obj->made = 0;
    if (obj->done >= limits[0] &&               if (obj->done >= limits[0] &&
        limits[1] == 0 && ...)                      (u8) obj->made >= limits[1] && ...)

A game that keeps one counter per kind clears them and then asks of each kind whether its counter has reached its
limit. The counter stored last is still known to be zero, so cse folds `made >= limit` into the bare test `limit == 0`,
and m2c writes that. The difference is what cse learns after it: from `limit == 0` it knows the limit is zero on the
fall-through and drops a later test of the same limit, where from `0 >= limit` it records no equivalence and the later
test stays (`bnel` on the register the first test loaded). A 195-instruction N64 chain spawner (SN GCC 2.8.1 `-G0
-mips3 -O2`) tested its second table byte twice; this edit gave 2591 -> 2371 and was needed for the match (the later
test cannot be spelled back into the code any other way found). That the equivalence record is the cause is a
hypothesis; the judge decides.

zeroed_field_compare
    After a run of `LVALUE = 0;` stores (with only `if (..) return;` guards between them and the test), a term
    `Y == 0`, `Y != 0` or `!Y` of an `if` condition, where Y is a load the C shows to be unsigned, becomes `X >= Y`
    (`X < Y`), X one of the cleared lvalues. Offered only when a term of that condition or of a neighbouring guard
    orders a cleared lvalue against something, which is the sign the others are counters too. X is zero there and Y is not negative, so
    the value of the condition is unchanged."""
import re

from .csource import _blank, find
from .pattern_repairs import close

FAMILY = 'zeroed_field_compare'
FAMILIES = (FAMILY,)
LIMIT = 4
IDENT = r'[A-Za-z_]\w*'
_FIELD = re.compile(r'M2C_FIELD\(\s*(?P<base>[^,()]+?)\s*,\s*(?P<type>[su](?:8|16|32))\s*\*\s*,\s*(?P<off>[^,()]+?)\s*\)')
_PLAIN = rf'{IDENT}(?:(?:->|\.){IDENT}|\[\w+\])+'
_STORE = re.compile(rf'\s*(?P<lvalue>M2C_FIELD\([^;=]*?\)|{_PLAIN})\s*=\s*0[Uu]?\s*;')
_RETURN_GUARD_BODY = re.compile(r'\s*(?:return\b[^;{}]*;|\{\s*return\b[^;{}]*;\s*\})')
_IF = re.compile(r'\s*if\s*\(')
_CASTS = r'(?:\(\s*[su](?:8|16|32)\s*\)\s*)?'
_ORDERED = r'(?<![<>=\-])(?:<=|>=|<|>)(?![<>=])'


def _read(lvalue):
    """How a cleared lvalue is read: an m2c field as an unsigned load of its own width."""
    found = _FIELD.fullmatch(lvalue)
    if not found:
        return lvalue
    width = found['type'][1:]
    kind = f'u{width}' if width != '32' else found['type']
    field = f'M2C_FIELD({found["base"]}, {kind} *, {found["off"]})'
    return f'(u8) {field}' if width == '8' else field


def _same_place(a, b):
    """Whether two spellings name one cell (an m2c field by base and offset, whatever its type)."""
    one, two = _FIELD.search(a), _FIELD.search(b)
    if one and two:
        return (one['base'], one['off']) == (two['base'], two['off'])
    return re.sub(rf'\s+|^{_CASTS}', '', a) == re.sub(rf'\s+|^{_CASTS}', '', b)


def _unsigned(operand, source):
    """Whether the C shows the loaded value cannot be negative."""
    if re.match(r'\(\s*u(?:8|16|32)\s*\)', operand):
        return True
    bare = re.sub(rf'^{_CASTS}', '', operand)
    if re.match(r'\(\s*s', operand):
        return False
    field = _FIELD.fullmatch(bare)
    if field:
        return field['type'].startswith('u')
    plain = re.fullmatch(_PLAIN, bare)
    if not plain:
        return False
    if bare.endswith(']'):
        array = re.escape(bare[:bare.index('[')].split('.')[-1].split('->')[-1])
        declared = re.findall(rf'(?<![\w])([A-Za-z_]\w*)\s+{array}\s*\[', source)
    else:
        member = re.escape(re.split(r'->|\.', bare)[-1])
        declared = re.findall(rf'(?<![\w])([A-Za-z_]\w*)\s+{member}\s*(?:\[[^\]]*\])?\s*;', source)
    return bool(declared) and all(kind in ('u8', 'u16', 'u32') for kind in declared)


def _terms(condition):
    """The terms of an `&&`/`||` chain with their offsets, split at its top level only."""
    depth, start, out = 0, 0, []
    for token in re.finditer(r'\(|\)|&&|\|\|', condition):
        if token[0] == '(':
            depth += 1
        elif token[0] == ')':
            depth -= 1
        elif depth == 0:
            out.append((start, token.start()))
            start = token.end()
    out.append((start, len(condition)))
    return out


def _stripped(text, start, end):
    """The span of a term without its surrounding blanks and brackets."""
    while True:
        while start < end and text[start].isspace():
            start += 1
        while end > start and text[end - 1].isspace():
            end -= 1
        if start < end and text[start] == '(' and close(text, start) == end:
            start, end = start + 1, end - 1
            continue
        return start, end


def _zero_test(term):
    """(operand, operator for `X op operand`) of `Y == 0`, `Y != 0` or `!Y`; or None."""
    found = re.fullmatch(r'(?s)(.+?)\s*(==|!=)\s*0[Uu]?', term)
    if found:
        return found[1], '>=' if found[2] == '==' else '<'
    found = re.fullmatch(r'(?s)!\s*(?!=)(.+)', term)
    return (found[1], '>=') if found else None


def _chains(clean, opening, end):
    """Every run of zero stores and the `if` conditions reached from it: [(cleared lvalues, condition start, end)]."""
    out, done = [], set()
    for first in _STORE.finditer(clean, opening, end):
        if first.start() in done or not re.search(r'[;{}]\s*\Z', clean[opening:first.start() + 1].rstrip(' \t\n') or '{'):
            continue
        cleared, at, chain = [], first.start(), []
        while True:
            store = _STORE.match(clean, at, end)
            if store:
                done.add(store.start())
                cleared.append(store['lvalue'])
                at = store.end()
                continue
            guard = _IF.match(clean, at, end)
            if not guard or not cleared:
                break
            stop = close(clean, guard.end() - 1)
            if not stop:
                break
            chain.append((list(cleared), guard.end(), stop - 1))
            body = _RETURN_GUARD_BODY.match(clean, stop, end)
            if not body or re.match(r'\s*else\b', clean[body.end():end]):
                break
            at = body.end()
        if chain:
            out.append(chain)
    return out


def variants(source, name):
    """Children: one zero test of a limit written as the comparison with a counter just cleared."""
    span = find(source, name)
    if not span:
        return []
    clean = _blank(source)
    opening = clean.find('{', span[0], span[1])
    end = close(clean, opening, '{', '}') if opening >= 0 else None
    if not end:
        return []
    out = []
    for chain in _chains(clean, opening + 1, end - 1):
        split = [(cleared, start, clean[start:stop], [_stripped(clean[start:stop], *part)
                  for part in _terms(clean[start:stop])]) for cleared, start, stop in chain]
        # the cleared lvalues some term of the chain already orders against a limit
        ordered = [x for cleared, _, condition, spans in split for a, b in spans
                   if re.search(_ORDERED, condition[a:b])
                   for x in cleared if any(_same_place(x, side.strip())
                                           for side in re.split(_ORDERED, condition[a:b]))]
        if not ordered:
            continue
        for cleared, start, condition, spans in split:
            fresh = [x for x in reversed(cleared) if x not in ordered] + [x for x in reversed(cleared) if x in ordered]
            for a, b in spans:
                test = _zero_test(condition[a:b])
                if not test:
                    continue
                operand, op = test[0].strip(), test[1]
                while operand.startswith('(') and close(operand, 0) == len(operand):
                    operand = operand[1:-1].strip()
                # a call before the test could change the counter
                before = re.sub(r'\bM2C_FIELD\b', '', condition[:b])
                if re.search(rf'(?<![\w]){IDENT}\s*\(', before) or not _unsigned(operand, clean):
                    continue
                if any(_same_place(x, operand) for x in cleared):
                    continue
                for counter in fresh:
                    child = source[:start + a] + f'{_read(counter)} {op} {operand}' + source[start + b:]
                    if (FAMILY, child) not in out:
                        out.append((FAMILY, child))
                    if len(out) >= LIMIT:
                        return out
    return out


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}
