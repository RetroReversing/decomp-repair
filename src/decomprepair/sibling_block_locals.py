"""Locals declared in separate inner blocks, written as one function-level local.

Under KMC GCC 2.7.2 (`-O1 -G0 -mips3 -mgp32 -mfp32`) a variable declared once per block is a new pseudo in each, local to
its block; one function-level variable is a single pseudo that lives in several blocks, which the allocator colours
differently. Two N64 object-update routines were exact apart from this:

- a 561-instruction one with the same `Rec *p = &table[e];` in four separate blocks put every element address in the
  other of two registers (180); one function-level `p` gave 0;
- a 468-instruction one declared a speed's length (`f32 dist`) in one block and a second vector length (`f32 len`) in a
  later one; the target computes both into one saved float register (130); one `dist` for the two gave 0.

`float_local_merge` and `disjoint_local_merge` pair function-level declarations only, and `declaration_scope_hoist`
moves only a name that is declared once. Two families, both for blocks neither of which holds the other, so each
variable is dead where the other is declared (a block's local starts without a value):

- `block_local_shared`: one name with one type declared in two or more such blocks becomes one function-level local
  (a declaration with an initialiser becomes an assignment, when no declaration follows it in its block);
- `block_local_merge`: two names of one type declared in two such blocks become one function-level local with the
  first name.

Hypothesis from the registers the targets use, not confirmed in the compiler's source; the judge decides."""
import re

from .declaration_scope_sink_repairs import _blocks
from .integer_repair_support import IDENT, _address_taken, edit, view

SHARED = 'block_local_shared'
MERGE = 'block_local_merge'
FAMILIES = (SHARED, MERGE)
LIMIT = 24
LINE = re.compile(rf'(?m)^(?P<indent>[ \t]*)(?P<type>(?:(?:unsigned|signed|struct)[ \t]+)*{IDENT}(?:[ \t]+|[ \t]*\*+[ \t]*))'
                  rf'(?P<rest>{IDENT}(?:[ \t]*,[ \t]*{IDENT})*|{IDENT}[ \t]*=(?!=)[^;{{}}\n]*);[ \t]*\n')
NOT_TYPES = {'return', 'goto', 'else', 'case', 'do', 'break', 'continue', 'typedef', 'extern', 'static', 'sizeof'}


def _kind(text):
    return re.sub(r'\s*\*\s*', '*', ' '.join(text.split()))


def _declarations(part):
    """(declarations, blocks): every plain declaration line at the head of a block of the function."""
    clean = part.clean
    blocks = [(a, b) for a, b in _blocks(clean, part.opening, part.end)
              if not re.search(r'\b(?:struct|union|enum)\b[^{};()=]*$', clean[max(0, a - 120):a])]
    found = []
    for hit in LINE.finditer(clean, part.opening + 1, part.end):
        words = re.findall(IDENT, hit['type'])
        if not words or words[0] in NOT_TYPES:
            continue
        holders = [b for b in blocks if b[0] < hit.start() < b[1]]
        if not holders:
            continue
        block = max(holders)
        before = clean[block[0] + 1:hit.start()]
        if LINE.sub('', before).strip():
            continue  # not among the block's leading declarations
        name, eq, _value = hit['rest'].partition('=')
        names = [name.strip()] if eq else [n.strip() for n in hit['rest'].split(',')]
        for name in names:
            found.append({'name': name, 'type': _kind(hit['type']), 'hit': hit, 'names': names,
                          'init': bool(eq), 'block': block})
    return found, blocks


def _disjoint(a, b):
    return a[1] < b[0] or b[1] < a[0]


