"""A local's live ranges given their own variables, or a value given a local it did not have: the pseudo numbering moves.

GCC 2.x numbers the pseudo of a declared local in declaration order and breaks every tie of the register allocator
(`local-alloc` quantities of equal priority, `global-alloc` candidates of equal weight) by that number; a local that
holds two unrelated values in turn is ONE pseudo with a long live range, and the same two values in two locals are two
short ones the allocator may colour differently (and `-O2` cross-jumping and the scheduler see different register names).
Hand matches on N64 SN/KMC GCC code needed both directions, found by hand because the family list had only merges of
locals (`disjoint_local_merge_repairs`, `merge_disjoint_temporaries`, `dead_scratch_reuse`):
- a float held a call's result for the first compares and was reused for a later load (`d = f(); if (d < K) ...;
  d = cam->x;`): the first range written in a new local `e`;
- a loop cursor assigned from a call several lines above the loop (`o = f(0); end = g(0); for (; o <= end; o++)`):
  the call's result in a local of its own and the cursor set from it in the loop head (`p = f(0); ... for (o = p; ...)`);
- a call result used only as the base of a store through a field (`FIELD(f(a), T, 0x9C) = v;`) held in a local first
  (`temp = f(a); FIELD(temp, T, 0x9C) = v;`), in a declared local of the same type that is dead there or a new one;
- a float assigned from a call in a statement (`dist = sqrtf(x);`) while the same call stands in a test elsewhere
  (`if (k < sqrtf(x)) {`): the test assigns it (`k < (dist = sqrtf(x))`), the later statement staying.

Children (`LIMIT` in all, in the order of the source):
- `local_split_new`: for a scalar or pointer local `X` (declared plainly, address never taken) and two consecutive
  definitions `X = e0;` ... `X = e1;` (e1 not reading X, the first at the top of its block), either range written in a
  new local `X2` declared after the others: the first range (the definition and the uses before the second definition),
  or the second (its definition and the uses after it up to the next one). Only when no other path can reach them: every
  use of the renamed range lies between the definition and the next definition or the end of its block, the next
  definition's block closes with no later use of X outside it (a conditional second definition leaves the first live
  past it), no loop around the definition reads X before it, and the function has no `goto`.
- `loop_cursor_own_temp`: `X = e;` then, within three statements that do not name X, a `for (; test; step)` whose head has
  no initialiser and tests X: `P = e;` and `for (X = P; ...)`.
- `call_result_base_local`: a statement that stores through the result of a call (`M2C_FIELD(f(a), T, off) = v;`,
  `*(T *)((s8 *)f(a) + off) = v;`, `f(a)->m = v;`) written with the call result in a local on the line before: each
  dead-looking declared local of the callee's pointer type (at most two), then a new one.
- `call_assigned_in_test`: `if (... f(a) ...)` or `while (...)` whose test holds the call text of a statement
  `L = f(a);` (L a float or integer local): the test's call written `(L = f(a))`, the statement unchanged.
A function with `volatile`, `asm`, `goto` or a preprocessor line is left alone. Proposals only; the byte judge decides."""
import re

from .integer_repair_support import IDENT, _address_taken, edit, view
from .local_weight_ladder import _declaration

FAMILY_SPLIT = 'local_split_new'
FAMILY_CURSOR = 'loop_cursor_own_temp'
FAMILY_BASE = 'call_result_base_local'
FAMILY_TEST = 'call_assigned_in_test'
FAMILIES = (FAMILY_SPLIT, FAMILY_CURSOR, FAMILY_BASE, FAMILY_TEST)
LIMIT = 8
_PLAIN = {'if', 'else', 'while', 'for', 'do', 'switch', 'return', 'goto', 'break', 'continue', 'case', 'default'}
_CALL = re.compile(rf'(?<![\w.>])(?P<callee>{IDENT})\s*\(')


def _python_matches(clean, lo, hi):
    """{opening brace: its closing brace} of every block in [lo, hi)."""
    stack, out = [], {}
    for at in range(lo, hi):
        if clean[at] == '{':
            stack.append(at)
        elif clean[at] == '}' and stack:
            out[stack.pop()] = at
    return out


_matches = _python_matches
try:  # the typed kernel (native_build.py), when it is built: same answers, the loop in C
    from . import _scan
