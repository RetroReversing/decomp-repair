"""A store m2c made once after an `if`/`else` chain, from variables each arm set, written in every arm with the arms' own variables.

m2c merges what several arms have in common into the statement after them. A menu routine picks a sound record in
three arms (one `if`, an `else` holding a nested `if`/`else`), each arm setting the record pointer, a value and a byte,
and stores the combination once after the chain:

    if (idx != 0) {
        sound = menu->rec;  var_v0 = table[idx];  var_a0 = state->level;
    } else {
        if (flags & 0x80) { sound = menu->rec;  var_v0 = D_A; } else { sound = menu->rec;  var_v0 = D_B; }
        var_a0 = sound->level;
    }
    sound->word = (var_v0 & ~0xFF) | var_a0;

The game's code had the store in each arm; gcc 2.7's jump pass merges the identical tails again after register
allocation. With the shared variables the pseudos span several blocks and `global.c` allocates them by priority, after
`local-alloc.c` gave the tail's own temporaries (the mask `li`, the `and`) the first registers: the value ended in `$a0`
with the mask in `$v0` where the game has the value in `$v0` and the mask in `$v1`, and every later register of the
block shifted with it (24 rows on a 578-instruction menu function, 610 -> 545 for the first chain, 545 -> 505 for a
second one whose tail was an identical-arm `if (g) { S } else { S }`). Once each arm's variables are its own they live
in one basic block, `local-alloc.c` allocates them (a result ties to the input that dies there) and the tails merge
after allocation (hypotheses: what the sources show is the allocation that follows, not a statement about jump.c).

Offered only when the meaning is unchanged: the statement after the chain is one assignment (or an `if (c) { S } else
{ S }` of one identical assignment, written once); every variable it or an arm's trailing statements read that the arms
set is a local of the function declared once, assigned by a plain statement before any read in every leaf, is
mentioned nowhere else in the chain (its conditions, the arms' other statements) and nowhere after the store. The arms'
trailing statements (the byte read after a nested `if`/`else` above) go into every leaf of that arm, ahead of the
store; the variables are renamed in each leaf (`name_1`, `name_2`, ..., declared at the top of the leaf block).

`variants` gives, labelled `store_tail_into_arms`, one child per such chain.
"""
import re

from .case_temporary_repairs import DECLARATION, _identifiers, _mentions
from .csource import _blank, find
from .pattern_repairs import close

FAMILY = 'store_tail_into_arms'
FAMILIES = (FAMILY,)
LIMIT = 8
ID = r'[A-Za-z_]\w*'
ASSIGN = re.compile(r'[ \t]*[^;={}\n()]*(?:\([^;{}]*\))?[^;={}\n]*?=(?!=)[^;{}]+;')


def _skip(text, k):
    while k < len(text) and text[k].isspace():
        k += 1
    return k


def _parse_if(clean, at):
    """(then_open, then_close, else_open, else_close) of a braced `if (c) { } else { }` at `at`, or None."""
    m = re.compile(r'if\s*\(').match(clean, at)
    if not m:
        return None
    cond_end = close(clean, m.end() - 1, '(', ')')
    if not cond_end:
        return None
    then_open = _skip(clean, cond_end)
    if clean[then_open:then_open + 1] != '{':
        return None
    then_close = close(clean, then_open, '{', '}')
    if not then_close:
        return None
    then_close -= 1  # (the brace itself: `close` answers the position after it)
    k = _skip(clean, then_close + 1)
    if not re.compile(r'else\b').match(clean, k):
        return None
    else_open = _skip(clean, k + 4)
    if clean[else_open:else_open + 1] != '{':
        return None
    else_close = close(clean, else_open, '{', '}')
    if not else_close:
        return None
    return then_open, then_close, else_open, else_close - 1


def _statements(clean, lo, hi):
    """[(start, end)] of the top-level statements between two braces; a braced `if`/`else` is one statement."""
    out, k = [], lo
    while True:
        k = _skip(clean, k)
        if k >= hi:
            return out
        start = k
        parsed = _parse_if(clean, k) if re.compile(r'if\s*\(').match(clean, k) else None
        if parsed:
            k = parsed[3] + 1
        else:
            while k < hi and clean[k] not in ';{':
                k += 1
            if k < hi and clean[k] == '{':
                end = close(clean, k, '{', '}')
                if not end:
                    return None
                k = end
            else:
                k += 1
        out.append((start, k))


def _leaves(clean, lo, hi, tail):
    """The leaf blocks under an arm whose interior is `lo`..`hi`: [(lo, hi, tail spans)]; the tail is the statements
    that run after the leaf inside the enclosing arms, innermost first."""
    statements = _statements(clean, lo, hi)
    if statements is None:
        return None
    for number, (a, b) in enumerate(statements):
        parsed = _parse_if(clean, a) if re.compile(r'if\s*\(').match(clean, a) else None
        if parsed and parsed[3] + 1 == b:
            now = statements[number + 1:] + tail
            out = []
            for o, c in ((parsed[0], parsed[1]), (parsed[2], parsed[3])):
                sub = _leaves(clean, o + 1, c, now)
                if sub is None:
                    return None
                out += sub
            return out
    return [(lo, hi, tail)]


