"""A field read of a packed word that the run later overwrites in place, moved after the overwrite through a copy.

The triangle commands of a display-list interpreter (SN64 GCC 2.8.1 `-G0 -mips3 -O2 -mfp32`, 618 instructions) unpack
three 5-bit vertex indices from a 16-bit word, and the target decodes them as `srl $a2, $a1, 5; move $v0, $a1;
sra $a1, $a1, 0xa; andi $a0, $v0, 0x1f`: the word's register becomes the last field in place, and the first field is
taken from a copy made before. Written `w = word; r = w & 0x1F; k = (w >> 5) & 0x1F; w = (w >> 10) & 0x1F;` the
compiler needs no copy (the `& 0x1F` reads the word before it is overwritten) and every register after it moves. With
the first field's read after the overwrite, through a copy in a block of its own,

    { s32 w_1 = w; k = (w >> 5) & 0x1F; w = (w >> 10) & 0x1F; r = w_1 & 0x1F; }

the copy is kept (cse cannot fold it into the overwritten word) and the target's `move` comes back: 1800 -> 1780 for one
decode and 1780 -> 1685 with the second triangle's.

In a run of consecutive one-line assignments at one indent (`x = expr;`, no call, `++`/`--` or compound assignment),
for a statement `X = f(V);` (X another plain variable) followed later in the run by `V = g(V);`, where nothing
between them reads or writes X or writes anything `f` reads, the statement moves after the overwrite with `V` read
through `T V_n = V;` declared in a block around the moved statements (T is V's declared type). The program is the same
program. A candidate rewrite; the exact judge decides.
"""
import re

from .integer_repair_support import edit, view

FAMILY = 'inplace_field_copy'
FAMILIES = (FAMILY,)
LIMIT = 12
_ID = re.compile(r'[A-Za-z_]\w*')
_LINE = re.compile(r'^(?P<indent>[ \t]*)(?P<lhs>[A-Za-z_]\w*)[ \t]*=(?!=)[ \t]*(?P<rhs>[^;{}\n]+);[ \t]*$')
_CALL = re.compile(r'\b[A-Za-z_]\w*\s*\(')
_CASTS = {'char', 'u8', 's8', 'u16', 's16', 'u32', 's32', 'int', 'unsigned', 'signed', 'short', 'long', 'sizeof'}
_TYPE = r'(?:unsigned\s+(?:int|short|char|long)|signed\s+(?:int|short|char)|s32|u32|s16|u16|s8|u8|int|long|short)'
_DECL = re.compile(rf'(?m)^[ \t]*({_TYPE})[ \t]+([A-Za-z_]\w*)[ \t]*;')


def _statement(text):
    found = _LINE.match(text)
    if not found or '++' in text or '--' in text:
        return None
    if any(m.group().rstrip('( \t') not in _CASTS for m in _CALL.finditer(found.group('rhs'))):
        return None
    return found.group('indent'), found.group('lhs'), set(_ID.findall(found.group('rhs')))


def _runs(source, lo, hi):
    """Runs of consecutive simple assignments at one indent: [(start, end, indent, lhs, reads)]."""
    runs, run, at = [], [], lo
    for text in source[lo:hi].split('\n'):
        found = _statement(text)
        if found and (not run or run[-1][2] == found[0]):
            run.append((at, at + len(text), *found))
        else:
            if len(run) >= 3:
                runs.append(run)
            run = [(at, at + len(text), *found)] if found else []
        at += len(text) + 1
    if len(run) >= 3:
        runs.append(run)
    return runs


def variants(source, name):
    part = view(source, name)
    if not part:
        return []
    lo, hi = part.opening + 1, part.end - 1
    body = part.clean[lo:hi]
    if re.search(r'\bvolatile\b', body):
        return []
    types = {}
    for decl in _DECL.finditer(part.clean, lo, hi):
        types[decl.group(2)] = None if decl.group(2) in types else re.sub(r'\s+', ' ', decl.group(1))
    taken = set(_ID.findall(source))
    out = []
    for run in _runs(source, lo, hi):
        for j, (_, _, _, var, reads_j) in enumerate(run):
            if var not in reads_j or not types.get(var) or re.search(rf'&\s*{var}\b', body):
                continue  # not an in-place update of a plain local
            for i in range(j - 1, -1, -1):
                _, _, _, target, reads_i = run[i]
                if target == var:
                    break  # an earlier value of V: the reads before it see another word
                if var not in reads_i or target in reads_i:
                    continue
                between = run[i + 1:j + 1]
                if any(target == lhs or target in reads for _, _, _, lhs, reads in between):
                    continue
                if any(lhs in reads_i and lhs != var for _, _, _, lhs, _ in between):
                    continue
                n = 1
                while f'{var}_{n}' in taken:
                    n += 1
                copy = f'{var}_{n}'
                indent = run[i][2]
                start, end = run[i][0], run[j][1]
                moved = re.sub(rf'\b{var}\b', copy, source[run[i][0] + len(indent):run[i][1]])
                lines = [f'{indent}{{', f'{indent}    {types[var]} {copy} = {var};']
                lines += [f'    {source[s:e]}' for s, e, _, _, _ in between]
                lines += [f'{indent}    {moved}', f'{indent}}}']
                text = edit(source, [(start, end, '\n'.join(lines))])
                if text != source and all(text != t for _, t in out):
                    out.append((FAMILY, text))
                if len(out) >= LIMIT:
                    return out
    return out


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}  # the registry: no caller wiring (registry.py)
