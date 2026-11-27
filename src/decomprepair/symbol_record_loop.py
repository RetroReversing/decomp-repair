"""Fields of a global record array written through their own symbols and a hand-stepped byte offset, as `table[i].field`.

A draft (and the searches after it) keeps one `char` array per field address and walks them with a byte offset that
steps by the record's size beside the loop's counter, stores as well as loads, sometimes two such offsets at once:

    off = 0;  far = 0;                                    for (i = 0; i < 2; i++) {
    for (i = 0; i < 2; i++) {                                 table[i].x_44 = 0;
        *((s32 *) (D_8000A054 + off)) = 0;            ->      table[i].x_10 = 2;
        *((s32 *) (D_8000A010 + off)) = 2;                    ...
        *((s32 *) (D_8000C000 + far)) = 0;                    other[i].x_0 = 0;
        far += 0x184;  off += 0x58;                       }
    }

The record's first byte need not be any symbol the code names: a header the loop never writes sits before the lowest
field. Where it starts changes the bytes (GCC 2.7.2 tells the stores apart by `symbol + constant`, so a field at offset
0 of the array is scheduled differently from one at offset 16), so children try the base at the lowest symbol and a few
bytes before it. `record_field_array` reads one offset's loads spelled `(char *)&D + off`; this takes the plain `char`
array spellings, writes, several offsets and single-field records.

The same drafts spell the distance between two symbols as `(u32) (f + 0xD0) - (u32) f` with `f` a `char` array, which
the compiler folds to the constant; the game named the second symbol, so both addresses are loaded and subtracted
(`symbol_difference`). Around them: `do { } while (0)` fences are opened, an `if (off) { S } else { S }` left on the
dead offset is written once, and a local holding the difference and read once is written at its use.

One function (a 158-instruction N64 audio manager set-up, `gcc-2.7.2-kmc -G0 -mips3 -mgp32 -mfp32 -O2`): saved best
990, no family chain below 785; the combined child here is exact. Candidates for the exact judge, never a verdict."""
import re

from .csource import _blank, find
from .identical_arm_collapse_repairs import variants as collapse_arms
from .pattern_repairs import close
from .scaffold_strip import unfence

FAMILY = 'symbol_record_loop'
DIFFERENCE = 'symbol_difference'
FAMILIES = (FAMILY, DIFFERENCE)
LOWS = (0, 16, 8, 4)
SIZE = {'s8': 1, 'u8': 1, 'char': 1, 's16': 2, 'u16': 2, 'short': 2, 's32': 4, 'u32': 4, 'int': 4, 'f32': 4,
        'float': 4}
BYTES = r'(?:char|u8|s8|unsigned\s+char|signed\s+char)'
NAMED = r'(?:D|func)_[0-9A-Fa-f]{8}'


def _byte_arrays(clean):
    """The address-named symbols declared as byte arrays."""
    return set(re.findall(rf'\bextern\s+{BYTES}\s+({NAMED})\s*\[\s*\]\s*;', clean))


def _body_span(source, name):
    span = find(source, name)
    if not span:
        return None
    clean = _blank(source)
    opening = clean.find('{', span[0], span[1])
    end = close(clean, opening, '{', '}') if opening >= 0 else None
    return (clean, span[0], opening, end) if end else None


def _loop_at(clean, at, start, end):
    """(head, open, close) of the innermost braced `for`/`while`/`do` body around `at`."""
    best = None
    for m in re.finditer(r'\b(for|while|do)\b', clean[start:end]):
        head = start + m.start()
        if m[1] == 'do':
            body = clean.find('{', head)
            if body < 0 or clean[head + 2:body].strip():
                continue
        else:
            paren = clean.find('(', head)
            stop = close(clean, paren, '(', ')') if paren >= 0 else None
            if not stop:
                continue
            body = stop
            while body < end and clean[body].isspace():
                body += 1
            if body >= end or clean[body] != '{':
                continue
        tail = close(clean, body, '{', '}')
        if tail and body < at < tail and (best is None or body > best[1]):
            best = (head, body, tail)
    return best


def _counter(clean, head, body, tail, opening):
    """The loop's counter: started at 0 before the body and stepped by one in the header or the body."""
    step = r'(?:\+\+\s*([A-Za-z_]\w*)|([A-Za-z_]\w*)\s*(?:\+\+|\+=\s*1[uU]?(?!\w)))'
    found = []
    if clean[head:head + 3] == 'for':
        parts = clean[clean.find('(', head) + 1:body].rsplit(')', 1)[0].split(';')
        if len(parts) == 3:
            m = re.fullmatch(rf'\s*{step}\s*', parts[2])
            if m:
                found.append(m[1] or m[2])
    found += [m[1] or m[2] for m in re.finditer(rf'(?m)^[ \t]*{step}\s*;', clean[body:tail])]
    for name in found:
        if re.search(rf'(?<![\w.>]){name}\s*=\s*0[uU]?\s*[;,)]', clean[opening:body]):
            return name
    return None


