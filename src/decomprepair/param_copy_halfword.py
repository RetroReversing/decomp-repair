"""Word parameters that reach a call only through a `& 0xFFFF` copy: declared `u16` with their copies in the original.

m2c declares a parameter the target only ever hands on masked as `s32`, copies it into a word local and masks at the
call:

    void f(..., s32 arg1, s32 arg2, s32 arg3, ...) {
        s1 = arg1; s2 = arg2;
        do { g(&val, s1 & 0xFFFF, s2 & 0xFFFF, ...); s1 += arg3; } while (...);

param_copy_halfword
    Every word parameter copied (`L = P;`) into a word local whose reads as a call argument are `L & 0xFFFF` is
    declared `u16` with its local, the masks dropped, together with each word parameter added into such a local (in one
    child, since each alone is not the measured step). A second child writes the sum as `L = P + L` (the target's
    operand order of that `addu`).

Measured on one match (KMC gcc 2.7.2, `-G0 -mips3 -mgp32 -mfp32 -O1`, a digit-string drawer): a late parameter copy
and the add's operand order, 540 -> 205 with the sum swapped. Parameters are taken as one register each, so a signature
with `double`, `long long` or `float` parameters is left alone. The exact judge decides every child."""
import re

from .csource import _blank, find
from .integer_repair_support import IDENT, edit, split_args
from .pattern_repairs import close

FAMILY = 'param_copy_halfword'
FAMILIES = (FAMILY,)
WORD = r'(?:s32|u32|int|unsigned\s+int|unsigned)'
MASK = r'(?:0[xX][Ff]{4}\b|65535\b)'


def variants(source, name):
    span = find(source, name)
    if not span:
        return []
    clean = _blank(source)
    opening = clean.find('{', span[0], span[1])
    head = re.search(r'\b' + re.escape(name) + r'\s*\(', clean[span[0]:opening]) if opening >= 0 else None
    if not head or '#' in clean[opening:span[1]]:
        return []
    start = span[0] + head.end() - 1
    end = close(clean, start)
    if not end:
        return []
    params = {}
    for a, b in split_args(clean[start + 1:end - 1]):
        low, high = start + 1 + a, start + 1 + b
        if re.search(r'\b(?:f32|f64|float|double|long\s+long|s64|u64)\b', clean[low:high]):
            return []
        declared = re.fullmatch(r'\s*(' + WORD + r')\s+(' + IDENT + r')\s*', clean[low:high])
        if declared:
            params[declared[2]] = (low + declared.start(1), low + declared.end(1))
    body = clean[opening:span[1]]
    locals_ = {}
    for hit in re.finditer(r'(?m)^[ \t]*(' + WORD + r')\s+(' + IDENT + r')\s*;', body):
        locals_[hit[2]] = (opening + hit.start(1), opening + hit.end(1))
    edits, copied, wide = [], [], set()
    for local, place in locals_.items():
        sources = [p for p in params if re.search(r'(?<![\w.>])' + local + r'\s*=\s*' + p + r'\s*;', body)]
        masked = list(re.finditer(r'(?<=[(,])\s*(' + local + r'\s*&\s*' + MASK + r')(?=\s*[,)])', body))
        if len(sources) != 1 or not masked:
            continue
        # any other call argument that reads the local unmasked needs the word
        if re.search(r'[(,]\s*' + local + r'\s*[,)]', body):
            continue
        copied.append(local)
        wide.add(sources[0])
        edits.append((*place, 'u16'))
        edits += [(opening + m.start(1), opening + m.end(1), local) for m in masked]
    if not copied:
        return []
    sums = []
    for local in copied:
        for hit in re.finditer(r'(?<![\w.>])' + local + r'\s*\+=\s*(' + IDENT + r')\s*;', body):
            if hit[1] in params:
                wide.add(hit[1])
                sums.append((opening + hit.start(), opening + hit.end(), f'{local} = {hit[1]} + {local};'))
    edits += [(*params[p], 'u16') for p in sorted(wide)]
    result = [(FAMILY, edit(source, edits))]
    if sums:
        result.append((FAMILY, edit(source, edits + sums)))
    return result


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}
