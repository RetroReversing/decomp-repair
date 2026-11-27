"""Two spellings GCC 2.7.2 at `-O1` keeps apart that leave what the function does unchanged.

`empty_cse_fence`: cse follows a table's address from a test (`if (t[i] != 0)`) into the calls after it and keeps
it in a saved register, where the target forms it again at each use. The notes of an empty `do { } while (0);` end
cse's block there. On an 832-instruction N64 drawing function one before the first call of an arm took the saved
register (and eight bytes of frame) back out.

`subterm_into_idle_local`: a product that heads a call argument is a temporary of its own block, so local
allocation may overwrite it in its source register. Written into a local that another block uses (`(n = i * 14) + 58`)
that local becomes one pseudo of the whole function, allocated by global.c instead, and the other block's use stops
being tied to it. A 734-instruction N64 function went from 15 to 0 with it. Only a local every read of which follows an
assignment in the read's own block is borrowed, and never between the two.
"""
import re

from .integer_repair_support import IDENT, edit, view
from .pattern_repairs import close

FAMILIES = ('empty_cse_fence', 'subterm_into_idle_local')
FENCE = 'do { } while (0);'
LIMIT = 48
_STATEMENT = re.compile(rf'(?<=[;{{}}])\s*({IDENT})\s*\(')
_KEYWORDS = {'if', 'while', 'for', 'switch', 'sizeof', 'return', 'do'}
_TABLE = re.compile(rf'\b({IDENT})\s*\[')
_INTEGER = r'(?:s32|u32|int|long)'


def _calls(clean, opening, end):
    """(start of the callee's name, end past the `;`) of every call statement in the body."""
    found = []
    for match in _STATEMENT.finditer(clean, opening, end):
        if match[1] in _KEYWORDS:
            continue
        stop = close(clean, match.end() - 1)
        tail = re.compile(r'\s*;').match(clean, stop) if stop else None
        if tail:
            found.append((match.start(1), tail.end()))
    return found


def fences(source, part):
    clean = part.clean
    calls = _calls(clean, part.opening, part.end)
    sites = []
    for match in re.finditer(r'\bif\s*\(', clean[part.opening:part.end]):
        paren = part.opening + match.end() - 1
        stop = close(clean, paren)
        if not stop:
            continue
        tables = set(_TABLE.findall(clean[paren:stop]))
        if not tables:
            continue
        following = [call for call in calls if call[0] > stop][:3]
        for index, (start, finish) in enumerate(following):
            if tables & set(_TABLE.findall(clean[start:finish])):
                sites += [call[0] for call in following[:index + 1]]
                break
    result = []
    for site in dict.fromkeys(sites):
        if not clean[:site].rstrip().endswith(FENCE):
            result.append(edit(source, [(site, site, FENCE + ' ')]))
    return result[:LIMIT]


def _blocks(clean, opening, end):
    """(open, close) of every brace block of the body, innermost last for any position inside it."""
    stack, found = [], []
    for brace in re.compile(r'[{}]').finditer(clean, opening, end):
        if brace[0] == '{':
            stack.append(brace.start())
        elif stack:
            found.append((stack.pop(), brace.start()))
    return sorted(found)


def _block(blocks, opening, position):
    """The `{` of the innermost block around `position`."""
    return max((start for start, stop in blocks if start < position < stop), default=opening)


def _live_spans(clean, blocks, opening, end, name):
    """[(assignment, read)] of a local whose every read follows an assignment in its own block, or None."""
    body = clean[opening:end]
    if re.search(rf'&\s*{name}\b|\b{name}\s*(?:\+\+|--|[-+*/|&^]=|<<=|>>=)|(?:\+\+|--)\s*{name}\b', body):
        return None
    assigned, spans = {}, []
    declaration = re.search(rf'\b{_INTEGER}\s+{name}\s*;', body)
    for match in re.finditer(rf'\b{name}\b', body):
        position = opening + match.start()
        if declaration and declaration.start() <= match.start() < declaration.end():
            continue
        block = _block(blocks, opening, position)
        before = clean[:position].rstrip()
        if re.compile(r'\s*=(?!=)').match(clean, position + len(name)) and before.endswith((';', '{', '}', ':')):
            assigned[block] = position
            continue
        chain = block
        while chain not in assigned and chain > opening:
            chain = _block(blocks, opening, chain)
        if chain not in assigned:
            return None
        spans.append((assigned[chain], position))
    return spans if assigned else None


def borrowed(source, part):
    clean = part.clean
    body = clean[part.opening:part.end]
    names = re.findall(rf'(?m)^\s*{_INTEGER}\s+({IDENT})\s*;', body)
    blocks = _blocks(clean, part.opening, part.end)
    locals_ = {name: _live_spans(clean, blocks, part.opening, part.end, name) for name in names}
    result = []
    for start, finish in _calls(clean, part.opening, part.end):
        for match in re.finditer(rf'(?<=[(,])(\s*)({IDENT}\s*\*\s*(?:0[xX][0-9a-fA-F]+|\d+))(?=\s*\+)',
                                 clean[start:finish]):
            site = start + match.start(2)
            stop = start + match.end(2)
            factor = match[2].split('*')[0].strip()
            for name, spans in locals_.items():
                if spans is None or name == factor or any(a < site < b for a, b in spans):
                    continue
                result.append(edit(source, [(site, stop, f'({name} = {source[site:stop]})')]))
    return result[:LIMIT]


def variants(source, name, header=''):
    part = view(source, name)
    if not part or '__LINE__' in source + header:
        return []
    return ([(FAMILIES[0], child) for child in fences(source, part)]
            + [(FAMILIES[1], child) for child in borrowed(source, part)])


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'header')}
