"""`(X - K) - Y` with the first difference held in a block-scoped local, so cse cannot reassociate it.

gcc 2.7.2 (`-O1 -g`, KMC and SN builds) folds the constant out of `(X - 0x11310) - Y` and builds `X - (Y + 0x11310)`,
which reuses the `Y + 0x11310` an earlier statement already computed (the game stored `Y + 0x11310` one line above). The
game kept the first difference in a local (`span = X - 0x11310`) and subtracted `Y` from it, once for each of two
statements; the target has the two subtractions, each from its own `X - 0x11310`. A 59-instruction N64 display-list
setup, 440 -> 0 on both compilers: every `(X - K) - Y` statement written `{ s32 span = X - K; ...span - Y...; }`. Hypotheses
from the output, which the judge decides: a named pseudo is not folded through (the combiner does not merge a set that
has another use), and a block of its own gives each statement a fresh pseudo, where one local assigned twice, or the
sum named inside the expression (`named_sum_difference`'s form), each stayed at 70.

A site is a statement, at the top of a block, with a parenthesised `E - K` or `E + K` (`K` a literal; `E` one
operand: a `M2C_FIELD(...)` read, a `*(T *)...` dereference or an integer local or parameter, with no call, comparison
or assignment) directly before another `-` or `+`. The statement may be an expression, an assignment or a `return`
(not an `if`, a loop or a `goto`). The local is `span` (a suffix when the name is in use), `s32` unless the operand is an
unsigned 32-bit word. One child with every site staged, and one per site when there are several.
"""
import re

from .arm_block_support import KEYWORDS, brace_pairs, statements
from .integer_repair_support import IDENT, INTEGER, NUMBER, edit, view
from .pattern_repairs import close

FAMILY = 'difference_block_stage'
FAMILIES = (FAMILY,)
LIMIT = 6
LOCAL = 'span'
_FIELD = re.compile(rf'M2C_FIELD\((?:.|\n)*,\s*(?P<type>{INTEGER}|M2C_UNK32)\s*\*\s*,\s*[-\w]+\s*\)\Z')
_DEREF = re.compile(rf'\*\s*\(\s*(?P<type>{INTEGER})\s*\*\s*\)')
_FOLLOWS = re.compile(r'\s*[-+](?![-+=])')
_OPERAND = re.compile(r'[A-Za-z_]\w*\Z|M2C_FIELD\s*\(|\(?\s*\*\s*\(\s*\w+(?:\s+\w+)?\s*\*\s*\)')
_BINARY = re.compile(r'[-+*/%<>=!&|^?,]|\bsizeof\b')


def _blanked(text):
    """`text` with the inside of every bracket pair blanked, so only its top-level characters remain."""
    out, depth = [], 0
    for char in text:
        if char in '([':
            out.append(char if not depth else ' ')
            depth += 1
        elif char in ')]':
            depth -= 1
            out.append(char if not depth else ' ')
        else:
            out.append(char if not depth else ' ')
    return ''.join(out)


def _operand_type(part, operand):
    """The C type of `operand` as `s32` or `u32`, or None when it is not one the family reads."""
    if (hit := _FIELD.match(operand)) or (hit := _DEREF.match(operand.lstrip('( \t'))):
        kind = ' '.join(hit['type'].split())
    elif re.fullmatch(IDENT, operand):
        found = re.findall(rf'(?<![\w.>])({INTEGER})\s+{operand}\s*[;,=)]', part.clean[:part.end])
        if not found:
            return None
        kind = ' '.join(found[-1].split())
    else:
        return None
    return 'u32' if kind in {'u32', 'unsigned int', 'unsigned', 'M2C_UNK32'} and not kind.startswith('M2C') else 's32'


def _group(text, start):
    """(opening, end, operand, sign, constant) for the `( E -/+ K )` group opening at `start`, else None."""
    end = close(text, start)
    if end is None or end <= start + 1:
        return None
    inner = text[start + 1:end - 1].strip()
    hit = re.fullmatch(rf'(?P<e>.+?)\s*(?P<sign>[-+])\s*(?P<k>{NUMBER})', inner, re.S)
    if not hit:
        return None
    operand = hit['e'].strip()
    top = _blanked(operand)
    if top.startswith(('*', '(*')) or _OPERAND.match(operand):
        top = re.sub(r'^\(?\s*\*', '', top)
    if _BINARY.search(top) or re.search(r'\w\s*\(', re.sub(r'M2C_FIELD\s*\(', '', operand)) \
            or not _OPERAND.match(operand):
        return None
    return start, end, operand, hit['sign'], hit['k']


def _sites(part):
    clean = part.clean
    pairs = brace_pairs(clean, part.opening, part.end) or {}
    found = []
    for opening, closing in sorted(pairs.items()):
        for begin, end in statements(clean, opening + 1, closing):
            text = clean[begin:end]
            if not text.endswith(';') or re.match(rf'(?:{"|".join(sorted(KEYWORDS - {"return"}))})\b', text):
                continue
            if re.match(IDENT + r'\s*:(?!:)', text):
                continue  # a label
            for at in (m.start() for m in re.finditer(r'\(', text)):
                group = _group(text, at)
                if not group or not _FOLLOWS.match(text, group[1]) or group[1] >= len(text):
                    continue
                if text.count(clean[begin + group[0]:begin + group[1]]) != 1:
                    continue
                kind = _operand_type(part, group[2])
                if kind:
                    found.append((begin, end, begin + group[0], begin + group[1], group[2], group[3], group[4], kind))
                    break
    return found


def _local(clean):
    name, number = LOCAL, 1
    while re.search(rf'\b{name}\b', clean):
        number += 1
        name = f'{LOCAL}{number}'
    return name


def variants(source, name):
    part = view(source, name)
    if not part:
        return []
    sites = _sites(part)
    if not sites:
        return []
    local = _local(part.clean)

    def staged(site):
        begin, end, left, right, operand, sign, constant, kind = site
        indent = re.match(r'[ \t]*', source[source.rfind('\n', 0, begin) + 1:begin])[0]
        body = source[begin:left] + local + source[right:end]
        return [(begin, end, f'{{\n{indent}    {kind} {local} = {operand} {sign} {constant};\n{indent}    {body}\n{indent}}}')]

    choices = [sites] + ([[site] for site in sites] if len(sites) > 1 else [])
    return [(FAMILY, edit(source, [e for site in choice for e in staged(site)])) for choice in choices][:LIMIT]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}
