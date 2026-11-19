"""m2c's `goto` loop with a shared skip block, written as the `do`/`while` it came from.

A search loop that returns when two tests pass, stepping its counters otherwise, comes back from m2c as two `if`s
sharing a label for the step:

    loop_1:
        if (A == 0) {
            off += 0xE8;
            goto block_8;
        }
        if (B != arg1) {
            off += 0xE8;
    block_8:
            i += 1;
            p += 8;
            if (i >= 0x21U) {
                return 0;
            }
            goto loop_1;
        }
        return 1;

gcc builds the gotos with the counters in other registers and the found case at the bottom: an N64 function was
75.7% so. As the loop it is, `do { if (A != 0 && B == arg1) return 1; off += 0xE8; i += 1; p += 8; } while (i <
0x21U); return 0;`, it was exact. Only this shape: both arms step the same way, the second falls into the shared
label, and the loop's one exit returns.
"""
import re

from .csource import _blank, find
from .pattern_repairs import close, negate

FAMILY = 'goto_loop'
FAMILIES = (FAMILY,)

SHAPE = re.compile(
    r'(?m)^[ \t]*(?P<loop>[A-Za-z_]\w*):[ \t]*\n'
    r'(?P<indent>[ \t]*)if \((?P<first>.*)\) \{[ \t]*\n(?P<step1>(?:[ \t]*[^\n:{}]*;[ \t]*\n)*?)[ \t]*goto (?P<label>\w+);[ \t]*\n'
    r'[ \t]*\}[ \t]*\n'
    r'[ \t]*if \((?P<second>.*)\) \{[ \t]*\n(?P<step2>(?:[ \t]*[^\n:{}]*;[ \t]*\n)*?)(?P=label):[ \t]*\n'
    r'(?P<body>(?:[ \t]*[^\n:{}]*;[ \t]*\n)*?)'
    r'[ \t]*if \((?P<exit>.*)\) \{[ \t]*\n[ \t]*return (?P<left>[^;\n]+);[ \t]*\n[ \t]*\}[ \t]*\n'
    r'[ \t]*goto (?P=loop);[ \t]*\n'
    r'[ \t]*\}[ \t]*\n'
    r'[ \t]*return (?P<found>[^;\n]+);[ \t]*\n')


def _not(condition):
    return negate(condition.strip()) or f'!({condition.strip()})'


def _lines(text, indent):
    return ''.join(indent + line.strip() + '\n' for line in text.splitlines() if line.strip())


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
        if ' '.join(hit['step1'].split()) != ' '.join(hit['step2'].split()):
            continue
        # nothing else may jump to the loop or the shared step
        if len(re.findall(r'\bgoto\s+(?:' + hit['loop'] + '|' + hit['label'] + r')\s*;', clean[opening:end])) != 2:
            continue
        indent = hit['indent']  # (m2c writes labels at the margin: the `if` after it has the block's)
        inner = indent + '    '
        def raw(group, hit=hit):
            return source[hit.start(group):hit.end(group)]
        loop = (f'{indent}do {{\n'
                f'{inner}if (({_not(raw("first"))}) && ({_not(raw("second"))})) {{\n'
                f'{inner}    return {raw("found").strip()};\n'
                f'{inner}}}\n'
                + _lines(raw('step1'), inner) + _lines(raw('body'), inner)
                + f'{indent}}} while ({_not(raw("exit"))});\n'
                f'{indent}return {raw("left").strip()};\n')
        result.append((FAMILY, source[:hit.start()] + loop + source[hit.end():]))
    return result[:2]
