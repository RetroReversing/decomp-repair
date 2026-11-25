"""A float window clamp written the way m2c splits it, rebuilt as the compiler's own staging: reused variable split,
loaded temporaries folded into their sums, an accumulator's first sum staged in a local of its own, and the staged
sum's pair of loads and adds inside nested one-shot scopes.

KMC GCC 2.7.2 (`-G0 -mips3 -mgp32 -mfp32 -O2`), an N64 bounding-rectangle function: four `x = *p + a` sums, four
`x += 8.0f` steps, then four more sums that are each the larger of a field and a clamp (`if (a < e) a = e;`). The saved
best stood at 120 with 22 rows, every one a float register or a pair of loads in the wrong order, and each of these
edits alone left it at 120-160 (a single one of them is a worse program: 910 for the folded sums without the rest).
Together, from the saved best, 120 -> 0 in the isolated judge. Read in the 2.7.2 source and the `-dl -dg -dS` dumps
(hypotheses where marked; the sched.c rule is in the source, the priorities are measured on one function):

- **Folded sums** (`temp = *(p + 0x70); sum = a + t; sum += temp;` -> `sum = a + t + *(p + 0x70);`): a pseudo that
  holds a pure load and is read once or twice is not the same thing to `sched.c` as the inline load, whose second copy
  `cse.c` merges away. The folded statement stays at the position of the *last* operation, so the order of the
  statements is the order of their final adds.
- **A reused variable split** (`t = *(p + 0x54) + t;` -> a fresh `t2` for the new value): `t` was assigned twice, so it
  was live across blocks and left to `global.c`; the fresh name is single-set and `local-alloc.c` gives it a register
  with the other block-local values (and the sums above can fold, which they could not while `t` changed).
- **The accumulator's first sum staged** (`acc = *(p + 0x58); acc += t1; ...; acc += u;` -> `head = *(p + 0x58);
  stage = head + t1; ...; acc = stage + u;`): the first add is a block-local value of its own that sched.c places at
  the top (it only depends on the opening loads), and the accumulator is first set where the target's last add is, so
  it does not take the register that the clamp values need. No spelling that keeps `acc` set twice did it.
- **The staged add in nested `do { } while (0)` scopes** (the preceding load, and the add inside it): `flow.c` adds
  `loop_depth` to every reference inside, so in `local-alloc.c`'s `floor_log2(refs) * refs / life` the staged value and
  the one loaded just before it outrank the opening factor, and take the low registers the target has them in; the
  one-statement scope alone left the factor and a late load exchanged (50). Hypothesis from the priorities in the dump.

Only the leading straight-line run of a function in m2c's layout (one statement per line, braces on their own lines),
floats only, MIPS only (the GCC schedulers), no call or jump inside the run; a `do { } while (0)` or plain block around
a statement is flattened, and an `if (v) { s } else { s }` with the same statement in both arms (a scaffold the saved
best may carry) is read as that statement. The children are the three wrapper choices of the same rewrite (nested,
staged add alone, none); the judge decides.
"""
import re

from .integer_repair_support import IDENT, edit, view
from .line_scan import lines

FAMILY = 'float_prefix_stage'
FAMILIES = (FAMILY,)
_FLOAT = r'(?:f32|float)'
_OFFSET = r'(?:0x[0-9A-Fa-f]+|\d+)'
_CAST_LOAD = re.compile(rf'^\*\s*\(\s*\(\s*{_FLOAT}\s*\*\s*\)\s*\(\s*\(\s*\(\s*char\s*\*\s*\)\s*{IDENT}\s*\)\s*\+\s*{_OFFSET}\s*\)\s*\)$')
_FIELD_LOAD = re.compile(rf'^M2C_FIELD\(\s*{IDENT}\s*,\s*{_FLOAT}\s*\*\s*,\s*{_OFFSET}\s*\)$')
_STATEMENT = re.compile(rf'^(?P<lhs>{IDENT})\s*(?P<op>=|\+=|-=)\s*(?P<rhs>[^;{{}}]+);$')
_DECLARATION = re.compile(rf'^(?P<type>{_FLOAT})\s+(?P<names>{IDENT}(?:\s*,\s*{IDENT})*)\s*;$')
_JUMP = re.compile(r'\b(?:return|goto|break|continue|for|while|switch|case|asm|__asm__|volatile)\b')
_CALL = re.compile(rf'\b(?!M2C_FIELD\b){IDENT}\s*\(')
LIMIT = 6
FOLD_USES = 2   # a loaded temporary read once or twice; the opening factors read by four sums stay locals


