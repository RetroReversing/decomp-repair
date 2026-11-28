"""A global index read into a local before the global pointer it indexes (GCC, N64).

`vtx = &gVerts[gVertCount];` and `s32 n = gVertCount; vtx = &gVerts[n];` are the same address and not the same bytes:
with both globals in one expression GCC loads the pointer first (`lui %hi(gVerts)` before `lui %hi(gVertCount)`), with the
index in a statement of its own the target's order comes out (index first, then the pointer). The two loads also swap in
the `base + index` spelling. On a 184-instruction N64 model-drawing function (`sn-n64-281 -G0 -mips3 -O2`) this was the
last step: 20 -> 0, the one difference being which of the two `lui`s came first.

`operand_temporary` (expression_locals) stages a sum's operand only when the function never writes that global, and does
not look inside a subscript. This function advanced the count in the loop that followed, which is the usual shape of
"append N records at the end of a list": the read is taken right before its own statement, so a later write does not
matter. A statement that calls a function or writes the global itself is left alone.

`variants` takes each plain statement that holds `pointer[index]`, `pointer + index` or `index + pointer`, where both
names are file-scope `extern` globals (a pointer and an integer), and reads the index into `__repair_index` first. One
child per site. The judge decides.
"""
import re

from .csource import _code_only, find

FAMILY = 'global_index_staged'
FAMILIES = (FAMILY,)
MAX_CHILDREN = 6

_INTEGER = r'(?:s8|u8|s16|u16|s32|u32|(?:(?:unsigned|signed)\s+)?(?:char|short|int|long)|unsigned|size_t)'
_INDEX_GLOBAL = re.compile(rf'(?m)^[ \t]*extern\s+({_INTEGER})\s+([A-Za-z_]\w*)\s*;')
_POINTER_GLOBAL = re.compile(r'(?m)^[ \t]*extern\s+(?:(?:struct|union|unsigned|signed)\s+)?[A-Za-z_]\w*\s*\*+\s*([A-Za-z_]\w*)\s*;')
_STATEMENT = re.compile(r'[^;{}]+;')
_CONTROL = re.compile(r'\b(?:if|for|while|do|else|switch|case|default|goto|sizeof)\b|[?:#]')
_CALL = re.compile(r'(?:[A-Za-z_]\w*|\]|\))\s*\(\s*(?!\s*\*)')
_DECLARATION = re.compile(r'\s*(?:(?:struct|union|unsigned|signed|const|volatile|static|register)\s+)*[A-Za-z_]\w*(?:\s*\*+\s*|\s+)[A-Za-z_]\w*\s*(?:=(?!=)|\[|;|,)')
_CAST = re.compile(r'\(\s*(?:(?:struct|union|unsigned|signed|const|volatile)\s+)*[A-Za-z_]\w*[\s*]*\)')


def _sites(statement, pointers, indexes):
    """(start, end, index name) of each global index beside a global pointer in `statement`."""
    found = []
    for name in indexes:
        n = re.escape(name)
        uses = list(re.finditer(rf'(?<![\w.>]){n}(?!\w)', statement))
        if len(uses) != 1:
            continue
        start, end = uses[0].span()
        before, after = statement[:start].rstrip(), statement[end:].lstrip()
        if after.startswith(('++', '--', '[', '.', '->', '(')) or before.endswith(('++', '--', '&')) \
                or re.match(r'(?:[-+*/%&|^]|<<|>>)?=(?!=)', after):
            continue
        subscript = re.search(r'(?<![\w.>])([A-Za-z_]\w*)\s*\[$', before)
        left = re.search(r'(?<![\w.>])([A-Za-z_]\w*)\s*\+$', before)
        right = re.match(r'\+\s*([A-Za-z_]\w*)(?![\w\[.(]|\s*->)', after)
        if (subscript and subscript[1] in pointers and after.startswith(']')) \
                or (left and left[1] in pointers and not after.startswith(('*', '/', '[', '.'))) \
                or (right and right[1] in pointers and not before.endswith(('*', '/', '-'))):
            found.append((start, end, name))
    return found


def variants(source, name, header=''):
    span = find(source, name)
    if not span:
        return []
    clean = _code_only(source)
    opening = clean.find('{', span[0], span[1])
    if opening < 0:
        return []
    outside = _code_only(header or '') + '\n' + clean[:span[0]] + clean[span[1]:]
    pointers = set(_POINTER_GLOBAL.findall(outside))
    indexes = {g: ' '.join(kind.split()) for kind, g in _INDEX_GLOBAL.findall(outside)}
    body = clean[opening + 1:span[1]]
    indexes = {g: kind for g, kind in indexes.items() if re.search(rf'\b{re.escape(g)}\b', body)}
    if not pointers or not indexes or '__repair_index' in body:
        return []
    out = []
    for hit in _STATEMENT.finditer(body):
        statement = hit[0]
        if _CONTROL.search(statement) or _DECLARATION.match(statement) or _CALL.search(_CAST.sub(' ', statement)):
            continue
        # a piece of a `for (...)` header: its parentheses don't close inside the piece
        if statement.count('(') != statement.count(')'):
            continue
        lead = len(statement) - len(statement.lstrip())
        for start, end, index in _sites(statement, pointers, indexes):
            at, first, last = (opening + 1 + hit.start() + offset for offset in (lead, start, end))
            line = source.rfind('\n', 0, at) + 1
            indent = re.match(r'[ \t]*', source[line:])[0]
            child = (source[:opening + 1] + f'\n    {indexes[index]} __repair_index;' + source[opening + 1:at]
                     + f'__repair_index = {index};\n{indent}' + source[at:first] + '__repair_index' + source[last:])
            out.append((FAMILY, child))
            if len(out) >= MAX_CHILDREN:
                return out
    return out


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'header')}
