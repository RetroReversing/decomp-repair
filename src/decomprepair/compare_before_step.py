"""A loaded value stepped in place, with the test on the stepped value taken into a flag first.

    n = p->timer;                      n = p->timer;
    tick();                            tick();
    p->a = n - 1;                      done = n - 1 < LIMIT;
    p->b = n - 1;            ->        n--;
    if (n - 1 < LIMIT || ...)          p->a = n;
                                       p->b = n;
                                       if (done || ...)

m2c keeps the loaded value and repeats `n - 1` at every use, in a local of the load's own narrow type. The target has
`addiu $v0,$s0,-1; move $s0,$v0; slti $v0,$v0,LIMIT`: the compare reads the sum, the loaded local takes it, and the
stores read the local. On a 37-instruction N64 fade-out update (SN64 GCC 2.8.1 `-G0 -mips3 -O2`) the repeated form
scored 325, and the flag with the step in place was exact. Stepping first and testing the local, or keeping the local a
byte, was not enough (325 to 590): the narrow local is widened to `int` here, its first value cast to the old type, so
every `n - K` keeps the value it had.

Offered when the local is assigned once, every later mention of it is the same `n - K` or `n + K`, one of them is
compared with a constant inside an `if`, and no loop lies between. The exact judge decides.
"""
import re

from .integer_repair_support import _address_taken, edit, locals_for, view
from .pattern_repairs import close

FAMILY = 'compare_before_step'
FAMILIES = (FAMILY,)
_NUMBER = r'(?:0[xX][0-9a-fA-F]+|\d+)[uU]?'
_COMPARE = r'(?:<=|>=|==|!=|<(?![<=])|>(?![>=]))'
_NARROW = re.compile(r'(?:(?:un)?signed\s+)?(?:char|short)|[su](?:8|16)')
_WORD = re.compile(r'int|signed\s+int|unsigned\s+int|[su]32')
LIMIT = 2


def _in_if(clean, opening, at):
    """Whether `at` lies inside the parentheses of an `if` condition."""
    for hit in re.finditer(r'\bif\s*\(', clean[opening:at]):
        paren = opening + hit.end() - 1
        stop = close(clean, paren, '(', ')')
        if stop and stop > at:
            return True
    return False


def _statement_start(clean, opening, at):
    """Where the statement holding `at` begins, or None where a line can't be put before it."""
    start = max(clean.rfind(c, opening, at) for c in ';{}') + 1
    start = len(clean) - len(clean[start:].lstrip())
    return None if re.match(r'else\b|case\b|default\b', clean[start:]) else start


def _offer(source, part, decl):
    clean = part.clean
    local, kind = decl['name'], ' '.join(decl['type'].split())
    narrow = _NARROW.fullmatch(kind)
    if not (narrow or _WORD.fullmatch(kind)) or _address_taken(part.body, local):
        return None
    hits = [hit.start() for hit in re.finditer(rf'(?<![\w.>])\b{local}\b', clean[part.opening:part.end])]
    hits = [part.opening + at for at in hits]
    if len(hits) < 4:
        return None
    declared, assigned, uses = hits[0], hits[1], hits[2:]
    assignment = re.compile(rf'{local}\s*=(?!=)\s*(?P<value>[^;{{}}]+);').match(clean, assigned)
    if not assignment or clean[:assigned].rstrip()[-1:] not in ';{}' or any(at < assignment.end() for at in uses):
        return None
    pattern = re.compile(rf'{local}\s*(?P<op>[-+])\s*(?P<k>{_NUMBER})(?![\w.])')
    spans, found = [], set()
    for at in uses:
        hit = pattern.match(clean, at)
        if not hit:
            return None
        before = clean[:at].rstrip()
        after = clean[hit.end():].lstrip()
        if not (before.endswith(('(', ',', '=', ';', '{', '[', '?', ':')) or re.search(r'\breturn$', before)):
            return None
        if not (after.startswith((')', ';', ',', ']', '?', ':')) or re.match(_COMPARE, after)):
            return None
        spans.append((at, hit.end()))
        found.add((hit['op'], hit['k']))
    if len(found) != 1:
        return None
    op, k = found.pop()
    between = clean[assignment.end():spans[-1][1]]
    if re.search(r'\b(?:for|while|do|switch|goto)\b', between):
        return None
    depth = 0
    for char in between:
        depth += (char == '{') - (char == '}')
        if depth < 0:
            return None
    expression = rf'{local}\s*{re.escape(op)}\s*{k}'
    test = re.compile(rf'(?:\(\s*{expression}\s*\)|(?<![\w]){expression})\s*{_COMPARE}\s*-?{_NUMBER}(?![\w.])'
                      rf'(?=\s*(?:\)|&&|\|\|))')
    compare = next((hit for hit in test.finditer(clean, assignment.end(), part.end)
                    if clean[:hit.start()].rstrip().endswith(('(', '&&', '||')) and _in_if(clean, part.opening, hit.start())),
                   None)
    if not compare:
        return None
    rest = [(a, b) for a, b in spans if not compare.start() <= a < compare.end()]
    start = _statement_start(clean, part.opening, spans[0][0])
    # The step goes in the assignment's own block, so every later use runs after it.
    opened = clean[assignment.end():start].count('{') - clean[assignment.end():start].count('}') if start else 1
    flag = f'{local}_before'
    if not rest or start is None or opened or re.search(rf'\b{flag}\b', part.clean):
        return None
    amount = int(k.rstrip('uU'), 0)
    step = f'{local}{op}{op};' if amount == 1 else f'{local} {op}= {k};'
    indent = source[source.rfind('\n', 0, start) + 1:start]
    indent = indent if not indent.strip() else '    '
    taken = source[compare.start():compare.end()]
    changes = [(start, start, f'{flag} = {taken};\n{indent}{step}\n{indent}'),
               (compare.start(), compare.end(), flag)]
    changes += [(a, b, local) for a, b in rest]
    # Declarations: the flag beside the local; a narrow local is widened, its value still cut to the old type.
    begin = max(clean.rfind(c, part.opening, declared) for c in ';{}') + 1
    begin = len(clean) - len(clean[begin:].lstrip())
    stop = clean.find(';', declared) + 1
    if narrow:
        changes.append((begin, stop, f'int {local};\n    int {flag};'))
        value = assignment.start('value'), assignment.end('value')
        changes.append((value[0], value[1], f'({kind}) ({source[value[0]:value[1]]})'))
    else:
        changes.append((stop, stop, f'\n    int {flag};'))
    return edit(source, changes)


def variants(source, name):
    part = view(source, name)
    if not part:
        return []
    out = []
    for decl in locals_for(part):
        child = _offer(source, part, decl)
        if child:
            out.append((FAMILY, child))
        if len(out) >= LIMIT:
            break
    return out


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}