def _offsets(source, name):
    """Every hand-stepped offset that only ever indexes byte-array symbols: its accesses, step, set-up and counter."""
    part = _body_span(source, name)
    if not part:
        return []
    clean, _, opening, end = part
    arrays = _byte_arrays(clean)
    out = []
    for step in re.finditer(r'(?<![\w.>])(?P<off>[A-Za-z_]\w*)\s*\+=\s*(?P<k>0[xX][0-9A-Fa-f]+|\d+)\s*;',
                            clean[opening:end]):
        off, size, at = step['off'], int(step['k'], 0), opening + step.start()
        loop = _loop_at(clean, at, opening, end)
        if not loop or size < 2:
            continue
        head, body, tail = loop
        access = re.compile(rf'\*\s*\(\s*\(\s*(?P<type>\w+)\s*\*\s*\)\s*\(\s*(?P<sym>{NAMED})\s*\+\s*{off}\s*\)\s*\)'
                            rf'|\*\s*\(\s*(?P<type2>\w+)\s*\*\s*\)\s*\(\s*(?P<sym2>{NAMED})\s*\+\s*{off}\s*\)')
        reads = [(opening + m.start(), opening + m.end(), m['sym'] or m['sym2'], m['type'] or m['type2'])
                 for m in access.finditer(clean[opening:end])]
        if not reads or any(not body < a < tail or sym not in arrays or kind not in SIZE for a, _, sym, kind in reads):
            continue
        uses = list(re.finditer(rf'(?<![\w.>]){off}\b', clean[opening:end]))
        decl = list(re.finditer(rf'(?m)^[ \t]*[A-Za-z_]\w*[ \t]+{off}[ \t]*;[ \t]*\n?', clean[opening:end]))
        init = list(re.finditer(rf'(?m)(?<![\w.>]){off}[ \t]*=[ \t]*0[ \t]*;[ \t]*\n?', clean[opening:body]))
        if len(init) != 1 or len(decl) != 1 or len(uses) != len(reads) + 3:
            continue
        counter = _counter(clean, head, body, tail, opening)
        if not counter or counter == off:
            continue
        fields = {}
        for _, _, sym, kind in reads:
            fields.setdefault(int(sym.rsplit('_', 1)[1], 16), set()).add((sym, kind))
        if any(len({kind for _, kind in found}) != 1 for found in fields.values()):
            continue
        edits = [(at, opening + step.end(), ''),
                 (opening + init[0].start(), opening + init[0].end(), ''),
                 (opening + decl[0].start(), opening + decl[0].end(), '')]
        out.append({'off': off, 'size': size, 'counter': counter, 'reads': reads, 'edits': edits,
                    'fields': {a: next(iter(found)) for a, found in fields.items()}})
    return out


def _records(source, name, low):
    """The function with every stepped offset written as a record array, its base `low` bytes before the lowest field
    (a record of one field keeps its own symbol), or None."""
    found = _offsets(source, name)
    if not found:
        return None
    edits, typedefs, moved = [], [], False
    for item in found:
        lowest = min(item['fields'])
        back = low if len(item['fields']) > 1 else 0
        base = lowest - back
        layout = sorted((address - base, kind) for address, (_, kind) in item['fields'].items())
        size = item['size']
        if any(o % SIZE[t] or o + SIZE[t] > size for o, t in layout) or size % max(SIZE[t] for _, t in layout):
            return None
        prefix = item['fields'][lowest][0].split('_')[0]
        symbol = f'{prefix}_{base:08X}'
        record = f'Rec_{symbol}'
        if re.search(rf'\b{record}\b', source):
            return None
        members, cursor = [], 0
        for o, t in layout:
            if o < cursor:
                return None
            if o > cursor:
                members.append(f'char pad_{cursor:X}[{o - cursor}];')
            members.append(f'{t} x_{o:X};')
            cursor = o + SIZE[t]
        if cursor < size:
            members.append(f'char pad_{cursor:X}[{size - cursor}];')
        moved = moved or back > 0
        typedefs.append((symbol, f'typedef struct {{ {" ".join(members)} }} {record};\nextern {record} {symbol}[];\n'))
        edits += item['edits']
        edits += [(a, b, f'{symbol}[{item["counter"]}].x_{int(sym.rsplit("_", 1)[1], 16) - base:X}')
                  for a, b, sym, _ in item['reads']]
    if low and not moved:
        return None
    text = source
    for a, b, new in sorted(edits, reverse=True):
        text = text[:a] + new + text[b:]
    for symbol, typedef in typedefs:
        declared = re.compile(rf'(?m)^[ \t]*extern\s+{BYTES}\s+{symbol}\s*\[\s*\]\s*;[ \t]*\n')
        clean = _blank(text)
        uses = len(re.findall(rf'\b{symbol}\b', clean))
        m = declared.search(clean)
        if m and uses == 1 + len(re.findall(rf'\b{symbol}\s*\[\s*[A-Za-z_]\w*\s*\]\s*\.', clean)):
            text = text[:m.start()] + typedef + text[m.end():]
        elif m or re.search(rf'\bextern\b[^;\n]*\b{symbol}\b', clean):
            return None
        else:
            span = find(text, name)
            text = text[:span[0]] + typedef + text[span[0]:]
    return text


