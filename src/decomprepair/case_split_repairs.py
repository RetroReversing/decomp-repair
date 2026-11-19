"""Stacked `case` labels given a copy of their body each, as the source had.

gcc 2.7.2 lays out a switch from its case values: adjacent labels on one body (`case 0x37: case 0x38:`) become a range
test (`v - 0x37 < 2`), but labels with bodies of their own become equality tests in its compare tree, even when cross
jumping later merges the identical bodies back into one. m2c sees the merged body and stacks the labels: an N64
function was 58.9% with `case 0x37: case 0x38: f(); break;` and exact with each label's own `f(); break;`. Offered
for a body of plain statements (no block, no label) that ends in `break;` or a `return`.
"""
import re

from .csource import _blank, find
from .pattern_repairs import close

FAMILY = 'split_case_labels'
FAMILIES = (FAMILY,)

LABEL = r'[ \t]*case\s+[^:\n]+:[ \t]*(?:/\*[^\n]*\*/)?[ \t]*\n'


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
    case = re.compile(r'^[ \t]*case\s+[^:\n]+:[ \t]*(?:/\*.*\*/)?[ \t]*$')
    lines = source[opening:end].split('\n')
    clean_lines = clean[opening:end].split('\n')
    offsets, at = [], opening
    for line in lines:
        offsets.append(at)
        at += len(line) + 1
    i = 0
    while i < len(lines):
        j = i
        while j < len(lines) and case.match(clean_lines[j]):
            j += 1
        if j - i < 2:
            i = max(j, i + 1)
            continue
        # the body: plain statements up to its `break;` or `return`, no blocks and no other label
        k, closed = j, None
        while k < len(lines):
            text = clean_lines[k].strip()
            if (not text or '{' in text or '}' in text or text.startswith(('case ', 'default'))
                    or re.fullmatch(r'[A-Za-z_]\w*\s*:', text)):  # a label can't be copied
                break
            if text == 'break;' or re.match(r'return\b[^;]*;$', text):
                closed = k
                break
            k += 1
        if closed is not None and closed > j - 1:
            labels = [lines[n] + '\n' for n in range(i, j)]
            body = ''.join(lines[n] + '\n' for n in range(j, closed + 1))
            start, stop = offsets[i], offsets[closed] + len(lines[closed]) + 1
            result.append((FAMILY, source[:start] + ''.join(label + body for label in labels) + source[stop:]))
            if len(result) >= 4:
                break
        i = j
    return result
