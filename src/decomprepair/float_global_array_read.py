"""A float global the target reads through a register of its own, declared as an unsized array and read as `G[0]`.

GCC loads a scalar float global with the assembler's `l.s` macro: `lui $at, %hi(G)` and `lwc1 $f, %lo(G)($at)`, the
address built in `$at`. The target of one function (KMC GCC 2.7.2 -G8 -mips2 -O1, a float compare after a call)
instead had `lui $v0, %hi(G)` and `lwc1 $fv1, %lo(G)($v0)`: the address in an ordinary register, so the register
allocator saw one more value and gave the call's result another register. No spelling of a scalar `extern f32 G;`
makes that shape (a pointer cast, `volatile`, a local read before the call, a ternary: every one stayed at its score).
Declaring the symbol `extern f32 G[];` and reading `G[0]` does: an array's address is an ordinary address constant
the compiler keeps in a register. That alone fixed the load pair and moved the call result to `$a0` (10 -> 115); the
element read into a local right after the call (`f = G[0]; ... if (!(f < other))`) gave the target's order
(115 -> 0), where the same local read before the call scored 607. So the repair is two parts that pay off together
(Hypothesis: the explanation of the extra register is read off the targets, not from the compiler's source).

A proposal takes one float global the function only reads and that the target's assembly loads through a register
other than `$at` (`lui $reg, %hi(G)`; a scalar read through `$at` or `$gp` is the other shape, `float_literal_global`
covers constants). Children, per global, from the plainest:
- the array declaration with every read written `G[0]`;
- the array declaration with the reads in a local, loaded at each statement boundary of the function's top block from
  the function's top down to the statement that holds the first read (after each call, before each statement, at the
  top): the position is the search, the judge decides.
At most 4 globals and 24 children."""
import re

from .csource import _blank
from .float_literal_global import _declared_float, _reads
from .integer_repair_support import IDENT, edit, view

FAMILY = 'float_global_array_read'
FAMILIES = (FAMILY,)

MAX_GLOBALS = 4
MAX_CHILDREN = 24
_FLOATS = ('f32', 'float', 'f64', 'double')
_DECLARATION = re.compile(rf'(?m)^(?P<indent>[ \t]*)extern[ \t]+(?P<type>f32|float|f64|double)[ \t]+(?P<name>{IDENT})[ \t]*;')


def _register_loads(symbol, asm):
    """True when the assembly builds `symbol`'s high half in a register other than `$at`, and never reads it through
    `$at` or `$gp` (a mix is a different shape this does not explain)."""
    through_register = False
    pattern = re.compile(r'%(?:hi|lo|gp_rel)\(\s*' + re.escape(symbol) + r'\s*(?:[+-][^)]*)?\)')
    for line in (asm or '').splitlines():
        if not pattern.search(line):
            continue
        code = re.sub(r'/\*.*?\*/', ' ', line).strip()
        high = re.match(r'lui\s+\$(\w+)\s*,\s*%hi\(', code)
        if high:
            if high[1] == 'at':
                return False
            through_register = True
            continue
        if re.search(r'\$(?:at|gp)\s*\)', code):
            return False
    return through_register


def _boundaries(clean, opening, end):
    """The offsets just after each statement of the function's top block that ends at depth 0, and the offset where
    each of those statements starts: [(start, stop)]."""
    spans, depth, start, at = [], 0, None, opening + 1
    text = clean[:end - 1]
    while at < len(text):
        char = text[at]
        if start is None and not char.isspace():
            start = at
        if char in '({[':
            depth += 1
        elif char in ')}]':
            depth -= 1
            if char == '}' and depth == 0 and start is not None:
                after = text[at + 1:].lstrip()
                if not re.match(r'(?:else|while)\b', after):
                    spans.append((start, at + 1))
                    start = None
        elif char == ';' and depth == 0 and start is not None:
            after = text[at + 1:].lstrip()
            if not re.match(r'else\b', after):
                spans.append((start, at + 1))
                start = None
        at += 1
    return spans


def _is_declaration(statement):
    return bool(re.match(rf'(?:(?:unsigned|signed|const|register|static)\s+)*(?:{IDENT})\s+\**\s*{IDENT}(?:\s*,\s*\**\s*{IDENT})*\s*(?:=[^;]*)?;\s*$', statement)
                and not re.match(r'(?:return|goto|break|continue|else|do)\b', statement))


def variants(source, name, header='', asm=''):
    """Proposals: a float global read through a register in the target, as `extern T G[];` read `G[0]`, plain and with
    the read held in a local at each statement boundary down to its first use."""
    if not asm:
        return []
    part = view(source, name)
    if not part:
        return []
    outside = _blank(source[:part.opening]) + ' ' + _blank(source[part.end:])
    body = source[part.opening:part.end]
    used = set(re.findall(IDENT, body))
    out = []
    taken = 0
    for found in _DECLARATION.finditer(outside):
        symbol = found['name']
        if taken >= MAX_GLOBALS or len(out) >= MAX_CHILDREN:
            break
        # the declaration is in the source (the header's cannot be changed), is the plain float, and nothing else
        # in the file (another function) uses the symbol
        if symbol not in used or symbol == name or re.search(rf'\b{re.escape(symbol)}\b', header or ''):
            continue
        if not _declared_float(symbol, (source,)) or not _register_loads(symbol, asm):
            continue
        spans = _reads(part, symbol)
        if not spans:
            continue
        uses = len(re.findall(rf'(?<![\w.]){re.escape(symbol)}\b', outside))
        if uses > len(re.findall(rf'\b{re.escape(symbol)}\b[ \t]*;', outside)):
            continue
        # the declaration's span in `source` (offsets of `outside` match `source` before the function; after it they
        # are shifted by the function's length minus one blank, so the declaration must precede the function)
        start = found.start('type')
        if start >= part.opening:
            continue
        declaration = (found.start(), found.end(), f'{found["indent"]}extern {found["type"]} {symbol}[];')
        taken += 1
        out.append((FAMILY, edit(source, [declaration] + [(a, b, f'{symbol}[0]') for a, b in spans])))
        local, kind = f'held_{symbol}', found['type']
        if local in used:
            continue
        top = _boundaries(part.clean, part.opening, part.end)
        first = next((index for index, (a, b) in enumerate(top) if a <= spans[0][0] < b), None)
        if first is None:
            continue
        indent = '    '
        first_use_line = source.rfind('\n', 0, top[first][0]) + 1
        indent = re.match(r'[ \t]*', source[first_use_line:top[first][0]]).group(0) or indent
        for index in range(first + 1):
            statement = source[top[index][0]:top[index][1]]
            if index < first and _is_declaration(statement):
                continue
            if index < first and re.search(rf'(?<![\w.]){re.escape(symbol)}\b', statement):
                continue
            # a local loaded after statement `index - 1` (before statement `index`): index 0 is the top of the block
            at = top[index][0]
            edits = [declaration, (part.opening + 1, part.opening + 1, f'\n{indent}{kind} {local};'),
                     (at, at, f'{local} = {symbol}[0];\n{indent}')]
            edits += [(a, b, local) for a, b in spans]
            out.append((FAMILY, edit(source, edits)))
            if len(out) >= MAX_CHILDREN:
                break
    return list(dict.fromkeys(out))


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'header', 'asm'), 'order': 61,
          'archs': ('mips',)}  # the registry: no caller wiring (registry.py)