except ImportError:
    _scan = None
if _scan is not None:
    def _matches(clean, lo, hi):
        found = _scan.block_pairs(clean, lo, hi)
        if found is not NotImplemented:
            return dict(found)
        return _python_matches(clean, lo, hi)


def _enclosing(blocks, at):
    """(opening, closing) of the innermost block holding `at`, outermost first when several share it."""
    inside = [(o, c) for o, c in blocks.items() if o < at < c]
    return min(inside, key=lambda item: item[1] - item[0]) if inside else None


def _locals(part):
    """{name: (type text, declaration line)} of the function's plain leading local declarations."""
    out = {}
    pos = part.opening + 1
    for line in part.clean[pos:part.end].split('\n'):
        stripped = line.strip()
        if not stripped:
            continue
        match = _declaration(line)
        if not match:
            if re.fullmatch(r'[\w\s*\[\]]+;', stripped) and stripped.split()[0] not in _PLAIN:
                continue  # an array or another plain declaration
            break
        out[match['name']] = (match['type'] + match['gap'].rstrip(), line)
    return out


def _insert_declaration(source, part, declaration, after=None):
    """`source` with `declaration` on a new line after the function's last leading declaration (arrays included), or after
    the last one whose line has the type `after` (a pointer local next to the others of its type)."""
    clean = part.clean
    at = part.opening + 1
    end, chosen = at, None
    for line in clean[at:part.end].split('\n')[1:]:
        stripped = line.strip()
        at_line = clean.find(line, end) if line else end
        if not stripped:
            continue
        if not (_declaration(line) or (re.fullmatch(r'[\w\s*\[\]]+;', stripped) and stripped.split()[0] not in _PLAIN)):
            break
        end = at_line + len(line)
        if after is not None and (match := _declaration(line)) and (match['type'] + match['gap'].rstrip()) == after:
            chosen = end
    if after is not None and chosen is not None:
        end = chosen
    indent = re.search(r'\n([ \t]*)\S', source[part.opening:]).group(1) or '    '
    return edit(source, [(end, end, f'\n{indent}{declaration}')])


def _decl_text(kind, name):
    return f'{kind}{name};' if kind.endswith('*') else f'{kind} {name};'


def _uses(clean, name, lo, hi):
    """Where `name` is read or written in [lo, hi): not a field of something (`o->name`, `o.name`)."""
    return [lo + m.start() for m in re.finditer(rf'(?<![\w.])(?<!->){re.escape(name)}\b', clean[lo:hi])]


def _paren_depth(clean, lo, at):
    return clean[lo:at].count('(') - clean[lo:at].count(')')


def _definitions(clean, name, lo, hi):
    """[(statement start, `=` end, statement end)] of the statements `name = e;` at a statement boundary."""
    out = []
    for hit in re.finditer(rf'(?<![\w.])(?<!->){re.escape(name)}\s*=(?!=)', clean[lo:hi]):
        start = lo + hit.start()
        before = clean[lo:start].rstrip()[-1:]
        if before not in (';', '{', '}') or _paren_depth(clean, lo, start):
            continue
        end = clean.find(';', lo + hit.end())
        if end < 0 or end >= hi:
            continue
        out.append((start, lo + hit.end(), end))
    return out