def _python_unwrap(text):
    """`text` without parentheses that enclose all of it."""
    text = text.strip()
    while text.startswith('(') and text.endswith(')'):
        depth = 0
        for i, c in enumerate(text):
            depth += (c == '(') - (c == ')')
            if depth == 0 and i < len(text) - 1:
                return text
        text = text[1:-1].strip()
    return text


_unwrap = _python_unwrap
try:  # the typed kernel (native_build.py), when it is built: same answers, the loop in C
    from . import _scan
except ImportError:
    _scan = None
if _scan is not None:
    def _unwrap(text):
        found = _scan.unwrap_parens(text)
        return _python_unwrap(text) if found is NotImplemented else found


def _is_load(expression):
    text = _unwrap(expression)
    return bool(_CAST_LOAD.match(text) or _FIELD_LOAD.match(text))


def _is_atom(expression):
    text = expression.strip()
    return bool(re.fullmatch(IDENT, text) or _is_load(text))


def _names(text):
    return set(re.findall(rf'\b{IDENT}\b', text))


def _block_end(body, index):
    depth = 0
    for i in range(index, len(body)):
        depth += body[i].text.count('{') - body[i].text.count('}')
        if depth == 0:
            return i
    return None


def _flatten(body, start, stop):
    """(statements, next index) for the leading straight-line run in body[start:stop]; statements are the text of each
    simple statement in order. A one-shot `do { } while (0)`, a plain block and an `if (c) { s } else { s }` whose arms
    hold the same single statement are read through."""
    found = []
    i = start
    while i < stop:
        text = body[i].stripped
        if not text:
            i += 1
            continue
        if text in ('do', '{'):
            opening = i + 1 if text == 'do' else i
            if opening >= stop or body[opening].stripped != '{':
                break
            closing = _block_end(body, opening)
            if closing is None:
                break
            after = closing + 1
            if text == 'do':
                if after >= stop or body[after].stripped != 'while (0);':
                    break
                after += 1
            inner = _flatten(body, opening + 1, closing)
            if inner is None or inner[1] != closing:
                break
            found.extend(inner[0])
            i = after
            continue
        if re.match(r'if\s*\(', text) and i + 1 < stop and body[i + 1].stripped == '{':
            closing = _block_end(body, i + 1)
            if closing is None or closing + 2 >= stop or body[closing + 1].stripped != 'else' or body[closing + 2].stripped != '{':
                break
            end = _block_end(body, closing + 2)
            if end is None:
                break
            first = _flatten(body, i + 2, closing)
            second = _flatten(body, closing + 3, end)
            if not first or not second or first[1] != closing or second[1] != end or first[0] != second[0] or len(first[0]) != 1:
                break
            found.extend(first[0])
            i = end + 1
            continue
        hit = _STATEMENT.match(text)
        if not hit or _JUMP.search(text) or _CALL.search(hit['rhs']):
            break
        found.append(text)
        i += 1
    return found, i


def _is_declaration(text):
    return bool(re.fullmatch(r'[A-Za-z_][\w\s*,]*;', text)) and not re.match(r'(?:return|goto|break|continue)\b', text)


def _float_names(body):
    out = {}
    for line in body:
        hit = _DECLARATION.match(line.stripped)
        if hit:
            for name in re.split(r'\s*,\s*', hit['names']):
                out[name] = hit['type']
    return out


