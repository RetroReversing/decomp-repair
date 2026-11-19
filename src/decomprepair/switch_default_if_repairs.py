"""m2c's `default:` label inside a case arm's `if`, written as the returns it came from.

When some cases test a condition and return one value, and the default (and the condition's other side) return
another, gcc shares the second return. m2c reads that join as a label inside the `if`:

    switch (arg0) {
    case 2:
    case 3:
        var_v0 = 0;
        if (!((D != 1) & (D != 0x10))) {
        default:
            var_v0 = 1;
        }
        break;
    }
    return var_v0;

An N64 function was 36.6% so. Written as `case 2: case 3: if ((D != 1) & (D != 0x10)) { return 0; } default: return
1;` it was exact. Only this shape: the variable is assigned in those two places and returned right after the switch.
"""
import re

from .csource import _blank, find
from .pattern_repairs import close, negate

FAMILY = 'switch_default_in_if'
FAMILIES = (FAMILY,)

IDENT = r'[A-Za-z_]\w*'
VALUE = r'-?(?:0[xX][0-9a-fA-F]+|\d+)[uU]?|' + IDENT

SHAPE = re.compile(
    r'(?P<indent>[ \t]*)(?P<var>' + IDENT + r')\s*=\s*(?P<first>' + VALUE + r')\s*;[ \t]*\n'
    r'[ \t]*if\s*\((?P<cond>.*)\)\s*\{[ \t]*\n'
    r'[ \t]*default\s*:[ \t]*\n'
    r'[ \t]*(?P=var)\s*=\s*(?P<second>' + VALUE + r')\s*;[ \t]*\n'
    r'[ \t]*\}[ \t]*\n'
    r'[ \t]*break\s*;[ \t]*\n'
    r'(?P<close>[ \t]*\}[ \t]*\n)'
    r'[ \t]*return\s+(?P=var)\s*;')


def _inverse(condition):
    condition = condition.strip()
    inner = re.fullmatch(r'!\s*\((.*)\)', condition)
    if inner and close(condition, condition.index('(')) == len(condition):
        return inner[1].strip()
    return negate(condition) or f'!({condition})'


def variants(source, name):
    span = find(source, name)
    if not span:
        return []
    clean = _blank(source)
    opening = clean.find('{', span[0], span[1])
    end = close(clean, opening, '{', '}') if opening >= 0 else None
    if not end:
        return []
    result = []
    for hit in SHAPE.finditer(clean, opening, end):
        var = hit['var']
        mentions = re.findall(r'(?<![\w.>])' + var + r'\b', clean[opening:end])
        # the declaration, the two assignments and the return: nothing else reads or writes it
        if len(mentions) != 4:
            continue
        indent = hit['indent']
        outer = hit['close'][:len(hit['close']) - len(hit['close'].lstrip())]
        raw = source[hit.start('cond'):hit.end('cond')]
        text = (source[:hit.start()]
                + f'{indent}if ({_inverse(raw)}) {{\n{indent}    return {hit["first"]};\n{indent}}}\n'
                + f'{outer}default:\n{indent}return {hit["second"]};\n'
                + source[hit.start('close'):hit.end('close')] + source[hit.end():])
        # the variable's declaration goes with it (the return after the switch is gone too)
        decl = re.compile(r'(?m)^[ \t]*[\w ]+?\s+' + var + r'\s*;[ \t]*\n').search(text, opening, hit.start())
        if decl:
            text = text[:decl.start()] + text[decl.end():]
        result.append((FAMILY, text))
    return result[:2]
