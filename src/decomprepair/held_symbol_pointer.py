"""A global whose address the target holds in a saved register, read through a pointer local set at the top.

`lui $s6, %hi(D_x); addiu $s6, $s6, %lo(D_x)` near the prologue, with later `lhu ($s6)` and `lbu 1($s6)`, is a user
variable: written as `D_x.sel` at each use, KMC GCC 2.7.2 `-O1` loads the address again in each block (or addresses the
member directly with `%lo(D_x + 1)`) and saves one register less, so the frame is 8 bytes short as well. Written as
`T *held = &D_x;` (or `T *held = D_x;` for an array) at the head of the function, the address is built once and carried.
On a 479-instruction N64 screen set-up routine two such pointers took a candidate from 2336 to 0; neither the inlining
families (`array_pointer_local_inline`, `symbol_alias_array`) nor any other offered them.

The target's assembly is the evidence: only a symbol whose address `lui`/`addiu` build in an `$s` register before the
first call is offered (an address built later is usually the compiler's own reuse of an argument, and a pointer for it
undoes the match: 465 against 0 on that function).
It must be declared `extern T D_x;` and used as `D_x.member` or `&D_x`, or `extern T D_x[];` and used by name (one
dimension). The pointers are declared in the order of the first use. Children: each symbol alone, then all together.
"""
import re

from .csource import _blank, find

FAMILY = 'held_symbol_pointer'
FAMILIES = (FAMILY,)
LIMIT = 6
_ID = r'[A-Za-z_]\w*'
_HELD = re.compile(rf'lui\s+\$(s[0-8]),\s*%hi\(({_ID})\)[\s\S]{{0,200}}?addiu\s+\$\1,\s*\$\1,\s*%lo\(\2\)')
_NOT_TYPES = ('return', 'extern', 'typedef', 'else', 'goto', 'case')


def _declaration(clean, symbol):
    """(type, is_array) of `extern T symbol;` or `extern T symbol[..];`, else None."""
    hit = re.search(rf'\bextern\s+((?:struct\s+|unsigned\s+|signed\s+)?{_ID})\s+{symbol}\s*(\[[^\]\[]*\])?\s*;', clean)
    if not hit or hit[1] in _NOT_TYPES or hit[1] == 'volatile':
        return None
    return hit[1], bool(hit[2])


def _rewrite(body, symbol, local, is_array):
    if is_array:
        return re.sub(rf'(?<![\w.>])(?<!&){symbol}\b', local, body)
    body = re.sub(rf'(?<![\w.>])(?<!&){symbol}\s*\.', f'{local}->', body)
    return re.sub(rf'(?<![&\w])&\s*{symbol}\b(?!\s*[.\[])', local, body)


def _uses(body, symbol, is_array):
    """Where `symbol` is first used in a form the pointer can take over, or None."""
    pattern = (rf'(?<![\w.>])(?<!&){symbol}\b' if is_array
               else rf'(?<![\w.>])(?<!&){symbol}\s*\.|(?<![&\w])&\s*{symbol}\b')
    hit = re.search(pattern, body)
    return hit.start() if hit else None


def _build(source, opening, end, picked):
    body = source[opening + 1:end]
    declarations = []
    for position, (symbol, kind, is_array) in enumerate(picked):
        local = f'held_{symbol}'
        body = _rewrite(body, symbol, local, is_array)
        value = symbol if is_array else f'&{symbol}'
        declarations.append(f'\n    {kind} *{local} = {value};')
    return source[:opening + 1] + ''.join(declarations) + body + source[end:]


def variants(source, name, asm=''):
    span = find(source, name)
    if not span or not asm:
        return []
    clean = _blank(source)
    opening = clean.find('{', *span)
    if opening < 0:
        return []
    body = clean[opening + 1:span[1]]
    found = []
    call = re.search(r'\bjal', asm)
    for hit in _HELD.finditer(asm, 0, call.start() if call else len(asm)):
        symbol = hit[2]
        declared = _declaration(clean, symbol)
        if not declared or f'held_{symbol}' in clean or any(item[1] == symbol for item in found):
            continue
        first = _uses(body, symbol, declared[1])
        if first is not None:
            found.append((first, symbol, *declared))
    picked = [item[1:] for item in sorted(found)][:LIMIT]
    out = [(FAMILY, _build(source, opening, span[1], [item])) for item in picked]
    if len(picked) > 1:
        out.append((FAMILY, _build(source, opening, span[1], picked)))
    return [item for item in out if item[1] != source]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'asm'), 'archs': ('mips',)}
