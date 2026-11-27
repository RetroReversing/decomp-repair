"""A constant added before a subtraction, grouped with another operand: `(a + K) - b` as `a - (b - K)` or `(a - b) + K`.

gcc 2.x builds the tree as written, so which operand meets the constant decides which register is worked on first and
where the `addiu` sits: m2c reads `addiu a, a, 0x200; sra b, b, 5; subu a, a, b` back as `(a + 0x200) - (b >> 5)`,
while that spelling compiles with the `0x200` moved onto the other side (`addiu b, b, -0x200` before the `subu`).
`reassociate` leaves it alone: it regroups chains of one operator and never one holding a call. A 112-instruction N64
object update (SN GCC 2.8.1 `-G0 -mips3 -O2`) with `(h + 0x200) - (random() >> 5)` stood at 595 and the same line
written `h - ((random() >> 5) - 0x200)` took it to 385 alone and was one of the four edits of its match.

The value is the same in wrapping integer arithmetic; a floating literal is never matched (a regrouped float sum
rounds differently, so a left operand the reader sees to be a float is left alone). Proposals only; the byte judge
decides. One match, not read in the compiler source."""
import re

from .integer_repair_support import IDENT, edit, view

FAMILY = 'constant_term_regroup'
FAMILIES = (FAMILY,)
LIMIT = 8

_CONSTANT = re.compile(r'\+\s*(?P<k>0[xX][0-9a-fA-F]+|\d+)(?![\w.])')
_PRIMARY = re.compile(rf'{IDENT}(?:\s*(?:->|\.)\s*{IDENT})*')
_FLOAT = re.compile(r'\b(?:f32|f64|float|double)\b|\d\.\d')


def _close(text, at):
    """The offset past the bracket that closes the one at `at`, or None."""
    depth = 0
    for index in range(at, len(text)):
        depth += {'(': 1, '[': 1, ')': -1, ']': -1}.get(text[index], 0)
        if depth == 0:
            return index + 1
    return None


def _operand_before(text, end):
    """The start of the one primary operand (a name, a member chain, a call or a bracketed group) ending at `end`."""
    at = end
    while at and text[at - 1] in ' \t':
        at -= 1
    while at and text[at - 1] in ')]':
        depth = 0
        while at:
            at -= 1
            depth += {')': 1, ']': 1, '(': -1, '[': -1}.get(text[at], 0)
            if depth == 0:
                break
    while at and (text[at - 1].isalnum() or text[at - 1] in '_.' or text[at - 2:at] == '->'):
        at -= 2 if text[at - 2:at] == '->' else 1
    return at


def _operand_after(text, at):
    """`(start, end)` of the bracketed group or primary operand starting at or after `at`, or None."""
    while at < len(text) and text[at] in ' \t\n':
        at += 1
    if text[at:at + 1] == '(':
        end = _close(text, at)
        # a cast is not an operand of its own
        return (at, end) if end and not re.match(r'\s*[\w(]', text[end:]) else None
    found = _PRIMARY.match(text, at)
    if not found:
        return None
    end = found.end()
    while text[end:end + 1] in ('(', '['):
        end = _close(text, end)
        if not end:
            return None
    return at, end


def variants(source, name):
    part = view(source, name)
    if not part:
        return []
    clean = part.clean
    out = []
    for hit in _CONSTANT.finditer(clean, part.opening, part.end):
        first = _operand_before(clean, hit.start())
        left = clean[first:hit.start()].strip()
        if not left or left[0].isdigit() or _FLOAT.search(left):
            continue
        before = clean[:first].rstrip()
        rest = hit.end()
        after = re.match(r'\s*\)', clean[rest:])
        if after and before.endswith('('):  # `(a + K) - b`: not a call's or a cast's brackets
            opening = len(before) - 1
            if re.search(r'[\w\]]\s*$', clean[:opening]):
                continue
            start, rest = opening, rest + after.end()
        elif before.endswith(('=', '(', ',')) or before.endswith('return'):  # `a + K - b` starting an expression
            start = first
        else:
            continue
        minus = re.match(r'\s*-(?![-=>])', clean[rest:])
        second = minus and _operand_after(clean, rest + minus.end())
        if not second or re.match(r'\s*[*/%]', clean[second[1]:]):
            continue
        a, b, k = source[first:hit.start()].strip(), source[second[0]:second[1]], hit['k']
        for text in (f'{a} - ({b} - {k})', f'({a} - {b}) + {k}'):
            if start != first:  # the brackets that were there keep the new sum one operand
                text = f'({text})'
            out.append((FAMILY, edit(source, [(start, second[1], text)])))
        if len(out) >= LIMIT:
            break
    return list(dict.fromkeys(item for item in out if item[1] != source))[:LIMIT]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}
