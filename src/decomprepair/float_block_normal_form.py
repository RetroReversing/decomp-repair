"""A run of float assignments in m2c's spelling, written the way the game's source had them, as one child.

m2c (and the permuter's scaffolding after it) writes a straight-line run of float arithmetic with every value
stored in a reused local, edited in place, and fenced:

    a = <load> + o;   c = <load>;   b = <load> + o;   ...   a += c;   v += d;   b -= c;
    do { v = <load>; } while (0);    if (g) { v = <load>; } else { v = <load>; }     (an identical-arm guard)

GCC 2.7.2 (KMC) gives such a run its registers in two passes: the local allocator (local-alloc.c: a pseudo that is
born and dies in one basic block, lowest free register first, in the order of floor_log2(refs) * refs / live length)
and the global allocator (the rest). Which values are one pseudo and which are two decides that order, so a name
reused for two values, an in-place `x += y`, and the fences that weigh a value by loop depth all move registers.
A bounding-box clamp (a scissor rectangle clipped to another one, KMC GCC 2.7.2, 96 instructions) stood at 120 with
only register rows left, and no repair family improved it. What closed it (120 -> 0) was the whole normal form at
once, each part no better alone (the fences removed alone: 2200; the folds on the fenced source: 155):

  - the `do { } while (0)` fences, bare `{ }` blocks and identical-arm guards (`if (c) { S } else { S }`) taken off;
  - a name that holds two values (an offset `o`, then `o = load + o; o -= c`) split into one local per value;
  - `x = D; ...; x op= y;` folded into one expression `x = (D) op y` where the in-place update was: the load moves
    with it, so the temporary the compiler makes for the sum is a pseudo of its own;
  - a value updated twice (`v = D; v += y1; ...; v += y2`) split in two: `v_a = (D) + y1;` written just before
    `v = v_a + y2;`, so the first sum is a local of its own;
  - updates by a literal (`x -= 8.0f`) left alone: a literal folded into a sum is materialised differently.

The straight-line run is the function's first statements after its declarations, as far as they are assignments of
a local from a pure expression (loads, `+ - * /`, literals). The first other statement (the clamps' `if`s) ends it
and is left as it was, apart from identical-arm guards inside it. The meaning is unchanged: the final value of
every original local is computed before and after with random operands (a different association rounds differently,
an identical expression tree does not), and the child is offered only when the two agree exactly.
"""
import random
import re

from .csource import _blank, find
from .pattern_repairs import close

FAMILY = 'float_block_normal_form'
FAMILIES = (FAMILY,)

IDENT = r'[A-Za-z_]\w*'
_WORD = re.compile(IDENT)
_FLOAT_TYPES = ('f32', 'float')
_QUALIFIERS = {'register', 'volatile', 'const', 'static', 'unsigned', 'signed', 'struct'}
_KEYWORDS = {'if', 'else', 'while', 'for', 'do', 'return', 'switch', 'case', 'default', 'break', 'continue',
             'goto', 'typedef', 'sizeof'}
_ASSIGN = re.compile(r'^(' + IDENT + r')\s*(=|[-+*/]=)(?!=)\s*(.+);$', re.S)
_PURE = re.compile(r'[\w\s.+\-*/()\[\]]+')
_CALL = re.compile(IDENT + r'\s*\(')
_NUMBER = re.compile(r'^[\s(]*[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?[fF]?[\s)]*$')
_SIMPLE_CONDITION = re.compile(r'^[\w\s.!<>=]+$')
_LOAD = re.compile(r'\*\s*\(\s*(?P<outer>\(\s*)?(?:' + IDENT + r'\s+)*' + IDENT + r'\s*\*+\s*\)\s*')
_HEX = re.compile(r'\b0[xX][0-9a-fA-F]+\b')
MAX_STATEMENTS = 160


