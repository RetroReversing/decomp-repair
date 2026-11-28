"""A run of field updates staged through two scratch locals that take turns.

m2c writes `p->count += 1; p->angle += 0x7A; ...` back as one expression per field. Every such update makes registers set
once, which the first scheduler boosts (`birthing_insn_p`), so it pulls the next statements' loads further up than the
target has them. Written `a = p->count; a += 1; p->count = a; b = p->angle; b += 0x7A; p->angle = b; ...`, each local has
several sets: the loads stay one statement ahead and the two locals take two registers in turn. A particle update
(SN64 GCC 2.8.1, `-O2 -G0 -mips3`, 28 instructions) went from 990 to 105 with this alone, after 26 recorded attempts.

Its last rows needed the end of the run written with the compare that follows it: `a = p->b; b = p->r; p->b = a - 6;
do { b = b < 8; } while (0); if (b)`, where `r` was updated earlier in the run. `r` is read again from memory (its local
was set again), the second local holds the value and then the flag, and the loop notes keep the flag's compare from
being replaced by a new register (105 -> 170 with the read, 0 with the compare in the loop). That the notes are what
stops the replacement is a hypothesis from those scores; no compiler source of this build is public.

alternating_rmw_locals
    Three or more consecutive lines that each update one memory lvalue by a literal (`L = (T) (L + K);`, `L += K;`,
    `L++;`; `+ - | & ^`) become staged updates through a new `s32` and a new `u32`, taking turns; one child alternates to
    the end, one keeps the first local for the last update too. When an `if (R < K)` on an unsigned read of a field the
    run updated earlier follows, one more child writes the end as above. Only lvalues whose text shows an integer type
    (`M2C_FIELD(p, u8 *, K)`, `*(s32 *)...`) are staged; the same lvalue twice in a row ends a run."""
import re

from .csource import _blank, find

FAMILY = 'alternating_rmw_locals'
FAMILIES = (FAMILY,)
MIN_RUN = 3
_NUM = r'(?:0[xX][0-9A-Fa-f]+|\d+)[uUlL]*'
_CAST = r'(?:\(\s*(?:signed\s+|unsigned\s+)?[A-Za-z_]\w*\s*\)\s*)'
_TYPED = re.compile(r'(?:M2C_FIELD\s*\([^,;=]+,\s*|\*\s*\(\s*(?:\(\s*)?)(?P<type>[su](?:8|16|32))\s*\*(?!\s*\*)')
_LINE = re.compile(r'(?m)^(?P<indent>[ \t]+)(?P<body>[^\n;{}]+);[ \t]*$')
_ASSIGN = re.compile(r'(?P<lhs>[^=]+?)\s*(?P<op>[-+|&^])?=(?!=)\s*(?P<rhs>.+)\Z')
_STEP = re.compile(r'(?:(?P<pre>\+\+|--)\s*(?P<a>.+)|(?P<b>.+?)\s*(?P<post>\+\+|--))\Z')


def _group(text):
    """`text` without parentheses that wrap all of it."""
    text = text.strip()
    while text.startswith('(') and text.endswith(')'):
        depth = 0
        for at, char in enumerate(text):
            depth += (char == '(') - (char == ')')
            if not depth and at < len(text) - 1:
                return text
        text = text[1:-1].strip()
    return text


def _uncast(text):
    """`text` without the casts in front of it: `(u8) (X)` -> `X`."""
    text = _group(text)
    while True:
        found = re.match(_CAST, text)
        if not found or not text[found.end():] or text[found.end()] in '+-*&':
            return text
        text = _group(text[found.end():])


def _memory(lvalue):
    """True for a memory lvalue whose integer type its own text shows: a float or pointer field staged through an
    integer local would be another program, so a field known only by name is left alone."""
    return bool(_TYPED.match(lvalue))


