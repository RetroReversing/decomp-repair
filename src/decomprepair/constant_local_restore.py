"""A local that only ever holds one literal, written as that literal wherever it is read.

A search that finds a repeated literal gives it a local (`int k = 2;` at the top, then every `= 2` store reads `k`).
The local is set at entry, so the compiler loads its register in the prologue, where a program that writes the literal
loads it beside the first use. `sentinel_local_inline` writes such a local back only when it feeds `==`/`!=` compares;
one that is stored into fields had no rewrite at all. Matched on a 66-instruction N64 sound-voice initialiser (SN GCC
2.8.1 `-G0 -mips3 -O2`): the saved best's `int __repair_constant = 2;`, read by five byte stores, written as `2` took it
from 440 to 230 (the `addiu $s1, $zero, 2` left the prologue), the first of five steps to 0.

constant_local_restore
    `T v = K;` (or `T v; .. v = K;` once, before every read), `v` an integer local that is never assigned again, never
    address-taken and not `volatile`, and `K` a value `T` holds: every read written `K` and the local removed. All such
    locals at once, then each alone.

Hypothesis from one match: a constant local set far from its uses is loaded where it is set. The exact judge decides.
"""
import re

from .integer_repair_support import IDENT, view

FAMILY = 'constant_local_restore'
FAMILIES = (FAMILY,)
LIMIT = 8
_TYPE = r'(?:(?:unsigned|signed)\s+(?:char|short|int|long)|unsigned|signed|[su](?:8|16|32)|char|short|int|long)'
_LITERAL = r'-?\s*(?:0[xX][0-9A-Fa-f]+|\d+)[uUlL]*'
_RANGES = {'s8': (-128, 127), 'signed char': (-128, 127), 'u8': (0, 255), 'unsigned char': (0, 255),
           'char': (0, 127), 's16': (-32768, 32767), 'short': (-32768, 32767), 'signed short': (-32768, 32767),
           'u16': (0, 65535), 'unsigned short': (0, 65535)}
_UNSIGNED_WORD = {'u32', 'unsigned', 'unsigned int', 'unsigned long'}


def _spelling(kind, text):
    """The literal as a read of a `kind` local holding it would type it, or None when `kind` cannot hold it."""
    digits = re.sub(r'\s', '', text).rstrip('uUlL')
    value = int(digits, 16) if 'x' in digits.lower() else int(digits.lstrip('-') or '0', 10) * (-1 if digits[0] == '-' else 1)
    low, high = _RANGES.get(kind, (0, 0xFFFFFFFF) if kind in _UNSIGNED_WORD else (-0x80000000, 0x7FFFFFFF))
    if not low <= value <= high:
        return None
    if kind in _UNSIGNED_WORD:
        return digits + 'U'
    return f'({digits})' if value < 0 else digits


def _locals(source, name):
    """`(spans to remove, read spans, literal)` per qualifying local."""
    part = view(source, name)
    if not part:
        return []
    clean = part.clean
    out = []
    declaration = rf'(?m)^[ \t]*(?:register\s+)?(?P<type>{_TYPE})\s+(?P<name>{IDENT})\s*(?:=\s*(?P<value>{_LITERAL})\s*)?;[ \t]*\n?'
    for found in re.finditer(declaration, clean):
        if not part.opening < found.start() < part.end:
            continue
        local, value = found['name'], found['value']
        kind = ' '.join(found['type'].split())
        word = re.compile(rf'(?<![\w.])(?<!->){re.escape(local)}\b')
        if len(re.findall(rf'(?<![\w.]){_TYPE}[\s*]+{re.escape(local)}\b', clean[part.opening:part.end])) != 1:
            continue  # (declared again in an inner scope: the reads are not all this local's)
        removals, reads, assigned = [(found.start(), found.end())], [], found.start() if value else None
        for hit in word.finditer(clean, found.end(), part.end):
            before = clean[part.opening:hit.start()].rstrip()
            after = clean[hit.end():part.end]
            store = re.match(rf'\s*=(?!=)\s*({_LITERAL})\s*;[ \t]*\n?', after)
            if store and value is None and re.search(r'[;{}]$', before):
                line = clean.rfind('\n', 0, hit.start()) + 1
                if clean[line:hit.start()].strip():
                    break
                value, assigned = store[1], hit.start()
                removals.append((line, hit.end() + store.end()))
                continue
            written = (re.match(r'\s*(?:(?:[-+*/%&|^]|<<|>>)?=(?!=)|\+\+|--|\[|\()', after) or before.endswith(('++', '--'))
                       or (before.endswith('&') and not before.endswith('&&')
                           and not re.search(r'[\w\]]\s*&$', before)))
            if written or value is None:
                break
            reads.append((hit.start(), hit.end()))
        else:
            literal = value is not None and _spelling(kind, value)
            if literal and reads and assigned is not None:
                out.append((removals, reads, literal))
    return out


def _written(source, chosen):
    edits = []
    for removals, reads, literal in chosen:
        edits += [(a, b, '') for a, b in removals] + [(a, b, literal) for a, b in reads]
    for start, end, new in sorted(edits, reverse=True):
        source = source[:start] + new + source[end:]
    return source


def variants(source, name):
    found = _locals(source, name)
    if not found:
        return []
    choices = ([found] if len(found) > 1 else []) + [[one] for one in found]
    result = []
    for chosen in choices:
        child = _written(source, chosen)
        if child != source and child not in result:
            result.append(child)
        if len(result) >= LIMIT:
            break
    return [(FAMILY, child) for child in result]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}