def _statement(text, at, end):
    """The end of the statement that starts at `at`, or None. Handles blocks, `do { } while (..);`, `if` chains
    with `else`, and plain `;` statements."""
    while at < end and text[at].isspace():
        at += 1
    if at >= end:
        return None
    word = _WORD.match(text, at)
    token = word[0] if word else ''
    if text[at] == '{':
        return close(text, at, '{', '}')
    if token == 'do':
        opening = text.find('{', at, end)
        stop = close(text, opening, '{', '}') if opening >= 0 else None
        tail = re.compile(r'\s*while\s*\(').match(text, stop) if stop else None
        stop = close(text, tail.end() - 1, '(', ')') if tail else None
        semi = re.compile(r'\s*;').match(text, stop) if stop else None
        return semi.end() if semi else None
    if token in ('if', 'for', 'while', 'switch'):
        paren = text.find('(', at, end)
        stop = close(text, paren, '(', ')') if paren >= 0 else None
        stop = _statement(text, stop, end) if stop else None
        while stop and token == 'if':
            nxt = re.compile(r'\s*else\b').match(text, stop)
            if not nxt:
                break
            stop = _statement(text, nxt.end(), end)
        return stop
    depth = 0
    for pos in range(at, end):
        char = text[pos]
        if char in '({[':
            depth += 1
        elif char in ')}]':
            depth -= 1
        elif char == ';' and depth <= 0:
            return pos + 1
    return None


def _statements(text, start, end):
    """[(start, stop)] of the statements in text[start:end], or None when one cannot be delimited."""
    out, at = [], start
    while True:
        while at < end and text[at].isspace():
            at += 1
        if at >= end:
            return out
        stop = _statement(text, at, end)
        if not stop or stop > end:
            return None
        out.append((at, stop))
        at = stop


def _normal(text):
    return re.sub(r'\s+', ' ', text).strip()


def _guard(clean, at):
    """For an `if (c) { A } else { B }` that starts at `at`: (condition, A span, B span, end), else None."""
    paren = clean.find('(', at)
    pstop = close(clean, paren, '(', ')') if paren >= 0 else None
    arm = re.compile(r'\s*\{').match(clean, pstop) if pstop else None
    if not arm:
        return None
    first_end = close(clean, arm.end() - 1, '{', '}')
    other = re.compile(r'\s*else\s*\{').match(clean, first_end) if first_end else None
    second_end = close(clean, other.end() - 1, '{', '}') if other else None
    if not second_end:
        return None
    return (clean[paren + 1:pstop - 1], (arm.end(), first_end - 1), (other.end(), second_end - 1), second_end)


def _collapse_guards(text):
    """`if (c) { S } else { S }` with identical arms and a condition that only reads, written as S. Returns
    (text, changed)."""
    changed, pos = False, 0
    while True:
        clean = _blank(text)
        hit = re.compile(r'\bif\s*\(').search(clean, pos)
        if not hit:
            return text, changed
        guard = _guard(clean, hit.start())
        if guard and _SIMPLE_CONDITION.match(guard[0]):
            one, two = clean[guard[1][0]:guard[1][1]], clean[guard[2][0]:guard[2][1]]
            if one.strip() and _normal(one) == _normal(two) and not re.search(r'[{}]', one):
                text = text[:hit.start()] + one.strip() + text[guard[3]:]
                changed = True
                pos = hit.start()
                continue
        pos = hit.end()


def _flatten(clean, a, b, declared):
    """The simple assignments the statement clean[a:b] stands for, as [(lhs, op, rhs)], or None (it is something
    else): a pure assignment of a local, a fence `do { } while (0);`, a bare block, an identical-arm guard."""
    text = clean[a:b].strip()
    a += len(clean[a:b]) - len(clean[a:b].lstrip())
    word = _WORD.match(text)
    token = word[0] if word else ''
    inner = None
    if token == 'do':
        if not re.search(r'while\s*\(\s*0\s*\)\s*;$', text):
            return None
        opening = clean.find('{', a, b)
        stop = close(clean, opening, '{', '}')
        inner = (opening + 1, stop - 1)
    elif text.startswith('{'):
        inner = (a + 1, b - 1)
    elif token == 'if':
        guard = _guard(clean, a)
        if not guard or guard[3] != b or not _SIMPLE_CONDITION.match(guard[0]):
            return None
        if _normal(clean[guard[1][0]:guard[1][1]]) != _normal(clean[guard[2][0]:guard[2][1]]):
            return None
        inner = guard[1]
    if inner is not None:
        parts = _statements(clean, inner[0], inner[1])
        if parts is None:
            return None
        out = []
        for x, y in parts:
            got = _flatten(clean, x, y, declared)
            if got is None:
                return None
            out.extend(got)
        return out
    hit = _ASSIGN.match(text)
    if not hit or hit[1] not in declared:
        return None
    rhs = hit[3]
    if not _PURE.fullmatch(rhs) or _CALL.search(rhs) or '++' in rhs or '--' in rhs:
        return None
    return [(hit[1], hit[2], _normal(rhs))]


def _identifiers(text):
    return [n for n in _WORD.findall(_HEX.sub(' ', text)) if n not in _KEYWORDS]


