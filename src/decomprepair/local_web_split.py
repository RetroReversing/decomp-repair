"""A function-level scratch local that many arms assign afresh, split into one local per assignment web.

m2c (and a search that edits its drafts) declares a temporary once at the top, and every arm that needs a scratch value
reuses it: `packet = cursor; word = K; ...; packet[1] = word; return;` in two dozen arms. One name is one pseudo
register for the whole function: it is assigned in every arm, so the allocator (global.c) sees a single long-lived
pseudo with a huge reference count, and it outranks the short pseudos the same code gets when every arm has a local of
its own (each arm's pseudo is born and dies inside its block and goes to local-alloc, which picks `$v1` for the
pointer and `$a0` for the constant). The bytes do not show the difference except through which registers come out and
through which tails cross-jumping can merge, and a display-list function with 24 such arms went from 365 to exactly 0
by giving each arm its own locals (each arm alone is much *worse*: 365 -> 1055, because its tail stops merging with the
other arms' until all of them agree; that is why every web is split in one child).

What is split (an *assignment web*): a plain statement `name = expr;` at the level of its own block, and every read of
`name` after it up to the end of that block, to the next plain assignment at the same level, or to the next `case`
label of the switch whose body that block is. Reads before any assignment, an assignment nested in a conditional that
a later read can still see around, an assignment inside a loop that holds an outer assignment's reads, an address
taken (`&name`), a shadowing declaration, and any `goto`/label inside a web all leave the web alone (it keeps the
original name together with everything its reads may see), so the program is the same program. Only a local declared
once at the top of the function, without initialiser, array or `volatile`, is touched.

`variants` gives, labelled `local_web_split`:
  every web of one local renamed (a declaration per web), for each local;
  every web of every such local at once, with the declarations as written and with `register` dropped (a `register`
  local's pseudo prefers a hard register of its own; the arms' fresh locals match without it).
"""
import re

from .case_temporary_repairs import DECLARATION, GOTO_LABEL, LABEL, _identifiers, _mentions, _switches
from .csource import _blank, find
from .pattern_repairs import close

FAMILY = 'local_web_split'
FAMILIES = (FAMILY,)
LIMIT = 40


class _Union:
    def __init__(self, n):
        self.parent = list(range(n))

    def find(self, k):
        while self.parent[k] != k:
            self.parent[k] = self.parent[self.parent[k]]
            k = self.parent[k]
        return k

    def join(self, a, b):
        self.parent[self.find(a)] = self.find(b)


def _blocks(clean, opening, end):
    """[(open, close)] of every `{}` in the function body, by position of the brace."""
    stack, out = [], []
    for m in re.finditer(r'[{}]', clean[opening:end]):
        at = opening + m.start()
        if m.group() == '{':
            stack.append(at)
        elif stack:
            out.append((stack.pop(), at))
    return sorted(out)


def _depths(clean, opening, end):
    """Parenthesis depth in front of every position of the function body."""
    depth, table = 0, {}
    for k in range(opening, end):
        table[k] = depth
        ch = clean[k]
        if ch == '(':
            depth += 1
        elif ch == ')':
            depth -= 1
    return table


def _innermost(blocks, pos):
    best = None
    for a, b in blocks:
        if a < pos < b and (best is None or a > best[0]):
            best = (a, b)
    return best


def _is_loop(clean, block):
    before = clean[:block[0]].rstrip()
    if re.search(r'\bdo$', before):
        return True
    if not before.endswith(')'):
        return False
    depth, k = 0, len(before) - 1
    while k >= 0:
        if before[k] == ')':
            depth += 1
        elif before[k] == '(':
            depth -= 1
            if depth == 0:
                break
        k -= 1
    return bool(re.search(r'\b(?:for|while)\s*$', before[:k]))


