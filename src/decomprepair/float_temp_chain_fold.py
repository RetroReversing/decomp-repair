"""m2c's float temporaries folded into one expression per store: `(b - a) * t + a` with each field read once by cse.

m2c writes a vector interpolation (and any straight-line float update) as a run of temporaries, edited in place:

    t0 = *(p + 8);   t3 = *(q + 8);   t0 -= t3;   ...   t0 *= s;   ...   t0 += t3;   *(out + 8) = t0;

KMC GCC 2.7.2 expands each temporary as a pseudo of its own, so the loads come out in the order the statements name
them (the second operand's load first where m2c split `t3 = ...; t0 = (...) - t3;`) and the float registers follow the
order the pseudos were created. A developer wrote `out[0] = a[0] + (b[0] - a[0]) * t;`: one expression per store, the
field read twice in the text and once in the code (cse merges the loads), the minuend loaded first, the sum's operands
in the order the text has them. On a 150-instruction packed-vector interpolation (a three-float loop, then a packed
loop) this one edit took the three-float loop's six register rows and its swapped pair of loads away (75 -> 65), while
every older family was unable to move the saved best.

The rewrite is a symbolic forward substitution over a run of simple statements (float temporaries, plain integer
updates, `f32` stores; a call, brace, label or branch ends the run): each temporary becomes the expression it holds, the
stores are emitted in their original order at the first temporary's place, and the temporaries' statements go. It
declines (so the judge never scores a different program) when
- a temporary is used outside the run, or a step statement reads one;
- a store's pointer variable is also read through in the run (the store could change what a folded read sees; the
  rewrite assumes distinct buffers, as an interpolation's callers pass);
- a variable a read or store mentions is assigned between the new place and the statement the mention was in (a pointer
  step that m2c wrote before the stores is fine, because every read came before it);
- fewer than three temporary statements would go, or no temporary is used twice (nothing to fold).
The child is a hypothesis for the judge: the folded text computes the same values only while stores and reads do not
overlap, which the run's own pointer variables are checked for."""
import re

from .integer_repair_support import edit, view

FAMILY = 'float_temp_chain_fold'
FAMILIES = (FAMILY,)

_TYPES = {'const', 'char', 'f32', 'float', 's8', 's16', 's32', 'u8', 'u16', 'u32', 'int', 'short', 'long', 'unsigned',
          'signed', 'void', 'volatile', 'f64', 'double', 'sizeof'}
_IDENT = re.compile(r'(?<!\w)[A-Za-z_]\w*')
_FLOAT_DECL = re.compile(r'\b(?:f32|float)\s+([A-Za-z_][\w\s,]*);')
_BARRIER = re.compile(r'^(?:if|else|for|while|do|switch|case|default|goto|return|break|continue)\b|^\w+\s*:(?!:)')
_ASSIGN = re.compile(r'^([A-Za-z_]\w*)\s*(=|\+=|-=|\*=|/=)(?!=)\s*(.+)$', re.S)
_STORE = re.compile(r'^(\*?\(\s*\*\s*\(\s*(?:f32|float)\s*\*\s*\)[^;=]*?\)|\*\s*\(\s*(?:f32|float)\s*\*\s*\)[^;=]*?)'
                    r'\s*=(?!=)\s*(.+)$', re.S)
_CALL = re.compile(r'\b(?!sizeof\b)[A-Za-z_]\w*\s*\(')


def _statements(part):
    """(start, end, text) of each statement in the body; text is None for a brace, a label or an unfinished piece."""
    text, out = part.clean, []
    begin, depth = part.opening + 1, 0
    for i in range(part.opening + 1, part.end - 1):
        c = text[i]
        if c in '([':
            depth += 1
        elif c in ')]':
            depth -= 1
        elif depth == 0 and c in '{}':
            if text[begin:i].strip():
                out.append((begin, i, None))
            out.append((i, i + 1, None))
            begin = i + 1
        elif depth == 0 and c == ';':
            out.append((begin, i + 1, text[begin:i].strip()))
            begin = i + 1
    return out


