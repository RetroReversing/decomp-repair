"""A straight run of float temporaries written out in the stores that use them, the stores in index order.

m2c (and an agent editing its output) names every product the stores share (`czsy = cz * sy;`) and builds the
sums in place (`m01 = czsy * sx; m01 -= szcx; ... matrix[1] = m01;`). The hand-written original had the plain form:
one statement per output, `matrix[1] = (cz * sy) * sx - (sz * cx);`, the outputs in the order of their index, the
compiler's common-subexpression pass finding the shared products again. A rotation-matrix builder (GCC 2.7.2, the
nine outputs of a 3x3 matrix) was three registers short of exact at 15 with the temporaries and exact (15 -> 0) with
every temporary inlined *and* the stores in index order. Neither change helps alone (the inlined form in the old
store order was 70, the old temporaries in index order 180): the scheduler orders the shared products by the order
their first use appears, and that order is the stores'.

The run is the statements between two barriers (a call, a branch, a declaration, anything that is not
`name = e;` / `name op= e;` / `base[N] = e;`). Every name the run assigns must be a float local that nothing after
the run reads, and no expression may read memory (the stores can then be reordered freely). The temporaries are
substituted forward, so a name assigned twice (`sy = -sy;` after products that read the old `sy`) keeps the value
each use saw. Two children: the stores in their own order, and, when each stored index is distinct, sorted.
"""
import re

from .csource import _blank, find
from .pattern_repairs import close
from .shared_product_repairs import _declared_type

FAMILY = 'store_expression_form'
FAMILIES = (FAMILY,)

IDENT = r'[A-Za-z_]\w*'
FLOATS = {'float', 'f32', 'double', 'f64'}
ASSIGN = re.compile(rf'\s*({IDENT})\s*(\+|-|\*|/)?=(?!=)\s*(.+?)\s*\Z', re.S)
STORE = re.compile(rf'\s*({IDENT})\s*\[\s*(0[xX][0-9A-Fa-f]+|\d+)\s*\]\s*=(?!=)\s*(.+?)\s*\Z', re.S)
KEYWORD = re.compile(r'\s*(?:if|else|for|while|do|switch|case|default|return|goto|break|continue|typedef|struct|union|enum|static|extern|volatile|register|unsigned|signed|const|void|char|short|int|long|float|double|f32|f64|[su](?:8|16|32|64))\b')
CALL = re.compile(r'(?<![\w)\]])\w+\s*\(|\w\s*\(')
MEMORY = re.compile(r'\[|->|\.(?!\d)|&|(?:^|[(=+\-*/,<>!&|^?:])\s*\*')


def _balanced(text):
    return text.startswith('(') and close(text, 0) == len(text)


def _paren(text):
    return text if re.fullmatch(r'[\w.]+', text) or _balanced(text) else f'({text})'


def _expand(text, env):
    return re.sub(rf'(?<![\w.]){IDENT}\b', lambda m: _paren(env[m[0]]) if m[0] in env else m[0], text)


def _pure(text):
    """No call and no memory read: the value depends on the names alone."""
    return not CALL.search(text) and not MEMORY.search(text) and '++' not in text and '--' not in text


def _statements(clean, start, end):
    """(begin, stop, text) of each `;`-terminated statement in clean[start:end]."""
    result, begin = [], start
    for m in re.finditer(';', clean[start:end]):
        stop = start + m.start()
        result.append((begin, stop, clean[begin:stop]))
        begin = stop + 1
    return result


def _runs(statements, clean, signature, body):
    """Runs of plain statements: lists of (begin, stop, kind, match)."""
    runs, run = [], []
    for begin, stop, text in statements:
        kind = match = None
        if not re.search(r'[{}:?]', text) and not KEYWORD.match(text):
            for kind, pattern in (('store', STORE), ('assign', ASSIGN)):
                match = pattern.fullmatch(text)
                if match:
                    break
            else:
                match = None
        ok = match is not None and _pure(match[3] if kind == 'store' else match[3])
        if ok and kind == 'assign':
            ok = _declared_type(signature, body, match[1]) in FLOATS
        if ok:
            run.append((begin, stop, kind, match))
        elif run:
            runs.append(run)
            run = []
    if run:
        runs.append(run)
    return runs


def _forms(run, tail):
    """(statements as text, ordered) for the run, or None when it cannot be written out."""
    env, stores, defined = {}, [], set()
    for _, _, kind, m in run:
        if kind == 'assign':
            name, op, rhs = m[1], m[2], _expand(m[3], env)
            defined.add(name)
            if op:
                old = env.get(name, name)
                env[name] = f'{_paren(old) if op not in "+-" else old} {op} {_paren(rhs)}'
            else:
                env[name] = rhs
        else:
            stores.append((m[1], int(m[2], 0), _expand(m[3], env)))
    if not stores or not defined:
        return None
    if any(re.search(rf'(?<![\w.]){re.escape(n)}\b', tail) for n in defined):
        return None
    if any(re.search(r'(?<![\w.])' + re.escape(base) + r'\b', rhs) for base, _, rhs in stores):
        return None  # a stored array read back: the stores' order matters
    return [(base, index, rhs[1:-1] if _balanced(rhs) else rhs) for base, index, rhs in stores]


def variants(source, name):
    span = find(source, name)
    if not span:
        return []
    clean = _blank(source)
    opening = clean.find('{', span[0], span[1])
    end = close(clean, opening, '{', '}') if opening >= 0 else None
    if not end:
        return []
    body = clean[opening:end]
    if re.search(r'\bgoto\b', body):
        return []
    signature = clean[span[0]:opening]
    result = []
    for run in _runs(_statements(clean, opening + 1, end - 1), clean, signature, body):
        first, last = run[0][0], run[-1][1]
        first += len(clean[first:last]) - len(clean[first:last].lstrip())
        if clean[opening:first].count('{') - clean[opening:first].count('}') != 1:
            continue  # inside a block: a loop could read the temporaries again
        stores = _forms(run, clean[last + 1:end])
        if stores is None:
            continue
        line = source.rfind('\n', 0, first) + 1
        indent = re.match(r'[ \t]*', source[line:first])[0]
        orders = [stores]
        by_index = sorted(stores, key=lambda s: (s[0], s[1]))
        if len({(b, i) for b, i, _ in stores}) == len(stores) and by_index != stores:
            orders.append(by_index)
        for order in orders:
            text = ('\n' + indent).join(f'{base}[{index}] = {rhs};' for base, index, rhs in order)
            candidate = source[:first] + text + source[last + 1:]
            if candidate != source and candidate not in [c for _, c in result]:
                result.append((FAMILY, candidate))
    return result
