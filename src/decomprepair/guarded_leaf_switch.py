"""m2c's byte globals and its compare tree of guarded leaves, read back as arrays and a `switch`.

A 99-instruction N64 setup routine (`gcc-2.7.2-kmc -O1`) was exact from its machine draft with three edits and no
others:

- `extern M2C_UNK D;` read only as `*(&D + i)` and `M2C_FIELD(&D, u8 *, k)` is `extern u8 D[];`, `D[i]`, `D[k]`;
  a store `*(&D + i) = (s16) x` is a halfword one, `*(s16 *) (D + i) = (s16) x` (a vertex-coordinate updater's loop
  stored `sh` at stride 16; reading it as a byte left its draft's chain at 620, with the width kept it reached 0);
- inside `if (G == 1)`, a `v != G` of the dispatch is `v != 1`: m2c named the register that still held G's value;
- the dispatch, whose leaves return when the value is not theirs, is a `switch`:

      if (v != 2) { if (v >= 3) { if (v != 3) return; B3 } else { if (v != 1) return; B1 } } else { B2 }

  with its cases in ascending order (3275 -> 580 with the cases in the tree's order, 0 ascending).

The switch is only offered where nothing but closing braces follows the tree, so `break` and `return` are the same
exit. The order of the cases is a spelling, not proven by the tree: ascending first, then the order the arms appear.
"""
import re

from .csource import _blank, find
from .integer_repair_support import edit

FAMILIES = ('unknown_byte_array', 'guarded_leaf_switch')
NAME = r'D_[0-9A-Fa-f]{6,8}'
NUMBER = r'(?:0x[0-9A-Fa-f]+|\d+)'


def _pair(text, opening, left, right):
    depth = 0
    for index in range(opening, len(text)):
        if text[index] == left:
            depth += 1
        elif text[index] == right:
            depth -= 1
            if not depth:
                return index
    return None


def _byte_arrays(source, clean, span):
    """Every unknown global that is only ever a byte table, declared as one; with the compared guard constants."""
    edits, taken = [], []
    body = clean[span[0]:span[1]]
    for declaration in re.finditer(rf'^[ \t]*extern[ \t]+M2C_UNK[ \t]+({NAME})[ \t]*;', clean[:span[0]], re.M):
        name = declaration[1]
        fields = list(re.finditer(rf'M2C_FIELD\(\s*&\s*{name}\s*,\s*[su]8\s*\*\s*,\s*({NUMBER})\s*\)', body))
        indexed = []
        for hit in re.finditer(rf'\*\s*\(\s*&\s*{name}\s*\+\s*', body):
            opening = body.index('(', hit.start())
            closing = _pair(body, opening, '(', ')')
            if closing is not None:
                indexed.append((hit.start(), closing + 1, source[span[0] + hit.end():span[0] + closing].strip()))
        if not fields and not indexed:
            continue
        if len(re.findall(rf'\b{name}\b', body)) != len(fields) + len(indexed):
            continue  # another use: the declaration change would break it
        taken.append(name)
        edits.append((declaration.start(), declaration.end(), f'extern u8 {name}[];'))
        edits += [(span[0] + h.start(), span[0] + h.end(), f'{name}[{h[1]}]') for h in fields]
        for start, end, index in indexed:
            # `*(&D + i) = (s16) x`: the cast says the store is a halfword at byte offset i, not a byte
            wide = re.match(r'\s*=\s*\(\s*([su]16)\s*\)', body[end:])
            text = f'*({wide[1]} *) ({name} + {index})' if wide else f'{name}[{index}]'
            edits.append((span[0] + start, span[0] + end, text))
    if not taken:
        return None
    # m2c's `(u8)` before a byte it now reads from a byte table
    for cast in re.finditer(rf'\(u8\)\s*(?=M2C_FIELD\(\s*&\s*(?:{"|".join(taken)})\b)', body):
        edits.append((span[0] + cast.start(), span[0] + cast.end(), ''))
    return edits


def _guard_constants(source, clean, span):
    """`v != G` inside `if (G == K) {`: the K the guard proved."""
    edits = []
    body = clean[span[0]:span[1]]
    for guard in re.finditer(rf'\bif\s*\(\s*({NAME})\s*==\s*({NUMBER})\s*\)\s*\{{', body):
        end = _pair(body, guard.end() - 1, '{', '}')
        if end is None:
            continue
        for use in re.finditer(rf'(?<=[!=]= ){guard[1]}\b(?=\))', body[guard.end():end]):
            edits.append((span[0] + guard.end() + use.start(), span[0] + guard.end() + use.end(), guard[2]))
    return edits