def _split_children(source, part, name, declared):
    out = []
    clean = part.clean
    lo, hi = part.opening + 1, part.end
    blocks = _matches(clean, part.opening, part.end)
    loops = _loops(clean, blocks, part.opening)
    body = clean[lo:hi]
    used = set(re.findall(IDENT, body))
    whole = (part.opening, part.end)
    for local, (kind, _line) in declared.items():
        if _address_taken(body, local):
            continue
        defs = _definitions(clean, local, lo, hi)
        for index, (first, second) in enumerate(zip(defs, defs[1:])):
            if _uses(clean, local, second[1], second[2]):
                continue  # the second definition reads the first range's value: one chain
            block = _enclosing(blocks, first[0]) or whole
            other = _enclosing(blocks, second[0]) or whole
            if not (block[0] <= other[0] and other[1] <= block[1]):
                continue  # the second definition is neither in the first's block nor inside it
            new = _fresh(used, local)
            # the first range: its definition and every use up to the second definition
            exposed = other != block and _exposed(clean, blocks, defs, local, other[1], hi)
            span = [first[0]] + _uses(clean, local, first[1], second[0])
            if (not _read_before_in_loop(clean, loops, local, first[0]) and not exposed
                    and not _comes_round(loops, first[0], span[1:], defs)):
                child = edit(source, [(at, at + len(local), new) for at in span])
                moved = view(child, name)
                if moved:
                    out.append((FAMILY_SPLIT, _insert_declaration(child, moved, _decl_text(kind, new))))
            # the second range: its definition and the uses after it, up to the next definition in its own block; a
            # block that closes with a later use of the local outside it leaves the first range live there
            following = [d for d in defs[index + 2:] if (_enclosing(blocks, d[0]) or whole) == other]
            stop = following[0][0] if following else other[1]
            if other != whole and exposed:
                continue
            span = [second[0]] + _uses(clean, local, second[1], stop)
            if (not _read_before_in_loop(clean, loops, local, second[0])
                    and not _comes_round(loops, second[0], span[1:], defs)):
                if following:  # the next definition may read this range's value (`X = (X & 3) ? .. : X;`)
                    span += _uses(clean, local, following[0][1], following[0][2])
                child = edit(source, [(at, at + len(local), new) for at in span])
                moved = view(child, name)
                if moved:
                    out.append((FAMILY_SPLIT, _insert_declaration(child, moved, _decl_text(kind, new))))
            used.add(new)
    return out


def _exposed(clean, blocks, defs, local, lo, hi):
    """Whether a use of `local` after `lo` can see a value from before it. A use is covered when a definition before it
    (after `lo`) sits in a block that holds the use, or when an if/else-if/else chain before it defines the local in every
    arm, final else included."""
    chains = _defining_chains(clean, blocks, defs)
    written = {d[0] for d in defs}
    for use in _uses(clean, local, lo, hi):
        if use in written:
            continue  # the left side of a definition reads nothing
        if any(lo <= d[0] < use and _holds(blocks, d[0], use) for d in defs):
            continue
        if any(end >= lo and end < use and _holds(blocks, start, use) for start, end in chains):
            continue
        return True
    return False


def _defining_chains(clean, blocks, defs):
    """[(start, end)] of the if/else chains whose every arm holds a definition of the local at its own top level."""
    out = []
    starts = []
    for opening in sorted(blocks):
        head = clean[:opening].rstrip()
        if not head.endswith(')'):
            continue
        depth, at = 0, len(head)
        while at > 0:
            at -= 1
            depth += (head[at] == ')') - (head[at] == '(')
            if depth == 0:
                break
        lead = clean[:at].rstrip()
        if lead.endswith('if') and not clean[:len(lead) - 2].rstrip().endswith('else'):
            starts.append((len(lead) - 2, opening))
    for begin, opening in starts:
        arms, final, at = [], False, opening
        while True:
            close = blocks[at]
            arms.append((at, close))
            rest = clean[close + 1:]
            stripped = rest.lstrip()
            if not stripped.startswith('else'):
                break
            after = stripped[4:].lstrip()
            offset = len(clean) - len(after)
            if after.startswith('{'):
                arms.append((offset, blocks[offset]))
                final = True
                break
            if not after.startswith('if'):
                break
            paren = clean.find('(', offset)
            stop = _balanced(clean, paren)
            nxt = clean.find('{', stop) if stop > 0 else -1
            if nxt < 0 or nxt not in blocks:
                break
            at = nxt
        if final and all(any(_innermost(blocks, d[0]) == arm for d in defs) for arm in arms):
            out.append((begin, arms[-1][1]))
    return out


def _innermost(blocks, at):
    inside = [(o, c) for o, c in blocks.items() if o < at < c]
    return min(inside, key=lambda item: item[1] - item[0]) if inside else None


def _holds(blocks, definition, use):
    """Whether the innermost block of `definition` also holds `use` (the definition then comes first on that path)."""
    block = _enclosing(blocks, definition)
    return block is None or block[0] < use < block[1]