def _analyse(clean, var, decl, opening, end, blocks, parens, switches, labels):
    """[(assignment span, scope, reads)] webs of `var` after merging, each as (members, edits, ok); None to leave it."""
    pattern = _mentions(var)
    if re.search(r'&\s*' + re.escape(var) + r'\b', clean[opening:end]):
        return None
    mentions = [m for m in pattern.finditer(clean, opening + 1, end) if not decl.start() <= m.start() < decl.end()]
    assigns, reads = [], []
    for m in mentions:
        j = m.start()
        while j > opening and clean[j - 1].isspace():
            j -= 1
        before = clean[max(opening, j - 60):j]
        after = clean[m.end():m.end() + 80]
        plain = re.match(r'\s*=(?!=)', after) and parens.get(m.start(), 0) == 0 and (
            before.endswith((';', '{', '}')) or (before.endswith(':') and re.search(
                r'(?:\bcase\b[^:;{}]*|\bdefault|(?:^|[;{}\n])\s*[A-Za-z_]\w*)$', before[:-1])))
        if not plain:
            reads.append(m.start())
            continue
        stop, depth = m.end(), 0
        while stop < end:
            ch = clean[stop]
            if ch == '(':
                depth += 1
            elif ch == ')':
                depth -= 1
            elif ch == ';' and depth == 0:
                break
            stop += 1
        else:
            return None
        assigns.append({'at': m.start(), 'lhs_end': m.end(), 'stmt_end': stop + 1,
                        'block': _innermost(blocks, m.start())})
    if len(assigns) < 2 or not all(a['block'] for a in assigns):
        return None
    for a in assigns:
        a['scope_end'] = a['block'][1]
        for b in assigns:
            if b is not a and b['block'] == a['block'] and b['at'] > a['at']:
                a['scope_end'] = min(a['scope_end'], b['stmt_end'])
        for q in labels:
            if a['stmt_end'] < q < a['scope_end'] and _innermost(blocks, q) == a['block']:
                a['scope_end'] = q
    # every read belongs to the latest scope that contains it
    owner = {}
    for r in reads:
        mine = [k for k, a in enumerate(assigns) if a['stmt_end'] <= r < a['scope_end']]
        if not mine:
            return None
        owner[r] = max(mine, key=lambda k: assigns[k]['at'])
    web = _Union(len(assigns))
    for i, outer in enumerate(assigns):
        for j, inner in enumerate(assigns):
            if i == j or not (outer['stmt_end'] <= inner['at'] < outer['scope_end']) or inner['block'] == outer['block']:
                continue
            a, b = inner['block']
            leaves = re.search(r'\breturn\b[^;{}]*;\s*$', clean[a + 1:b])  # control never leaves the block but by `return`
            seen = [r for r, k in owner.items() if k == i and r > b and not leaves]  # reads in front of it see no inner value (a loop is checked below)
            if seen:
                web.join(i, j)
                continue
            chain = [blk for blk in blocks if blk[0] >= outer['stmt_end'] and blk[0] <= a and b <= blk[1]]
            if any(_is_loop(clean, blk) for blk in chain):
                web.join(i, j)
    groups = {}
    for k in range(len(assigns)):
        groups.setdefault(web.find(k), []).append(k)
    result = []
    for members in groups.values():
        ok = True
        for k in members:
            a = assigns[k]
            body = clean[a['stmt_end']:a['scope_end']]
            if GOTO_LABEL.search(body) or not _leaves_forward(clean, body, var, a['scope_end'], end):
                ok = False
            for q in (m.start() for m in LABEL.finditer(clean, a['stmt_end'], a['scope_end'])):
                if not any(b0 > a['stmt_end'] and q < b1 <= a['scope_end'] for b0, b1 in switches):
                    ok = False
        edits = [(assigns[k]['at'], assigns[k]['lhs_end']) for k in members]
        edits += [(r, r + len(var)) for r, k in owner.items() if k in members]
        result.append((sorted(members, key=lambda k: assigns[k]['at']), edits, ok, min(assigns[k]['at'] for k in members)))
    result.sort(key=lambda w: w[3])
    return result


