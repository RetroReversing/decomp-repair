"""A shifted value feeding a product, computed first in a `do { } while (0)` of its own.

`d = a - (b * (t >> 8));` expands the shift next to the multiply, and the scheduler orders the product's operand
loads before the shift. The register allocator then gives the first-born value of the pair the lowest register, and
the shift result (which the target computed first, in the delay slot of the test before it) lands in `$v0` where the
game's is `$v1`, mirroring a whole chain of five rows. The loop notes a `do { } while (0)` leaves are scheduling
boundaries and nothing else survives into the object, so staging the shift in a scope of its own (`do { s = t >> 8;
} while (0);` and `b * s`) fixes the order. Measured on a 719-instruction N64 function (`gcc-2.7.2-kmc -G0 -mips3
-mgp32 -mfp32 -O2`): 435 -> 400, the five rows of the chain gone. Each shift that is one operand of a product in an
assignment gets one variant. A candidate rewrite; the exact judge decides.

`product_shift_hoist` is the plain form: `s = t >> 8;` with no scope, placed right after the last assignment of `t`
in the same block (past statements and nested blocks that don't mention it). On the same function, the shift of an
accumulator written back into its product and the product moved past an `if` scored 1280; the `do { } while (0)`
stage at the product gave 1260, the plain stage at the product 1280, and the plain stage after the accumulator's
last write 0 (the scheduler sees the shift before the loads between, as the target computed it).
"""
import re

from .integer_repair_support import IDENT, edit, view
from .line_scan import apply, lines, with_local
from .loaded_byte_repairs import declarators

FAMILY = 'product_shift_stage'
MASKED_PRODUCT = 'masked_product_stage'
HOIST = 'product_shift_hoist'
FAMILIES = (FAMILY, MASKED_PRODUCT, HOIST)
_SHIFT = re.compile(r'\((?P<v>[A-Za-z_]\w*) >> (?P<n>\d+)\)')


_MASKED = re.compile(
    rf'(?m)^[ \t]*(?P<dst>{IDENT})\s*=\s*\((?P<src>{IDENT})\s*&\s*(?P<mask>0[xX][0-9a-fA-F]{{1,8}})\)'
    rf'\s*\*\s*(?P<scale>[1-9][0-9]{{0,9}})\s*;'
)


def _masked_products(source, part):
    """Keep the mask and the multiply in the existing unsigned destination."""
    if re.search(r'(?m)^\s*#', part.body) or re.search(r'\b(?:asm|__asm__)\b', part.body):
        return []
    result = []
    for m in _MASKED.finditer(part.clean, part.opening + 1, part.end):
        name = m['dst']
        mask, scale = int(m['mask'], 16), int(m['scale'])
        if not 0 < mask * scale <= 0x7fffffff or scale == 1:
            continue
        # The extra write must be local, nonvolatile, and invisible through aliases.
        declarations = [d for d in declarators(part.body, name) if not d[0].startswith('return ')]
        decl = re.search(rf'(?m)^[ \t]*(?:u32|unsigned(?:\s+int)?)\s+{name}\s*;', part.body)
        complex_declaration = rf'(?m)^\s*(?:{IDENT}\s+)+[^;\n=()]*[, (]\s*\**\s*{name}\s*[;=,)\[]'
        if (not decl or len(declarations) != 1 or re.search(complex_declaration, part.body)
                or re.search(rf'(?<!&)\&\s*\(?\s*{name}\b', part.body)):
            continue
        if source[m.start():m.end()] != m[0]:
            continue
        indent = m[0][:len(m[0]) - len(m[0].lstrip())]
        replacement = f'{indent}{{ {name} = ({m["src"]} & {m["mask"]}); {name} *= {m["scale"]}; }}'
        result.append((MASKED_PRODUCT, edit(source, [(m.start(), m.end(), replacement)])))
    return result


def variants(source, name):
    part = view(source, name)
    if not part:
        return []
    body = lines(part, source)
    out = _masked_products(source, part)
    for line in body:
        text = line.stripped
        if not re.match(r'[A-Za-z_]\w* = ', text) or not text.endswith(';'):
            continue
        for hit in _SHIFT.finditer(text):
            if not re.search(r'\*\s*$', text[:hit.start()]) and not re.match(r'\s*\*', text[hit.end():]):
                continue
            local = 'shift_stage'
            if re.search(rf'\b{local}\b', part.clean):
                continue
            declaration = with_local(source, part, f's32 {local};')
            if not declaration:
                continue
            indent = line.indent
            scope = (f'{indent}do\n{indent}{{\n{indent}  {local} = {hit["v"]} >> {hit["n"]};\n{indent}}}\n'
                     f'{indent}while (0);\n')
            replaced = line.source[:line.source.index(hit[0])] + local + line.source[line.source.index(hit[0]) + len(hit[0]):]
            out.append((FAMILY, apply(source, [declaration, (line.start, line.start, scope),
                                               (line.start, line.start + len(line.source), replaced)])))
            after = _last_write(body, body.index(line), hit['v'])
            if after is not None:
                stage = f'{body[after].indent}{local} = {hit["v"]} >> {hit["n"]};\n'
                out.append((HOIST, apply(source, [declaration, (body[after].end, body[after].end, stage),
                                                  (line.start, line.start + len(line.source), replaced)])))
            break
    return out


def _last_write(body, index, var):
    """Index of the line, in the block of line `index`, that last assigns `var` before it; None when a nested block
    or a line that isn't a plain assignment mentions it first, or the block starts first."""
    indent = body[index].indent
    mention = re.compile(rf'(?<![\w.>]){re.escape(var)}\b')
    write = re.compile(rf'^{re.escape(var)}\s*(?:[-+*/%&|^]|<<|>>)?=(?!=)')
    for i in range(index - 1, -1, -1):
        line = body[i]
        if len(line.indent) < len(indent):
            return None
        if not mention.search(line.text):
            continue
        if line.indent != indent or not line.stripped.endswith(';'):
            return None
        if write.match(line.stripped):
            return i
    return None
