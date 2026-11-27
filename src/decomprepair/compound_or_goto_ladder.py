"""An `if ((a && b) || c)` written as the branches themselves, so the compiler cannot merge `a && b` into one test.

    } else if ((diff < 0 && diff >= -0x7FF) || (diff > 0x800)) {

GCC folds `diff < 0 && diff >= -0x7FF` into one unsigned range test, which also leaves the body reached from one place
and lets cse carry registers into it. Where the target tests the two comparisons one after the other (`bgez` on the
first, `beqz` on the second, then the third), the same condition written as branches keeps them apart:

    } else {
        if (diff < 0) {
            if (diff >= -0x7FF) {
                goto ladder_body_1;
            }
        }
        if (diff <= 0x800) {
            goto ladder_done_1;
        }
    ladder_body_1:
        ...
    ladder_done_1:;
    }

On a 113-instruction N64 turning routine (SN GCC 2.8.1, `-O2`) in otherwise exact C the `||` scored 1786, this form 0.
Why the two later copies of the body then stay apart (cse stopping at a label two branches reach) is a hypothesis from
the dumps, not read in the compiler's source.

compound_or_goto_ladder
    Each `if` without an `else` whose condition is `(a && b) || c` and whose braced body has no label or `case`.
"""
import re

from .c_scan import close
from .csource import _blank, find

FAMILY = 'compound_or_goto_ladder'
FAMILIES = (FAMILY,)
LIMIT = 8
_IF = re.compile(r'\bif\s*\(')
_ELSE = re.compile(r'\s*else\b')
_KEPT = re.compile(r'\b(?:case|default|static)\b|(?<![\w?])[A-Za-z_]\w*\s*:(?!:)')
_TOKEN = re.compile(r'[()\[\]?,]|&&|\|\|')
_COMPARE = re.compile(r'(?P<left>[^<>=!&|?]+?)\s*(?P<op><=|>=|==|!=|(?<![<>-])[<>](?![<>=]))\s*(?P<right>[^<>=!&|?]+)')
_INVERSE = {'<': '>=', '>=': '<', '>': '<=', '<=': '>', '==': '!=', '!=': '=='}


def _split(text, operator):
    """The operands of the top-level `operator` in `text`; [] when there is none or a `?:` or comma is outside them."""
    depth, begin, parts = 0, 0, []
    for token in _TOKEN.finditer(text):
        found = token[0]
        if found in ('(', '['):
            depth += 1
        elif found in (')', ']'):
            depth -= 1
        elif depth == 0 and found in ('?', ','):
            return []
        elif depth == 0 and found == operator:
            parts.append(text[begin:token.start()])
            begin = token.end()
    return [*parts, text[begin:]] if parts else []


def _bare(text):
    """`text` without the parentheses that enclose all of it."""
    text = text.strip()
    while text.startswith('(') and close(text, 0, '(', ')') == len(text) - 1:
        text = text[1:-1].strip()
    return text


def _inverse(condition):
    hit = _COMPARE.fullmatch(condition)
    if not hit or '->' in condition:
        return f'!({condition})'
    return f'{hit["left"].strip()} {_INVERSE[hit["op"]]} {hit["right"].strip()}'


def variants(source, name):
    span = find(source, name)
    if not span or '||' not in source:
        return []
    clean = _blank(source)
    out = []
    for number, m in enumerate(_IF.finditer(clean, span[0], span[1]), 1):
        end = close(clean, m.end() - 1, '(', ')')
        if end < 0:
            continue
        sides = _split(clean[m.end():end], '||')
        if len(sides) != 2:
            continue
        opening = end + 1 + len(clean[end + 1:span[1]]) - len(clean[end + 1:span[1]].lstrip())
        if not clean.startswith('{', opening):
            continue
        tail = close(clean, opening)
        if tail < 0 or _ELSE.match(clean, tail + 1) or _KEPT.search(clean, opening, tail):
            continue
        offset = m.end() + len(sides[0]) + 2
        first = source[m.end():m.end() + len(sides[0])]
        second = source[offset:end]
        inner = _bare(_blank(first))
        pair = _split(inner, '&&')
        if len(pair) != 2:
            continue
        text = _bare(first)
        a, b = _bare(text[:len(pair[0])]), _bare(text[len(pair[0]) + 2:])
        body, done = f'ladder_body_{number}', f'ladder_done_{number}'
        if re.search(rf'\b(?:{body}|{done})\b', clean):
            continue
        ladder = (f'{{\nif ({a}) {{\nif ({b}) {{\ngoto {body};\n}}\n}}\n'
                  f'if ({_inverse(_bare(second))}) {{\ngoto {done};\n}}\n'
                  f'{body}:\n{source[opening:tail + 1]}\n{done}:;\n}}')
        out.append((FAMILY, source[:m.start()] + ladder + source[tail + 1:]))
        if len(out) == LIMIT:
            break
    return out


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}