def _leaves_forward(clean, body, var, scope_end, end):
    """True when the web has no `goto`, or only gotos to a label that lies after it where `var` is never mentioned
    again: the value cannot flow along the jump, so the web is as closed as one that ends in `return`. (A switch
    case that ends `goto block_66;` for the common exit, the exit reading none of the arms' scratch locals.)"""
    names = re.findall(r'\bgoto\s+([A-Za-z_]\w*)\s*;', body)
    if len(names) != len(re.findall(r'\bgoto\b', body)):
        return False
    for label in set(names):
        where = re.search(r'(?m)^[ \t]*' + re.escape(label) + r'[ \t]*:(?!:)', clean[scope_end:end])
        if not where:
            return False
        if _mentions(var).search(clean, scope_end + where.start(), end):
            return False
    return True


def _apply(source, clean, plans, drop_register, taken):
    """`plans`: [(declaration match, var, webs)]; each web `(members, edits, ok, first)`: renamed when ok."""
    edits, declarations = [], []
    for decl, var, webs in plans:
        line = source[decl.start():decl.end()]
        cut = line.rindex(var)
        names, kept = [], False
        count = 0
        for members, spans, ok, first in webs:
            if not ok:
                kept = True
                continue
            count += 1
            name = f'{var}_{count}'
            while name in taken:
                name += '_'
            taken.add(name)
            names.append(name)
            edits += [(a, b, name) for a, b in spans]
        text = ''.join(line[:cut] + n + line[cut + len(var):] for n in names)
        if drop_register:
            text = re.sub(r'\bregister\s+', '', text)
        declarations.append((decl.start(), decl.end(), (line if kept else '') + text))
    pieces = [(a, b, n) for a, b, n in edits] + declarations
    for a, b, new in sorted(pieces, reverse=True):
        source = source[:a] + new + source[b:]
    return source


def variants(source, name):
    span = find(source, name)
    if not span:
        return []
    clean = _blank(source)
    opening = clean.find('{', span[0], span[1])
    end = close(clean, opening, '{', '}') if opening >= 0 else None
    if not end:
        return []
    blocks = _blocks(clean, opening, end)
    parens = _depths(clean, opening, end)
    switches = _switches(clean, opening, end)
    labels = [m.start() for m in LABEL.finditer(clean, opening, end)]
    declarations = {}
    names = {}
    for m in DECLARATION.finditer(clean, opening + 1, end):
        text = clean[m.start():m.end()]
        depth = clean[opening + 1:m.start()].count('{') - clean[opening + 1:m.start()].count('}')
        if depth != 0 or '(' in m['type'] or '[' in text or 'volatile' in text or '=' in text:
            continue
        names[m['name']] = names.get(m['name'], 0) + 1
        declarations.setdefault(m['name'], m)
    plans = []
    for var, decl in declarations.items():
        if names[var] != 1:
            continue
        # a nested declaration of the same name shadows it: leave such a local alone
        if len(re.findall(r'(?m)^[ \t]*(?!return\b|goto\b|else\b|case\b)[A-Za-z_][\w \t*]*[ \t*]' + re.escape(var) + r'[ \t]*[;=]', clean[opening:end])) != 1:
            continue
        webs = _analyse(clean, var, decl, opening, end, blocks, parens, switches, labels)
        if not webs:
            continue
        renamed = sum(1 for w in webs if w[2])
        if renamed + (1 if renamed < len(webs) else 0) < 2:
            continue
        plans.append((decl, var, webs))
    result = []

    def emit(text):
        if text != source and text not in [t for _, t in result] and len(result) < LIMIT:
            result.append((FAMILY, text))

    for plan in plans:
        emit(_apply(source, clean, [plan], False, _identifiers(source)))
    if plans:
        emit(_apply(source, clean, plans, False, _identifiers(source)))
        emit(_apply(source, clean, plans, True, _identifiers(source)))
    return result


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'order': 40}  # the registry: no caller wiring (registry.py)
