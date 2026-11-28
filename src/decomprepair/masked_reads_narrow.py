"""A word counter that is only ever read under a halfword or byte mask, declared that narrow.

m2c has no type for a counter that lives in a saved register, so a `u16 i` comes back as `s32 var_s0` with every read
written `var_s0 & 0xFFFF`. The words are equal; the register is not: a word set to 0 is a known zero the compiler
reuses for a later zero argument (`move $a1,$s0` where the target has `move $a1,$zero`), while an HImode counter is
not substituted into a word. An 84-instruction N64 function (SN GCC 2.8.1 `-G0 -mips3 -O2`) went 45 -> 20 on this
step alone, and 0 with the argument its calls were short of.

`masked_reads_narrow` offers, for each signed word local (declared once, no initialiser, its address never taken)
whose reads are all `v & 0xFFFF` (or `v & 0xFF`, or the matching cast) and whose writes are a literal that fits,
`+=`, `-=`, `++` or `--` (a statement of its own or a whole clause of a `for` header), the local declared `u16` (`u8`) with the masks dropped, one child per local and one with all
of them. The values read are unchanged, and a `u16`/`u8` read is promoted to `int`, the type the masked word had, so
the program means the same. A read inside a subscript
(`table[v & 0xFFFF]`) and a counter kept by a `for` header count too (a 297-instruction N64 entity-list update:
320 -> 0 with both). `variants` returns [(family, source)]."""
import re

from .csource import _blank, find
from .pattern_repairs import close

FAMILY = 'masked_reads_narrow'
FAMILIES = (FAMILY,)
LIMIT = 6
_DECL = re.compile(r'(?<=[;{}])(?P<space>\s*)(?P<type>s32|int|signed\s+int|long)\s+(?P<name>[A-Za-z_]\w*)\s*;')
_MASKS = {0xFF: 'u8', 0xFFFF: 'u16'}
_NUMBER = r'(?:0[xX][0-9a-fA-F]+|\d+)'


def _uses(clean, var, start, end, decl):
    """(kind, [(start, end) of each masked read]) when every use of `var` allows the narrow type, else None."""
    kinds, reads = set(), []
    writes = []
    taken = []
    masked = re.compile(rf'(?<![\w.>])(?:{var}\s*&\s*(?P<mask>{_NUMBER})[uU]?(?!\w)|\(\s*(?P<cast>u8|u16)\s*\)\s*{var}\b)')
    for hit in masked.finditer(clean, start, end):
        if hit['mask']:
            kind = _MASKS.get(int(hit['mask'], 0))
            before = clean[start:hit.start()].rstrip()
            after = clean[hit.end():end].lstrip()
            # `&` binds looser than arithmetic and comparisons: only a whole operand is the counter's own mask
            plain = before.endswith(('(', ',', '{', ';', '[')) or re.search(r'(?<![=!<>+\-*/%&|^])=$', before)
            if not plain or not after.startswith((')', ',', ';', ']')):
                return None
        else:
            kind = hit['cast']
        if not kind:
            return None
        kinds.add(kind)
        reads.append((hit.start(), hit.end()))
        taken.append((hit.start(), hit.end()))
    if len(kinds) != 1:
        return None
    kind = kinds.pop()
    limit = 0xFF if kind == 'u8' else 0xFFFF
    headers = []
    for loop in re.finditer(r'(?<![\w.>])for\s*\(', clean[:end]):
        after_paren = close(clean, loop.end() - 1)
        if loop.start() >= start and after_paren:
            headers.append((loop.end(), after_paren - 1))
    for hit in re.finditer(rf'(?<![\w.>]){var}\b', clean[:end]):
        at = hit.start()
        if at < start or decl.start() <= at < decl.end() or any(a <= at < b for a, b in taken):
            continue
        before = clean[start:at].rstrip()
        after = clean[hit.end():end]
        stepped = re.match(rf'\s*(?:\+\+|--|[-+]=\s*{_NUMBER}\s*(?=[;,)]))', after)
        prefixed = before.endswith(('++', '--'))
        stored = re.match(rf'\s*=\s*(?P<k>{_NUMBER})\s*;', after)
        statement = before.endswith((';', '{', '}', ')', ':')) or before.endswith('else')
        if any(a <= at < b for a, b in headers):
            if _header_write(clean, before, after, limit):
                writes.append(at)
                continue
            return None
        if prefixed:
            statement = before[:-2].rstrip().endswith((';', '{', '}', ')', ':'))
            rest = after.lstrip()
            if statement and rest.startswith((';', ')')):
                writes.append(at)
                continue
            return None
        if statement and stepped and clean[hit.end() + stepped.end():end].lstrip().startswith((';', ')')):
            writes.append(at)
        elif statement and stored and int(stored['k'], 0) <= limit:
            writes.append(at)
        else:
            return None
    return (kind, reads) if reads and writes else None


def _header_write(clean, before, after, limit):
    """Whether the counter is set or stepped as a whole clause of a `for (...)` header, its value unused there."""
    alone = before.endswith(('(', ';', ','))
    stored = re.match(rf'\s*=\s*(?P<k>{_NUMBER})\s*[;,]', after)
    if alone and stored:
        return int(stored['k'], 0) <= limit
    if before.endswith(('++', '--')):
        return before[:-2].rstrip().endswith(('(', ';', ',')) and after.lstrip().startswith((';', ',', ')'))
    return alone and bool(re.match(rf'\s*(?:\+\+|--|[-+]=\s*{_NUMBER})\s*[;,)]', after))


def variants(source, name):
    span = find(source, name)
    if not span:
        return []
    clean = _blank(source)
    opening = clean.find('{', span[0], span[1])
    end = close(clean, opening, '{', '}') if opening >= 0 else None
    if not end or '#' in clean[opening:end]:
        return []
    plans, seen = [], set()
    for decl in _DECL.finditer(clean, opening, end):
        var = decl['name']
        if var in seen or re.search(rf'(?<![&\w\])])&\s*{var}\b', clean[opening:end]):
            continue
        seen.add(var)
        found = _uses(clean, var, opening + 1, end, decl)
        if found:
            kind, reads = found
            plans.append([(decl.start('type'), decl.end('type'), kind)] + [(a, b, var) for a, b in reads])

    def apply(edits):
        text = source
        for a, b, new in sorted(edits, reverse=True):
            text = text[:a] + new + text[b:]
        return text

    out = []
    if len(plans) > 1:
        out.append(apply([edit for plan in plans for edit in plan]))
    out += [apply(plan) for plan in plans]
    return [(FAMILY, text) for text in dict.fromkeys(out) if text != source][:LIMIT]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'order': 95}  # registry.py