def _atoms(text):
    """`text` with each memory read (`*((T *) (...))`) replaced by a symbol, and literals unsuffixed: (text, atoms)."""
    atoms, out, pos = {}, [], 0
    while True:
        hit = _LOAD.search(text, pos)
        if not hit:
            out.append(text[pos:])
            break
        out.append(text[pos:hit.start()])
        at = hit.end()
        if at < len(text) and text[at] == '(':
            stop = close(text, at, '(', ')')
        else:
            word = re.compile(r'[\w.]+').match(text, at)
            stop = word.end() if word else None
        if stop and hit['outer']:
            shut = re.compile(r'\s*\)').match(text, stop)
            stop = shut.end() if shut else None
        if not stop:
            return None, None
        key = _normal(text[hit.start():stop])
        atoms.setdefault(key, f'__L{len(atoms)}')
        out.append(atoms[key])
        pos = stop
    joined = ''.join(out)
    return re.sub(r'(?<![\w.])(\d+\.\d*|\.\d+|\d+)[fF]\b', r'\1', joined), atoms


def _numeric(records, seed):
    """The final value of every local with random operands, or None when an expression cannot be evaluated."""
    free, env = {}, {}

    def value(name):
        if name in env:
            return env[name]
        if name not in free:  # (by name, so the same operand is the same number in whatever order it is met)
            free[name] = random.Random(f'{seed}:{name}').uniform(1.0, 2.0)
        return free[name]
    for lhs, op, rhs in records:
        text, atoms = _atoms(rhs)
        if text is None:
            return None
        scope = {}
        for key in atoms:
            scope[atoms[key]] = value(key)
        for ident in _identifiers(text):
            if ident not in scope:
                scope[ident] = value(ident)
        try:
            got = eval(text, {'__builtins__': {}}, scope)  # noqa: S307  (a pure arithmetic expression, checked above)
        except (SyntaxError, TypeError, NameError, ZeroDivisionError, ValueError):
            return None
        if op == '=':
            env[lhs] = got
        else:
            old = value(lhs)
            env[lhs] = {'+': old + got, '-': old - got, '*': old * got, '/': old / got if got else None}[op[0]]
            if env[lhs] is None:
                return None
    return env


def _same_meaning(before, after, names):
    for seed in (1, 2, 3):
        old, new = _numeric(before, seed), _numeric(after, seed)
        if old is None or new is None:
            return False
        if any(old.get(n) != new.get(n) for n in names if n in old):
            return False
    return True


def _fresh(base, taken):
    for suffix in ('_a', '_b', '_c', '_d', '_e', '_f', '_g'):
        if base + suffix not in taken:
            taken.add(base + suffix)
            return base + suffix
    return None


def _normal_form(records, floats, taken):
    """(records, fresh float names) of the split and folded run, or None when nothing changes or it is unsafe."""
    current, count, webs = {}, {}, {}
    readmap, writes = [], []
    for index, (lhs, op, rhs) in enumerate(records):
        seen = {}
        for ident in _identifiers(rhs):
            if ident in floats:
                if ident not in current:
                    return None
                seen[ident] = current[ident]
                webs[current[ident]]['readers'].append(index)
        write = None
        if lhs in floats:
            if op == '=':
                count[lhs] = count.get(lhs, 0) + 1
                write = (lhs, count[lhs])
                webs[write] = dict(name=lhs, define=index, rmw=[], literal=[], readers=[])
                current[lhs] = write
            else:
                if lhs not in current:
                    return None
                write = current[lhs]
                webs[write]['literal' if _NUMBER.match(rhs) else 'rmw'].append(index)
        readmap.append(seen)
        writes.append(write)
    fresh, names = set(), {}
    for ident, web in webs.items():
        if (ident[0], ident[1] + 1) in webs:
            names[ident] = _fresh(web['name'], taken)
            if names[ident] is None:
                return None
            fresh.add(names[ident])
        else:
            names[ident] = web['name']
    renamed = []
    for index, (lhs, op, rhs) in enumerate(records):
        swap = {ident: names[web] for ident, web in readmap[index].items()}
        renamed.append([names[writes[index]] if writes[index] is not None else lhs, op,
                        re.sub(IDENT, lambda m, swap=swap: swap.get(m[0], m[0]), rhs)])
    removed, placed = set(), {}
    for ident, web in webs.items():
        if not web['rmw'] or web['literal']:
            continue
        define, rmw = web['define'], sorted(web['rmw'])
        last = rmw[-1]
        if any(r < last and r != define and r not in rmw for r in web['readers']):
            continue  # something reads an intermediate value
        moved = {w for i in [define, *rmw[:-1]] for w in readmap[i].values()}
        if any(webs[w]['rmw'] or webs[w]['literal'] for w in moved):
            continue  # an operand that is itself updated in place cannot be read later
        value = renamed[define][2]
        for r in rmw[:-1]:
            value = f'({value}) {renamed[r][1][0]} {renamed[r][2]}'
        name = names[ident]
        if len(rmw) == 1:
            placed[last] = [[name, '=', f'({value}) {renamed[last][1][0]} {renamed[last][2]}']]
        else:
            inter = _fresh(web['name'], taken)
            if inter is None:
                return None
            fresh.add(inter)
            placed[last] = [[inter, '=', value], [name, '=', f'{inter} {renamed[last][1][0]} {renamed[last][2]}']]
        removed.update([define, *rmw[:-1]])
    out = []
    for index, record in enumerate(renamed):
        if index in placed:
            out.extend(placed[index])
        elif index not in removed:
            out.append(record)
    out = [tuple(r) for r in out]
    if out == [tuple(r) for r in records]:
        return None
    if not _same_meaning(list(records), out, {r[0] for r in records}):
        return None
    return out, fresh