def _fresh(taken, stem):
    name, n = stem, 0
    while name in taken:
        n += 1
        name = f'{stem}_{n}'
    taken.add(name)
    return name


def _replace(text, old, new):
    return re.sub(rf'(?<![\w.]){re.escape(old)}\b(?!\s*\()', new, text)


def _parse(statement):
    hit = _STATEMENT.match(statement)
    return hit['lhs'], hit['op'], hit['rhs'].strip()


def _split_reused(items, floats, tail, taken):
    """`R = e + R;` (R set before and read here): the new value under a fresh name; later reads are renamed."""
    for k, (lhs, op, rhs) in enumerate(items):
        if op != '=' or lhs not in floats or not re.search(rf'(?<![\w.]){lhs}\b', rhs) or not any(
                i[0] == lhs for i in items[:k]) or not _is_load(re.sub(rf'\s*\+\s*{lhs}\b|{lhs}\s*\+\s*', '', rhs, count=1)):
            continue
        if re.search(rf'(?<![\w.]){lhs}\s*(?:[-+]?=)(?!=)', tail) or re.search(rf'\b{lhs}\s*(?:\+\+|--)', tail):
            continue
        fresh = _fresh(taken, f'{lhs}_next')
        floats[fresh] = floats[lhs]
        items[k][0] = fresh
        for later in items[k + 1:]:
            later[0] = _replace(later[0], lhs, fresh)
            later[2] = _replace(later[2], lhs, fresh)
        return fresh, lhs, floats[lhs]
    return None


def _fold(items, floats, tail, keep=()):
    """Pure-load temporaries read only inside the run go inline; `Y = e1; ...; Y op= e2;` merge at the later statement."""
    changed = True
    while changed:
        changed = False
        for k, (lhs, op, rhs) in enumerate(items):
            if op != '=' or lhs not in floats or lhs in keep or not _is_load(rhs):
                continue
            if sum(1 for i in items if i[0] == lhs) != 1 or re.search(rf'(?<![\w.]){lhs}\b', tail):
                continue
            uses = [i for i in items[k + 1:] if re.search(rf'(?<![\w.]){lhs}\b', i[2])]
            if not uses or len(uses) > FOLD_USES or any(re.search(rf'(?<![\w.]){lhs}\b', i[2]) for i in items[:k]):
                continue
            for i in uses:
                i[2] = _replace(i[2], lhs, f'({rhs.strip()})' if not rhs.strip().startswith('(') else rhs.strip())
            del items[k]
            changed = True
            break
    merged = True
    while merged:
        merged = False
        for k, (lhs, op, rhs) in enumerate(items):
            if op != '=' or lhs not in floats or re.search(rf'(?<![\w.]){lhs}\b', rhs):
                continue
            for m in range(k + 1, len(items)):
                lhs2, op2, rhs2 = items[m]
                if lhs2 == lhs and op2 in ('+=', '-='):
                    between = items[k + 1:m]
                    needs = _names(rhs)
                    if any(re.search(rf'(?<![\w.]){lhs}\b', i[2]) or i[0] == lhs or i[0] in needs for i in between):
                        break
                    if not _is_atom(rhs2) and not re.fullmatch(r'\(.*\)', rhs2.strip()):
                        break
                    sign = '+' if op2 == '+=' else '-'
                    items[m] = [lhs, '=', f'{rhs} {sign} {rhs2.strip()}']
                    del items[k]
                    merged = True
                    break
                if lhs2 == lhs:
                    break
            if merged:
                break
    return items