def variants(source, name):
    part = view(source, name)
    if not part or re.search(r'\b(?:asm|__asm__|setjmp|longjmp|goto)\b|^\s*#', part.body, re.M):
        return []
    clean = part.clean
    found, blocks = _declarations(part)
    top = (part.opening, max(b for a, b in blocks if a == part.opening)) if any(a == part.opening for a, _ in blocks) else None
    inner = [d for d in found if d['block'][0] != part.opening]
    if not top or not inner:
        return []
    taken = {d['name'] for d in found if _address_taken(part.body, d['name'])}
    by_name = {}
    for d in found:
        by_name.setdefault(d['name'], []).append(d)

    def movable(entry):
        """Every declaration of this one name can leave its block."""
        for d in entry:
            if d['init']:
                rest = clean[d['hit'].end():d['block'][1]]
                if LINE.match(rest):
                    return False  # a statement may not stand before a later declaration
        return True

    def one_type(entry):
        return len({d['type'] for d in entry}) == 1

    last_top = max((d['hit'].end() for d in found if d['block'][0] == part.opening), default=None)
    if last_top is None:
        last_top = clean.index('\n', part.opening) + 1

    def child(drop, rename):
        """Declarations in `drop` leave their blocks and are declared once at the top; `rename` maps
        (name, block) to the name its mentions take."""
        edits, lines = [], {}
        declared = {d['name'] for d in found if d['block'][0] == part.opening}
        by_line = {}
        for d in drop:
            by_line.setdefault(d['hit'].start(), []).append(d)
            new = rename.get((d['name'], d['block']), d['name'])
            if new not in declared:
                kind = d['type']
                star = len(kind) - len(kind.rstrip('*'))
                lines[new] = f'    {kind.rstrip("*")} {"*" * star}{new};\n'
        for start, gone in by_line.items():
            d = gone[0]
            hit = d['hit']
            if d['init']:
                new = rename.get((d['name'], d['block']), d['name'])
                value = source[hit.start('rest'):hit.end('rest')].partition('=')[2].strip()
                edits.append((hit.start(), hit.end(), f'{hit["indent"]}{new} = {value};\n'))
            else:
                rest = [n for n in d['names'] if n not in {g['name'] for g in gone}]
                if rest:
                    edits.append((hit.start('rest'), hit.end('rest'), ', '.join(rest)))
                else:
                    edits.append((hit.start(), hit.end(), ''))
        for (old, block), new in rename.items():
            if old == new:
                continue
            for m in re.finditer(rf'(?<![\w.>]){re.escape(old)}\b', clean[block[0]:block[1]]):
                at = block[0] + m.start()
                if not any(d['hit'].start() <= at < d['hit'].end() and not d['init'] for d in drop):
                    if not any(d['init'] and d['name'] == old and at == d['hit'].start('rest') for d in drop):
                        edits.append((at, at + len(old), new))
        edits.append((last_top, last_top, ''.join(lines.values())))
        return edit(source, edits)

    shared = []
    for local, entry in by_name.items():
        if local in taken or len(entry) < 2 or not one_type(entry) or any(d['block'][0] == part.opening for d in entry):
            continue
        if all(_disjoint(a['block'], b['block']) for i, a in enumerate(entry) for b in entry[i + 1:]) and movable(entry):
            shared.append(entry)
    out = []
    if len(shared) > 1:
        out.append((SHARED, child([d for entry in shared for d in entry], {})))
    out += [(SHARED, child(entry, {})) for entry in shared]

    pairs = []
    single = {n: e[0] for n, e in by_name.items() if len(e) == 1 and n not in taken}
    for a in single.values():
        for b in single.values():
            if a['type'] != b['type'] or a['hit'].start() >= b['hit'].start() or b['block'][0] == part.opening:
                continue
            if a['block'][0] == part.opening:
                continue  # a function-level partner is `float_local_merge`'s and `disjoint_local_merge`'s job
            if not _disjoint(a['block'], b['block']) or not movable([a]) or not movable([b]):
                continue
            pairs.append((b['block'][0] - a['block'][1], a['hit'].start(), a, b))
    pairs.sort(key=lambda p: (p[0], p[1]))
    for _gap, _at, a, b in pairs[:LIMIT]:
        out.append((MERGE, child([a, b], {(b['name'], b['block']): a['name']})))
    return list(dict.fromkeys(out))[:LIMIT + 6]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'order': 900}