def _block(clean, at):
    """(inside start, inside end, after) of the `{ ... }` at the next non-space of `at`."""
    opening = at + len(clean[at:]) - len(clean[at:].lstrip())
    if opening >= len(clean) or clean[opening] != '{':
        return None
    closing = _pair(clean, opening, '{', '}')
    return None if closing is None else (opening + 1, closing, closing + 1)


def _tree(source, clean, start, end, variable):
    """{case value: statements} of the dispatch in source[start:end], or None when it is anything else."""
    text = clean[start:end]
    head = re.match(rf'\s*if\s*\(\s*{re.escape(variable)}\s*(!=|>=|<)\s*({NUMBER})\s*\)\s*', text)
    if not head:
        return None
    value = int(head[2], 0)
    rest = start + head.end()
    guarded = re.match(r'(?:\{\s*return\s*;\s*\}|return\s*;)', clean[rest:end])
    if head[1] == '!=' and guarded:
        # a leaf: `if (v != K) return; BODY`
        return {value: source[rest + guarded.end():end]}
    then = _block(clean, rest)
    if not then or then[2] > end:
        return None
    other = re.match(r'\s*else\s*', clean[then[2]:end])
    if not other:
        return None
    last = _block(clean, then[2] + other.end())
    if not last or last[2] > end or clean[last[2]:end].strip():
        return None
    left = _tree(source, clean, then[0], then[1], variable)
    right = _tree(source, clean, last[0], last[1], variable)
    if head[1] == '!=':
        if value in (left or {}) or left is None:
            return None
        return {**left, value: source[last[0]:last[1]]}
    if left is None or right is None or set(left) & set(right):
        return None
    return {**left, **right}


def _switches(source, clean, span):
    out = []
    for head in re.finditer(rf'\bif\s*\(\s*({NAME}|\w+)\s*!=\s*{NUMBER}\s*\)\s*\{{', clean[span[0]:span[1]]):
        start = span[0] + head.start()
        then = _block(clean, span[0] + head.end() - 1)
        other = then and re.match(r'\s*else\s*', clean[then[2]:span[1]])
        last = other and _block(clean, then[2] + other.end())
        # nothing but closing braces after the tree: `break` and the leaves' `return` are the same exit
        if not last or clean[last[2]:span[1]].replace('}', '').strip():
            continue
        cases = _tree(source, clean, start, last[2], head[1])
        if not cases or len(cases) < 3 or any(re.search(r'\bbreak\b', _blank(v)) for v in cases.values()):
            continue
        appearance = sorted(cases, key=lambda v: source.find(cases[v], start))
        for order in dict.fromkeys((tuple(sorted(cases)), tuple(appearance))):
            arms = []
            for value in order:
                lines = [line.strip() for line in cases[value].strip().splitlines()]
                depth, kept = 0, []
                for line in lines:
                    depth -= line.startswith('}')
                    kept.append('    ' * depth + line)
                    depth += line.count('{') - line.count('}') + line.startswith('}')
                if kept and kept[-1] == 'return;':
                    kept.pop()
                arms.append(f'case {value}:\n' + ''.join(f'    {line}\n' for line in kept) + '    break;\n')
            text = f'switch ({head[1]}) {{\n' + ''.join(arms) + '}'
            out.append(('guarded_leaf_switch', source[:start] + text + source[last[2]:]))
    return out


def variants(source, name):
    """[(family, source)] for the function `name`."""
    span = find(source, name)
    if not span:
        return []
    clean = _blank(source)
    out = []
    arrays = _byte_arrays(source, clean, span)
    constants = _guard_constants(source, clean, span)
    if arrays and constants:
        out.append(('unknown_byte_array', edit(source, arrays + constants)))
    if arrays:
        out.append(('unknown_byte_array', edit(source, arrays)))
    if constants:
        out.append(('unknown_byte_array', edit(source, constants)))
    out += _switches(source, clean, span)
    return [(family, text) for family, text in dict.fromkeys(out) if text != source]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'archs': ('mips',)}
