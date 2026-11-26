"""Calls fitted to the argument counts the destination's header declares.

Another game's matched C, renamed for a look-alike, can call a function whose prototype there takes another number of
arguments (a parameter added or dropped between the two games, or a draft's guess). decompdecomp's preflight
(repair_preflight.invalid_call) rightly refused to compile such a candidate, so the donor was never tried at all. Here
each direct call to a function with one fixed, plainly typed prototype in the header is given that many arguments:
extra trailing ones dropped, missing ones passed as 0. Only the judge says whether that is what the target does."""
import re

from .csource import find
from .repair_preflight import _header, clean

FAMILY = 'call_arity'
FAMILIES = (FAMILY,)
CALL = re.compile(r'(?<![\w.>])([A-Za-z_]\w*)\s*\(')
PUNCTUATION = re.compile(r'[()\[\]{},]')


def _arguments(text, opening):
    """(end of the call's closing parenthesis, [(start, end) of each top-level argument]) or None."""
    depth, start, spans = 0, opening + 1, []
    for m in PUNCTUATION.finditer(text, opening):
        char = m.group(0)
        if char in '([{':
            depth += 1
        elif char in ')]}':
            depth -= 1
            if depth == 0:
                if text[start:m.start()].strip() or spans:
                    spans.append((start, m.start()))
                return m.end(), spans
        elif char == ',' and depth == 1:
            spans.append((start, m.start()))
            start = m.end()
    return None


def fit(source, name, header=''):
    """`source` with every call that disagrees with a fixed prototype in `header` given its declared count; '' when
    nothing needed fitting or a call can't be read."""
    _, unknown, complete, declared = _header(header or '')
    if unknown or not complete or not declared:
        return ''
    span = find(source, name)
    if not span:
        return ''
    text = clean(source)
    body_start = text.find('{', span[0])
    if body_start < 0 or body_start > span[1]:
        return ''
    edits = []
    for call in CALL.finditer(text, body_start, span[1]):
        counts = declared.get(call.group(1))
        if not counts or len(counts) != 1 or None in counts:
            continue
        if re.search(rf'\b{re.escape(call.group(1))}\b(?!\s*\()', text[span[0]:span[1]]):
            continue  # a local of that name, or the function's address taken: not a plain call
        read = _arguments(text, call.end() - 1)
        if read is None:
            return ''
        end, spans = read
        expected = next(iter(counts))
        if len(spans) == expected:
            continue
        kept = [source[a:b].strip() for a, b in spans[:expected]] + ['0'] * max(0, expected - len(spans))
        edits.append((call.end(), end - 1, ', '.join(kept)))
    if not edits:
        return ''
    out = source
    for start, end, replacement in sorted(edits, reverse=True):
        out = out[:start] + replacement + out[end:]
    return out


def variants(source, name, header=''):
    fitted = fit(source, name, header)
    return [(FAMILY, fitted)] if fitted else []


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'header')}