def _loops(clean, blocks, opening):
    """[(start of the loop's head, its closing brace)] of every braced loop."""
    out = []
    for start, end in blocks.items():
        head = clean[opening:start].rstrip()
        if head.endswith('do'):
            out.append((opening + len(head) - 2, end))
        elif head.endswith(')'):
            depth, at = 0, len(head)
            while at > 0:
                at -= 1
                depth += (head[at] == ')') - (head[at] == '(')
                if depth == 0:
                    break
            if re.search(r'\b(?:for|while)\s*$', head[:at]):
                out.append((opening + re.search(r'(?:for|while)\s*$', head[:at]).start(), end))
    return out


def _read_before_in_loop(clean, loops, local, at):
    """Whether a loop round `at` mentions the local before it: its value then comes round from the last pass."""
    return any(start < at < end and _uses(clean, local, start, at) for start, end in loops)


def _comes_round(loops, definition, uses, defs):
    """Whether one of `uses` sits in a loop that does not hold `definition` but holds another definition: from the
    second pass on that use reads the other one's value, so it cannot be renamed apart from it."""
    return any(any(start < use < end for use in uses) and any(start < d[0] < end for d in defs if d[0] != definition)
               for start, end in loops if not start < definition < end)


def _fresh(used, local):
    base = re.sub(r'\d+$', '', local) or 'v'
    number = 1 if base == 'p' and 'p' not in used else 2
    while f'{base}{number}' in used:
        number += 1
    return f'{base}{number}'


def _cursor_children(source, part, name, declared):
    out = []
    clean = part.clean
    used = set(re.findall(IDENT, clean[part.opening:part.end]))
    for hit in re.finditer(r'(?<![\w.])for\s*\(\s*;', clean[part.opening:part.end]):
        loop = part.opening + hit.start()
        open_at = clean.find('(', loop)
        close = _balanced(clean, open_at)
        if close < 0:
            continue
        pieces = clean[open_at + 1:close - 1].split(';')
        if len(pieces) != 3:
            continue
        for local, (kind, _line) in declared.items():
            if not _uses(pieces[1], local, 0, len(pieces[1])):
                continue
            at = loop
            for _ in range(4):  # the statements before the loop, nearest first
                ended = clean[:at].rstrip()
                if not ended.endswith(';'):
                    break
                stop = len(ended) - 1
                begin = max(clean.rfind(';', part.opening, stop), clean.rfind('{', part.opening, stop),
                            clean.rfind('}', part.opening, stop))
                previous = clean[begin + 1:stop]
                found = re.fullmatch(rf'(\s*){re.escape(local)}\s*=(?!=)\s*[^;{{}}]+', previous)
                if found:
                    new = _fresh(used, 'p')
                    first = begin + 1 + len(found[1])
                    where = open_at + 1
                    child = edit(source, [(first, first + len(local), new), (where, where, f'{local} = {new}')])
                    moved = view(child, name)
                    if moved:
                        out.append((FAMILY_CURSOR, _insert_declaration(child, moved, _decl_text(kind, new))))
                        beside = _insert_declaration(child, moved, _decl_text(kind, new), after=kind)
                        if (FAMILY_CURSOR, beside) not in out:
                            out.append((FAMILY_CURSOR, beside))
                        used.add(new)
                    break
                if _uses(previous, local, 0, len(previous)) or re.search(r'[{}]', previous):
                    break
                at = begin + 1
    return out


def _python_balanced(clean, start):
    """The index just past the `)` that closes the `(` at `start`, or -1."""
    depth = 0
    for at in range(start, len(clean)):
        depth += {'(': 1, ')': -1}.get(clean[at], 0)
        if depth == 0:
            return at + 1
    return -1


_balanced = _python_balanced
try:  # the typed kernel (native_build.py), when it is built: same answers, the loop in C
    from . import _scan
except ImportError:
    _scan = None
if _scan is not None:
    def _balanced(clean, start):
        found = _scan.close_every(clean, start, '(', ')', True, -1)
        return _python_balanced(clean, start) if found is NotImplemented else found


def _return_type(header, callee):
    hit = re.search(rf'(?m)^\s*(?:extern\s+)?((?:(?:const|struct|unsigned)\s+)*{IDENT}[\s*]*?)\s*\b{re.escape(callee)}\s*\(', header)
    return re.sub(r'\s+', ' ', hit[1]).strip() if hit else ''


