"""A product by a small constant, written the way the game's shift-and-add chain computes it: `(x * 0xA)` as `((x << 2) + x) << 1`.

m2c reads the constant multiply the compiler emitted and writes it back as `x * K`. When the game spelled the
scaling with shifts and adds (a fixed-point scale of ten, a stride of three words), GCC 2.7.2 does not rebuild the
same chain from `x * K`: it expands the multiply itself with its own choice of operand order and temporaries, so the
shift chain's registers and the position of its operands differ even when the instruction count is the same.
Measured on a KMC GCC 2.7.2 (`-G0 -mips3 -mgp32 -mfp32 -O2`) 30-instruction N64 function that scales a volume by 100,
10 and 4 in turn: the product `arg1 * 0xA` held at 15, `((arg1 << 2) + arg1) << 1` was 0.

The shape: a parenthesised `(local * K)` with `local` a plain integer name and `K` a literal that factors as
`(2^a + 1) * 2^b` (3, 5, 9, 10, 18, 20, 36, ...) or `(2^a - 1) * 2^b` (7, 14, 15, 28, 30, ...). One child per product:
`((x << a) + x) << b` or `((x << a) - x) << b` (the `<< b` dropped when `b` is 0). A float or pointer operand is skipped.
The reading of the compiler is a hypothesis; the exact judge decides.
"""
import re

from .integer_repair_support import IDENT, NUMBER, edit, view

FAMILY = 'multiply_shift_add'
FAMILIES = (FAMILY,)

PRODUCT = re.compile(rf'\((?P<var>{IDENT})\s*\*\s*(?P<k>{NUMBER})\)')
FLOAT_TYPES = r'(?:f32|f64|float|double)'
LIMIT = 8


def chain(var, k):
    """The shift-and-add spelling of `var * k`, or None when k has no one-step form."""
    low = (k & -k).bit_length() - 1
    odd = k >> low
    if odd < 3:
        return None
    if (odd - 1) & (odd - 2) == 0:
        inner = f'({var} << {(odd - 1).bit_length() - 1}) + {var}'
    elif (odd + 1) & odd == 0:
        inner = f'({var} << {(odd + 1).bit_length() - 1}) - {var}'
    else:
        return None
    return f'(({inner}) << {low})' if low else f'({inner})'


def variants(source, name):
    part = view(source, name)
    if not part:
        return []
    clean = part.clean
    out = []
    for hit in PRODUCT.finditer(clean, part.opening, part.end):
        var = hit['var']
        if re.search(rf'\b{FLOAT_TYPES}\s+\**\s*{var}\b|\b{var}\s*\.', clean[:part.end]):
            continue
        if hit['k'][-1] in 'fF' and not hit['k'].lower().startswith('0x'):
            continue
        k = int(hit['k'].rstrip('uUlL'), 0)
        text = chain(var, k)
        if text is None:
            continue
        child = edit(source, [(hit.start(), hit.end(), text)])
        if (FAMILY, child) not in out:
            out.append((FAMILY, child))
        if len(out) >= LIMIT:
            break
    return out


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}  # the registry: no caller wiring (registry.py)
