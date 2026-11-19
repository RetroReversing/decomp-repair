"""Parameters as the target uses them: masked once at entry, or arriving as floats in integer registers.

`parameter_mask_hoist`: a parameter only ever read as `(arg & K)` (one K) is `arg &= K;` once at the top. gcc 2.7.2
then masks it on entry, where with the mask at each use it recomputes `K` beside the loop: an N64 search loop was 80%
with the mask in its test and exact with `arg0 &= 0x1E000;` first.

`float_register_parameter`: a parameter m2c typed as an integer (`M2C_UNK`, `s32`) that the target moves into a float
register at entry (`mtc1 $a1, $fs2`) is an `f32`. After a pointer the o32 ABI passes floats in `$a1`-`$a3`, and m2c
missed them: an N64 function was 34% so, and exact with its three parameters as `f32` (and its callees' prototypes).
"""
import re

from .csource import _blank, find
from .pattern_repairs import close

MASK_HOIST = 'parameter_mask_hoist'
FLOAT_PARAM = 'float_register_parameter'
FAMILIES = (MASK_HOIST, FLOAT_PARAM)

IDENT = r'[A-Za-z_]\w*'
ARG_REGISTERS = ('a0', 'a1', 'a2', 'a3')


def _signature(source, name):
    span = find(source, name)
    if not span:
        return None
    clean = _blank(source)
    opening = clean.find('{', span[0], span[1])
    end = close(clean, opening, '{', '}') if opening >= 0 else None
    if not end:
        return None
    paren = clean.rfind(')', span[0], opening)
    depth, start = 0, None
    for i in range(paren, span[0] - 1, -1):
        depth += (clean[i] == ')') - (clean[i] == '(')
        if depth == 0:
            start = i
            break
    if start is None:
        return None
    return clean, opening, end, start, paren


def _params(clean, start, paren):
    """[(begin, end, type text, name)] of the signature's parameters."""
    out, at = [], start + 1
    for part in clean[start + 1:paren].split(','):
        m = re.fullmatch(r'\s*(.*?[\s*])(' + IDENT + r')\s*', part)
        if m:
            out.append((at + m.start(1), at + m.end(1), m[1], m[2]))
        at += len(part) + 1
    return out


def mask_hoist(source, name):
    found = _signature(source, name)
    if not found:
        return []
    clean, opening, end, start, paren = found
    result = []
    body = clean[opening:end]
    for _, _, kind, param in _params(clean, start, paren):
        if '*' in kind or 'f32' in kind or 'f64' in kind or 'float' in kind or 'double' in kind:
            continue
        uses = list(re.finditer(r'(?<![\w.>])' + param + r'\b', body))
        masked = list(re.finditer(r'\(\s*' + param + r'\s*&\s*(0[xX][0-9a-fA-F]+|\d+)[uU]?\s*\)', body))
        if not masked or len(uses) != len(masked) or len({m[1].lower() for m in masked}) != 1:
            continue
        # the first statement after the declarations
        decls = re.match(r'\{\s*(?:(?:[\w ]+?[\s*]+' + IDENT + r'(?:\[[^]]*\])?\s*(?:,\s*\**\s*' + IDENT + r')*\s*;\s*)*)',
                         clean[opening:end])
        at = opening + (decls.end() if decls else 1)
        indent = re.search(r'\n([ \t]*)\S', clean[opening:end])
        indent = indent[1] if indent else '    '
        text = source
        for m in reversed(masked):
            text = text[:opening + m.start()] + param + text[opening + m.end():]
        line_start = text.rfind('\n', 0, at) + 1
        text = text[:line_start] + f'{indent}{param} &= {masked[0][1]};\n' + text[line_start:]
        result.append((MASK_HOIST, text))
    return result


def float_parameters(source, name, asm):
    if not asm:
        return []
    found = _signature(source, name)
    if not found:
        return []
    clean, opening, end, start, paren = found
    # the entry block: moves out of argument registers into float registers before the first branch or call
    entry = re.split(r'\b(?:jal|jalr|b\w*|j)\s', asm, maxsplit=1)[0]
    moved = {m[1] for m in re.finditer(r'\bmtc1\s+\$(a[0-3])\s*,', entry)}
    if not moved:
        return []
    params = _params(clean, start, paren)
    edits = []
    for index, (begin, stop, kind, param) in enumerate(params[:4]):
        if ARG_REGISTERS[index] in moved and re.fullmatch(r'\s*(?:M2C_UNK|s32|u32|int|M2C_UNK32)\s*', kind):
            edits.append((begin, stop, 'f32 '))
    if not edits:
        return []
    text = source
    for begin, stop, insert in sorted(edits, reverse=True):
        text = text[:begin] + insert + text[stop:]
    return [(FLOAT_PARAM, text)]


def variants(source, name, asm=''):
    return (mask_hoist(source, name) + float_parameters(source, name, asm))[:4]