def _base_children(source, part, name, declared, header):
    out = []
    clean = part.clean
    used = set(re.findall(IDENT, clean[part.opening:part.end]))
    for hit in re.finditer(r'(?:M2C_FIELD\s*\(\s*|\*\s*\(\s*[^()]*\*\s*\)\s*\(\s*\(\s*[su]8\s*\*\s*\)\s*)(?=[A-Za-z_])', clean[part.opening:part.end]):
        call_at = part.opening + hit.end()
        call = _CALL.match(clean, call_at)
        if not call or call['callee'] in _PLAIN:
            continue
        stop = _balanced(clean, call.end() - 1)
        if stop < 0:
            continue
        text = clean[call_at:stop]
        begin = max(clean.rfind(';', part.opening, call_at), clean.rfind('{', part.opening, call_at), clean.rfind('}', part.opening, call_at))
        statement = clean[begin + 1:call_at]
        if not re.fullmatch(r'\s*(?:\*\s*\(\s*[^()]*\*\s*\)\s*\(\s*\(\s*[su]8\s*\*\s*\)\s*|\(\s*\*\s*\(\s*[^()]*\*\s*\)\s*\(\s*\(\s*[su]8\s*\*\s*\)\s*|M2C_FIELD\s*\(\s*)', statement):
            continue  # the call is not the base of the statement's own store
        kind = _return_type(header, call['callee']) or 'void *'
        if not kind.endswith('*'):
            continue
        line = source.rfind('\n', 0, begin + 1 + len(statement) - len(statement.lstrip())) + 1
        indent = re.match(r'[ \t]*', source[line:])[0]
        first = begin + 1 + len(statement) - len(statement.lstrip())
        old = [local for local, (k, _l) in declared.items()
               if k.replace(' ', '').rstrip('*') == kind.replace(' ', '').rstrip('*') and k.endswith('*')][:2]
        choices = [(local, None) for local in old]
        fresh = f'temp_{len(used)}'
        choices.append((fresh, _decl_text(kind if kind.endswith('*') else kind + ' ', fresh)))
        for local, declaration in choices:
            child = edit(source, [(call_at, stop, local), (first, first, f'{local} = {text};\n{indent}')])
            if declaration:
                moved = view(child, name)
                if not moved:
                    continue
                child = _insert_declaration(child, moved, declaration)
            out.append((FAMILY_BASE, child))
    return out


def _test_children(source, part, name, declared):
    out = []
    clean = part.clean
    for local, (kind, _line) in declared.items():
        for hit in re.finditer(rf'(?<![\w.])(?<!->){re.escape(local)}\s*=(?!=)\s*(?P<call>{IDENT}\s*\()', clean[part.opening:part.end]):
            start = part.opening + hit.start()
            if clean[part.opening:start].rstrip()[-1:] not in (';', '{', '}'):
                continue
            open_at = part.opening + hit.end('call') - 1
            stop = _balanced(clean, open_at)
            if stop < 0 or clean[stop:stop + 1].strip(' \t') != ';':
                continue
            call_text = clean[part.opening + hit.start('call'):stop]
            for test in re.finditer(r'\b(?:if|while)\s*\(', clean[part.opening:part.end]):
                head = part.opening + test.end() - 1
                close = _balanced(clean, head)
                if close < 0 or head <= start <= close:
                    continue
                at = clean.find(call_text, head, close)
                if at < 0 or clean[max(head, at - 1):at].strip(' \t') in ('=',) or re.search(rf'{re.escape(local)}\s*=\s*$', clean[head:at]):
                    continue
                out.append((FAMILY_TEST, edit(source, [(at, at + len(call_text), f'({local} = {call_text})')])))
                break
    return out


def variants(source, name, header=''):
    part = view(source, name)
    if not part:
        return []
    body = part.clean[part.opening:part.end]
    if re.search(r'\b(?:volatile|asm|__asm__|goto)\b|^\s*#', body, re.M):
        return []
    declared = _locals(part)
    out = []
    out += _split_children(source, part, name, declared)
    out += _cursor_children(source, part, name, declared)
    out += _base_children(source, part, name, declared, header)
    out += _test_children(source, part, name, declared)
    return list(dict.fromkeys(item for item in out if item[1] != source))[:LIMIT]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'header'), 'archs': ('mips',)}
