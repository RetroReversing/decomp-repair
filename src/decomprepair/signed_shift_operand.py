"""A right shift of an unsigned expression, written as the arithmetic shift the target's `sra` shows.

A sum or difference that mixes an unsigned local with signed ones is unsigned in C, and `(a - b + 8) >> 3` compiles to
`srl`. m2c writes the signed reading as `(s32) (a - b + 8) >> 3`, and a rewrite that dropped the `(s32)` with the mask
around it (a field of a display-list word) made the shift logical: 855 -> 655 on a 315-instruction tile-rectangle builder
once the cast was back. `variants` takes each `OPERAND >> K` whose operand is a parenthesised expression or an identifier
that names a local or parameter declared `u32`/`unsigned` (not already cast, not a call) and writes `(s32) OPERAND >> K`.
It runs only when the target's assembly has an `sra` (a candidate whose target has none cannot gain from it). One
proposal per distinct operand (at most 6; a line that two commands share is one edit) and one with all of them. A hypothesis; the exact judge decides."""
import re

from .integer_repair_support import edit, view

FAMILY = 'signed_shift_operand'
FAMILIES = (FAMILY,)
LIMIT = 6

_ID = r'[A-Za-z_]\w*'
_UNSIGNED = r'(?:u32|unsigned(?:\s+(?:int|long))?)'
_SHIFT = re.compile(r'>>\s*(?:0[xX][0-9a-fA-F]+|\d+)\b')


def _open_of(clean, end):
    """The `(` that matches the `)` at `end`, or None."""
    depth = 0
    for index in range(end, -1, -1):
        depth += clean[index] == ')'
        depth -= clean[index] == '('
        if depth == 0:
            return index
    return None


def variants(source, name, header='', asm=''):
    if asm and not re.search(r'\bsra\b', asm):
        return []
    part = view(source, name)
    if not part:
        return []
    clean = part.clean
    unsigned = {h['n'] for h in re.finditer(rf'(?<![\w])(?:register\s+)?{_UNSIGNED}\s+(?P<n>{_ID})\s*[;,)=]', clean[:part.end])}
    if not unsigned:
        return []
    sites = []
    for hit in _SHIFT.finditer(clean, part.opening, part.end):
        left = clean[:hit.start()].rstrip()
        if left.endswith(')'):
            opening = _open_of(left, len(left) - 1)
            if opening is None:
                continue
            before = left[:opening].rstrip()
            if re.search(rf'{_ID}$', before) and not re.search(r'\b(?:return|if|while)$', before):
                continue  # a call's result
            if re.search(r'\)\s*$', before) and re.search(r'\(\s*(?:s32|int|long|s16|s8)\s*\)\s*$', before):
                continue  # already signed
            operand = left[opening:]
            at = opening
        else:
            token = re.search(rf'({_ID})$', left)
            if not token or re.search(r'(?:\.|->)$', left[:token.start()].rstrip()) or re.search(r'\(\s*(?:s32|int|long)\s*\)\s*$', left[:token.start()]):
                continue
            operand, at = token.group(1), token.start()
        if not set(re.findall(_ID, operand)) & unsigned:
            continue
        sites.append((at, ' '.join(operand.split())))
    if not sites:
        return []
    by_text = {}
    for at, text in sites:
        by_text.setdefault(text, []).append(at)
    texts = list(by_text)[:LIMIT]
    out = []
    groups = [texts] if len(texts) > 1 else []
    groups += [[text] for text in texts]
    for group in groups:
        out.append((FAMILY, edit(source, [(at, at, '(s32) ') for text in group for at in by_text[text]])))
    return list(dict.fromkeys(out))


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'header', 'asm'), 'order': 99}  # the registry: no caller wiring (registry.py)