def _declarations(clean, parts):
    """(declared names, float names, index of the first statement that is not a declaration, last declaration)."""
    declared, floats, last = set(), set(), None
    for index, (a, b) in enumerate(parts):
        text = clean[a:b].strip()
        word = _WORD.match(text)
        if not word or word[0] in _KEYWORDS or '=' in text or not text.endswith(';'):
            return declared, floats, index, last
        pieces = [p.strip() for p in text[:-1].split(',')]
        first = re.match(r'^((?:' + IDENT + r'\s+)*?)([\s*]*)(' + IDENT + r')$', pieces[0])
        if not first or not first[1].split() or not all(re.fullmatch(r'[\s*\w]+', p) for p in pieces):
            return declared, floats, index, last
        kind = [w for w in first[1].split() if w not in _QUALIFIERS]
        shape = [(first[2], first[3])] + [(re.match(r'[\s*]*', p)[0], re.search(IDENT + r'$', p)[0]) for p in pieces[1:]]
        for stars, ident in shape:
            declared.add(ident)
            if len(kind) == 1 and kind[0] in _FLOAT_TYPES and '*' not in stars:
                floats.add(ident)
        last = index
    return declared, floats, len(parts), last


def variants(source, name):
    span = find(source, name)
    if not span:
        return []
    clean = _blank(source)
    opening = clean.find('{', span[0], span[1])
    end = close(clean, opening, '{', '}') if opening >= 0 else None
    if not end or '#' in clean[opening:end]:
        return []
    parts = _statements(clean, opening + 1, end - 1)
    if not parts or len(parts) > MAX_STATEMENTS:
        return []
    declared, floats, first, last = _declarations(clean, parts)
    if first >= len(parts):
        return []
    run, barrier, fenced = [], len(parts), False
    for index in range(first, len(parts)):
        got = _flatten(clean, parts[index][0], parts[index][1], declared)
        if got is None:
            barrier = index
            break
        run.extend(got)
        fenced = fenced or not _ASSIGN.match(clean[parts[index][0]:parts[index][1]].strip())
    tail_start = parts[barrier][0] if barrier < len(parts) else end - 1
    tail, tail_changed = _collapse_guards(source[tail_start:end - 1])
    records = [tuple(r) for r in run]
    taken = set(_identifiers(clean))
    folded = _normal_form(records, floats, taken) if records else None
    if folded is None and not fenced and not tail_changed:
        return []
    new_records, fresh = folded if folded else (records, set())
    indent = (re.search(r'([ \t]*)$', source[:parts[first][0]])[1]) or '  '
    head = source[:parts[first][0]].rstrip(' \t')
    if fresh:
        stop = parts[last][1] if last is not None else len(head)
        head = source[:stop] + ''.join(f'\n{indent}f32 {n};' for n in sorted(fresh)) + source[stop:parts[first][0]].rstrip(' \t')
    block = '\n'.join(f'{indent}{lhs} {op} {rhs};' for lhs, op, rhs in new_records)
    rest = ('\n' + indent + tail.lstrip()) if tail.strip() else '\n'
    new_source = head + block + rest + source[end - 1:]
    return [(FAMILY, new_source)] if new_source != source else []


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}