def _update(body):
    """(lvalue, operator, literal) of a statement that updates one memory lvalue by a literal, else None."""
    body = body.strip()
    step = _STEP.match(body)
    if step:
        lvalue = (step['a'] or step['b']).strip()
        return (lvalue, (step['pre'] or step['post'])[0], '1') if _memory(lvalue) else None
    found = _ASSIGN.match(body)
    if not found or not _memory(found['lhs'].strip()):
        return None
    lvalue, rhs = found['lhs'].strip(), found['rhs'].strip()
    if found['op']:
        return (lvalue, found['op'], rhs) if re.fullmatch(_NUM, rhs) else None
    tail = re.match(rf'(?P<read>.+?)\s*(?P<op>[-+|&^])\s*(?P<k>{_NUM})\Z', _uncast(rhs))
    if not tail or _uncast(tail['read']) != lvalue:
        return None
    return lvalue, tail['op'], tail['k']


def _runs(source, clean, start, end):
    """Lists of (line match, update) for consecutive update lines of the function."""
    run, last = [], None
    for line in _LINE.finditer(clean, start, end):
        real = source[line.start('body'):line.end('body')]
        update = _update(real)
        joined = last is not None and not clean[last:line.start()].strip()
        if update and run and joined and update[0] != run[-1][1][0]:
            run.append((line, update))
        else:
            if len(run) >= MIN_RUN:
                yield run
            run = [(line, update)] if update else []
        last = line.end()
    if len(run) >= MIN_RUN:
        yield run


def _staged(local, update):
    lvalue, op, k = update
    return f'{local} = {lvalue}; {local} {op}= {k}; {lvalue} = {local};'


def _unsigned_read(read, lvalue):
    """True when `read` (a compare's left side) is the field `lvalue`, itself an unsigned byte or halfword."""
    return _uncast(read) == lvalue and _TYPED.match(lvalue)['type'] in ('u8', 'u16')


def _compare(source, clean, at, updates):
    """(start, end, field, literal) of an `if (R < K)` right after the run on a field updated before its last line."""
    found = re.compile(r'\s*if\s*\(').match(clean, at)
    if not found:
        return None
    depth, close = 1, found.end()
    while close < len(clean) and depth:
        depth += (clean[close] == '(') - (clean[close] == ')')
        close += 1
    condition = source[found.end():close - 1]
    parts = re.match(rf'(?P<read>.+?)\s*<\s*(?P<k>{_NUM})\Z', condition.strip(), re.S)
    if not parts or '&&' in condition or '||' in condition:
        return None
    for lvalue, _, _ in updates[:-1]:
        if lvalue != updates[-1][0] and _unsigned_read(parts['read'], lvalue):
            return found.end(), close - 1, lvalue, parts['k']
    return None


def variants(source, name):
    """[(family, source)]: each run of updates staged through two locals."""
    span = find(source, name)
    if span is None or re.search(r'\brmw_(?:first|second)\b', source):
        return []
    clean = _blank(source)
    opening = clean.find('{', *span)
    if opening < 0:
        return []
    locals_ = ('rmw_first', 'rmw_second')
    declared = '\n    s32 rmw_first;\n    u32 rmw_second;'
    out = []
    for run in _runs(source, clean, opening + 1, span[1]):
        updates = [update for _, update in run]
        start, end, indent = run[0][0].start(), run[-1][0].end(), run[0][0]['indent']
        taking_turns = [locals_[i % 2] for i in range(len(updates))]

        def build(lines, rest=source[end:], start=start):
            return source[:opening + 1] + declared + source[opening + 1:start] + '\n'.join(lines) + rest

        for names in (taking_turns, taking_turns[:-1] + [locals_[0]]):
            child = build([indent + _staged(local, update) for local, update in zip(names, updates)])
            if (FAMILY, child) not in out:
                out.append((FAMILY, child))
        compare = _compare(source, clean, end, updates)
        if compare:
            begin, stop, field, limit = compare
            lvalue, op, k = updates[-1]
            lines = [indent + _staged(local, update) for local, update in zip(taking_turns[:-1], updates[:-1])]
            lines.append(f'{indent}rmw_first = {lvalue}; rmw_second = {field}; {lvalue} = rmw_first {op} {k};\n'
                         f'{indent}do {{ rmw_second = rmw_second < {limit}; }} while (0);')
            out.append((FAMILY, build(lines, source[end:begin] + 'rmw_second' + source[stop:])))
    return out


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'archs': ('mips',)}