def _regions(part):
    run = []
    for item in _statements(part):
        if item[2] is None or _BARRIER.match(item[2]) or _CALL.search(item[2]):
            if run:
                yield run
            run = []
        else:
            run.append(item)
    if run:
        yield run


def _names(expr, temps):
    return [word for word in _IDENT.findall(expr) if word not in _TYPES and word not in temps]


def _fold(run, temps):
    """(removed, stores, steps) of a run, or None when a statement is not one the rewrite understands."""
    env, removed, stores, steps = {}, [], [], []
    for position, (_, _, text) in enumerate(run):
        store, assign = _STORE.match(text), _ASSIGN.match(text)
        if store:
            expr, mentions = _expand(store.group(2), env, position, temps)
            stores.append((position, store.group(1), expr, mentions + [(v, position) for v in _names(store.group(1), temps)]))
        elif assign and assign.group(1) in temps:
            temp, op, rhs = assign.groups()
            expr, mentions = _expand(rhs, env, position, temps)
            if op != '=':
                if temp not in env:
                    return None
                before, earlier = env[temp]
                expr, mentions = f'({before}) {op[0]} ({expr})', earlier + mentions
            env[temp] = (expr, mentions)
            removed.append(position)
        elif assign and assign.group(1) not in temps and assign.group(2) in ('=', '+=', '-='):
            if set(_IDENT.findall(assign.group(3))) & temps:
                return None
            steps.append((position, assign.group(1)))
        else:
            return None
    return removed, stores, steps, env


def _expand(expr, env, position, temps):
    """`expr` with each known temporary replaced by its expression, and the (variable, statement) mentions in it."""
    mentions = []

    def swap(m):
        word = m.group()
        if word in env:
            mentions.extend(env[word][1])
            return f'({env[word][0]})'
        if word not in _TYPES and word not in temps:
            mentions.append((word, position))
        return word

    return _IDENT.sub(swap, expr), mentions


def _region_edits(part, run, temps):
    folded = _fold(run, temps)
    if not folded:
        return []
    removed, stores, steps, env = folded
    if len(removed) < 3 or not stores or stores[0][0] < removed[0]:
        return []
    start, stop = run[0][0], run[-1][1]
    outside = _FLOAT_DECL.sub('', part.clean[part.opening + 1:start]) + part.clean[stop:part.end - 1]
    if any(re.search(rf'\b{t}\b', outside) for t in env):
        return []
    first = removed[0]
    store_vars = {v for _, lvalue, _, _ in stores for v in _names(lvalue, temps)}
    if store_vars & {v for _, _, expr, _ in stores for v in _names(expr, temps)}:
        return []
    for _, _, _, mentions in stores:
        for var, at in mentions:
            if any(name == var and first <= step < at for step, name in steps):
                return []
    inside = [run[i][2] for i in range(len(run))]
    if not any(sum(bool(re.search(rf'\b{t}\b', inside[i])) for i in range(first + 1, len(run))
                   if _ASSIGN.match(inside[i]) is None or _ASSIGN.match(inside[i]).group(1) != t
                   or re.search(rf'\b{t}\b', _ASSIGN.match(inside[i]).group(3))) >= 2 for t in env):
        return []
    raw = part.clean[run[first][0]:run[first][1]]
    begin = run[first][0] + len(raw) - len(raw.lstrip())
    indent = part.source[part.source.rfind('\n', 0, begin) + 1:begin]
    indent = indent if not indent.strip() else '    '
    text = f'\n{indent}'.join(f'{lvalue} = {expr};' for _, lvalue, expr, _ in stores)
    edits = [(begin, run[first][1], text)]
    edits += [(run[i][0], run[i][1], '') for i in removed[1:]]
    edits += [(run[i][0], run[i][1], '') for i, *_ in stores]
    return edits


def variants(source, name):
    part = view(source, name)
    if not part:
        return []
    body = part.clean[part.opening + 1:part.end - 1]
    temps = {t.strip() for group in _FLOAT_DECL.findall(body) for t in group.split(',') if t.strip()}
    if not temps:
        return []
    edits = []
    for run in _regions(part):
        edits += _region_edits(part, run, temps)
    return [(FAMILY, edit(source, edits))] if edits else []


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}