def _tail_statement(clean, at, end):
    """(start, end, text to write in every arm) of the one assignment at `at`, or of an `if` of two identical ones."""
    if re.compile(r'if\s*\(').match(clean, at):
        parsed = _parse_if(clean, at)
        if not parsed:
            return None
        then_open, then_close, else_open, else_close = parsed
        a, b = clean[then_open + 1:then_close].strip(), clean[else_open + 1:else_close].strip()
        if a and re.sub(r'\s+', '', a) == re.sub(r'\s+', '', b) and ASSIGN.fullmatch(a) and a.count(';') == 1:
            return at, else_close + 1, a
        return None
    if re.compile(r'(?:return|while|for|do|switch|goto|break|continue)\b').match(clean, at):
        return None
    m = ASSIGN.match(clean, at)
    if m and m.group().count(';') == 1:
        return at, m.end(), m.group().strip()
    return None


def _declaration(kind, name):
    kind = re.sub(r'\bregister\s+', '', kind).strip()
    return f"{kind}{'' if kind.endswith('*') else ' '}{name};"


def _build(source, clean, declared, taken, chain, tail, end, pointers=True):
    at, then_open, then_close, else_open, else_close = chain
    tail_start, tail_end, tail_text = tail
    leaves = []
    for o, c in ((then_open, then_close), (else_open, else_close)):
        sub = _leaves(clean, o + 1, c, [])
        if sub is None:
            return None
        leaves += sub
    suffixes = {span for _, _, extra in leaves for span in extra}
    texts = {}
    for k, (lo, hi, extra) in enumerate(leaves):
        texts[k] = clean[lo:hi] + ''.join('\n' + clean[a:b] for a, b in extra) + '\n' + tail_text
    mentioned = set(re.findall(ID, tail_text))
    for a, b in suffixes:
        mentioned |= set(re.findall(ID, clean[a:b]))
    private = []
    for var in sorted(mentioned & set(declared)):
        decl = declared[var]
        if 'volatile' in decl['type'] or (not pointers and '*' in decl['type']):
            continue
        pattern = _mentions(var)
        if pattern.search(clean, tail_end, end) or re.search(r'&\s*' + re.escape(var) + r'\b', clean[at:tail_end]):
            continue
        inside = sum(len(pattern.findall(clean[lo:hi])) for lo, hi, _ in leaves)
        inside += sum(len(pattern.findall(clean[a:b])) for a, b in suffixes) + len(pattern.findall(clean[tail_start:tail_end]))
        if len(pattern.findall(clean[at:tail_end])) != inside:
            continue  # (named in a condition or another statement of the chain)
        ok = True
        for k in texts:
            first = pattern.search(texts[k])
            if not first or not re.match(r'\s*=(?!=)', texts[k][first.end():]) \
                    or not re.search(r'(?:^|[;{}])\s*$', texts[k][:first.start()]):
                ok = False
                break
        if ok:
            private.append(var)
    plain = re.match(rf'\s*({ID})\s*=(?!=)', tail_text)
    reads = set(re.findall(ID, tail_text[plain.end():] if plain else tail_text))
    if not private or not (set(private) & reads):
        return None  # (the store reads none of what the arms would own: the copy changes nothing the allocator sees)
    cuts = [(tail_start, tail_end, '')] + [(a, b, '') for a, b in suffixes]
    for k, (lo, hi, extra) in enumerate(leaves, 1):
        names = {}
        for var in private:
            fresh = f'{var}_{k}'
            while fresh in taken:
                fresh += '_'
            taken.add(fresh)
            names[var] = fresh
        close_indent = re.match(r'[ \t]*', source[source.rfind('\n', 0, hi) + 1:]).group()
        indent = close_indent + '  '
        body = source[lo:hi].rstrip() + ''.join('\n' + indent + source[a:b].strip() for a, b in extra)
        body += '\n' + indent + tail_text
        for var, fresh in names.items():
            body = re.sub(r'(?<![\w.])(?<!->)' + re.escape(var) + r'\b', fresh, body)
        decls = ''.join(f"\n{indent}{_declaration(declared[v]['type'], names[v])}" for v in private)
        cuts.append((lo, hi, decls + body + '\n' + close_indent))
    result = source
    for a, b, new in sorted(cuts, reverse=True):
        result = result[:a] + new + result[b:]
    return re.sub(r'\n[ \t]*\n(\s*\})', r'\n\1', result)


def variants(source, name):
    span = find(source, name)
    if not span:
        return []
    clean = _blank(source)
    opening = clean.find('{', span[0], span[1])
    end = close(clean, opening, '{', '}') if opening >= 0 else None
    if not end:
        return []
    taken = _identifiers(source)
    out = []
    for hit in re.finditer(r'\bif\s*\(', clean[opening:end]):
        at = opening + hit.start()
        parsed = _parse_if(clean, at)
        if not parsed:
            continue
        tail = _tail_statement(clean, _skip(clean, parsed[3] + 1), end)
        if not tail:
            continue
        declared = {}  # the locals declared in a block that still encloses the chain
        for m in DECLARATION.finditer(clean, opening + 1, at):
            between = clean[m.end():at]
            if between.count('}') <= between.count('{') and m['name'] not in declared:
                declared[m['name']] = m
            elif between.count('}') <= between.count('{'):
                declared[m['name']] = None  # (declared twice: leave it alone)
        declared = {k: v for k, v in declared.items() if v}
        for pointers in (False, True):  # (the values alone first: a record pointer the arms share keeps its one register)
            child = _build(source, clean, declared, set(taken), (at,) + parsed, tail, end, pointers)
            if child and child != source and all(child != t for _, t in out):
                out.append((FAMILY, child))
        if len(out) >= LIMIT:
            break
    return out


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'order': 43}