def _stage(items, floats, taken):
    """`acc = load; acc += a; ...; acc += b;` -> head / stage / sum under fresh names; the (head, stage) names."""
    for k, (lhs, op, rhs) in enumerate(items):
        if op != '=' or lhs not in floats or not _is_load(rhs) or sum(1 for i in items if i[0] == lhs) != 3:
            continue
        positions = [m for m, i in enumerate(items) if i[0] == lhs]
        if positions[0] != k or [items[m][1] for m in positions] != ['=', '+=', '+=']:
            continue
        first_add, second_add = positions[1], positions[2]
        if any(re.search(rf'(?<![\w.]){lhs}\b', i[2]) for i in items[:second_add] if i[0] != lhs):
            continue
        if any(re.search(rf'(?<![\w.]){lhs}\b', i[2]) for i in items[second_add + 1:] if i[0] == lhs):
            continue
        head, stage = _fresh(taken, f'{lhs}_head'), _fresh(taken, f'{lhs}_stage')
        floats[head] = floats[stage] = floats[lhs]
        add = items[first_add][2]
        items[k] = [head, '=', rhs]
        items[first_add] = [stage, '=', f'{head} + {add}']
        items[second_add] = [lhs, '=', f'{stage} + {items[second_add][2]}']
        return first_add, (head, stage, floats[lhs])
    return None


def _emit(items, indent, staged, shape):
    """The run's lines; `shape` is 'nest' (the load before the staged add and the add, nested), 'add' or 'plain'."""
    pad = indent
    rows = [f'{pad}{lhs} {op} {rhs};' for lhs, op, rhs in items]
    if staged is None or shape == 'plain':
        return rows
    k = staged
    if shape == 'add':
        rows[k:k + 1] = [f'{pad}do {{', f'{pad}  {rows[k].strip()}', f'{pad}}} while (0);']
        return rows
    if k == 0:
        return None
    rows[k - 1:k + 1] = [f'{pad}do {{', f'{pad}  {rows[k - 1].strip()}', f'{pad}  do {{', f'{pad}    {rows[k].strip()}',
                         f'{pad}  }} while (0);', f'{pad}}} while (0);']
    return rows


def variants(source, name):
    part = view(source, name)
    if not part or re.search(r'\b(?:asm|__asm__|goto|volatile)\b|^\s*#|\b(?:for|switch)\b|\bwhile\s*\((?!0\))', part.body, re.M):
        return []
    body = lines(part, source)
    floats = _float_names(body)
    if not floats:
        return []
    first = next((i for i, line in enumerate(body) if line.stripped and not _is_declaration(line.stripped)), None)
    if first is None:
        return []
    statements, stop = _flatten(body, first, len(body))
    if len(statements) < 8 or stop <= first:
        return []
    start, end = body[first].start, body[stop - 1].end
    tail = source[end:part.end]
    indent = body[first].indent
    taken = set(re.findall(rf'\b{IDENT}\b', part.clean[part.opening:part.end]))
    items = [list(_parse(s)) for s in statements]
    renamed = _split_reused(items, floats, tail, taken)
    staged = _stage(items, floats, taken)
    items = _fold(items, floats, tail, keep=(staged[1][0],) if staged else ())
    if not renamed and not staged:
        return []
    declarations = []
    new_floats = []
    if renamed:
        new_floats.append(renamed[0])
        declarations.append((renamed[0], renamed[2]))
    if staged:
        new_floats.extend(staged[1][:2])
        declarations.extend((n, staged[1][2]) for n in staged[1][:2])
    renamed_tail = _replace(tail, renamed[1], renamed[0]) if renamed else tail
    last_declaration = max((i for i, line in enumerate(body[:first]) if _DECLARATION.match(line.stripped)), default=None)
    at = body[last_declaration].end if last_declaration is not None else body[first].start
    declared = ''.join(f'{indent}{kind} {n};\n' for n, kind in declarations)
    out = []
    for shape in (('nest', 'add', 'plain') if staged else ('plain',)):
        rows = _emit([tuple(i) for i in items], indent, staged[0] if staged else None, shape)
        if rows is None:
            continue
        edits = [(at, at, declared), (start, end, '\n'.join(rows) + '\n')]
        if renamed_tail != tail:
            edits.append((end, part.end, renamed_tail))
        text = edit(source, edits)
        if text != source:
            out.append((FAMILY, text))
    return out[:LIMIT]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'archs': ('mips',)}