def _difference(source, name):
    """`(T) (f + N) - (T) f` over a byte array `f` written with the symbol at `f + N`, or None."""
    part = _body_span(source, name)
    if not part:
        return None
    clean, start, opening, end = part
    arrays = _byte_arrays(clean)
    cast = r'\(\s*\w+(?:\s*\*)?\s*\)'
    pattern = re.compile(rf'\(\s*(?P<c1>{cast})\s*\(\s*(?P<sym>{NAMED})\s*\+\s*(?P<n>0[xX][0-9A-Fa-f]+|\d+)\s*\)\s*\)'
                         rf'\s*-\s*\(\s*(?P<c2>{cast})\s*(?P=sym)\s*\)')
    edits, added = [], []
    for m in pattern.finditer(clean, opening, end):
        sym = m['sym']
        if sym not in arrays:
            continue
        prefix, address = sym.split('_')
        other = f'{prefix}_{int(address, 16) + int(m["n"], 0):08X}'
        edits.append((m.start(), m.end(), f'({m["c1"]} {other}) - ({m["c2"]} {sym})'))
        if other not in arrays and other not in added:
            added.append(other)
    if not edits:
        return None
    text = source
    for a, b, new in reversed(edits):
        text = text[:a] + new + text[b:]
    if added:
        text = text[:start] + ''.join(f'extern char {other}[];\n' for other in added) + text[start:]
    return text


def _inline_difference(source, name):
    """A local set once to a difference of two symbols and read once, written at its use; or None."""
    part = _body_span(source, name)
    if not part:
        return None
    clean, _, opening, end = part
    value = rf'\(\s*\(\s*\w+\s*\)\s*{NAMED}\s*\)\s*-\s*\(\s*\(\s*\w+\s*\)\s*{NAMED}\s*\)'
    for m in re.finditer(rf'(?m)^[ \t]*(?P<local>[A-Za-z_]\w*)\s*=\s*(?P<value>{value})\s*;[ \t]*\n', clean[:end]):
        if m.start() < opening:
            continue
        local = m['local']
        uses = list(re.finditer(rf'(?<![\w.>]){local}\b', clean[opening:end]))
        decl = re.search(rf'(?m)^[ \t]*[A-Za-z_]\w*[ \t]+{local}[ \t]*;[ \t]*\n', clean[opening:end])
        if not decl or len(uses) != 3:
            continue
        use = opening + uses[-1].start()
        edits = [(use, use + len(local), source[m.start('value'):m.end('value')]), (m.start(), m.end(), ''),
                 (opening + decl.start(), opening + decl.end(), '')]
        text = source
        for a, b, new in sorted(edits, reverse=True):
            text = text[:a] + new + text[b:]
        return text
    return None


def _tidied(source, name):
    """Fences opened, empty `if (1) { }` dropped and identical arms written once."""
    text = unfence(source, name) or source
    text = re.sub(r'(?m)^[ \t]*if\s*\(\s*1\s*\)\s*\{\s*\}[ \t]*\n', '', text)
    collapsed = collapse_arms(text, name)
    return collapsed[-1][1] if collapsed else text


def _with_difference(text, name):
    other = _difference(text, name)
    if not other:
        return None
    return _inline_difference(other, name) or other


def variants(source, name, header=''):
    part = _body_span(source, name)
    if not part or not _byte_arrays(part[0]):
        return []
    out, seen = [], {source}

    def offer(family, text):
        if text and text not in seen:
            seen.add(text)
            out.append((family, text))

    tidy = _tidied(source, name)
    both = _with_difference(tidy, name)
    # the whole set first, then records alone and the difference alone
    for low in LOWS:
        offer(FAMILY, _records(both, name, low) if both else None)
    for low in LOWS:
        offer(FAMILY, _records(tidy, name, low))
        offer(FAMILY, _records(source, name, low))
    offer(DIFFERENCE, _with_difference(source, name))
    offer(DIFFERENCE, both)
    return out


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'header')}
