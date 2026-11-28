"""A local initialised in its declaration and read once, by the next statement, written where it is read.

`{ s32 base = gCount; verts = &((Vtx *) gDots)[base]; }` keeps the load of the index ahead of the load of the pointer;
`verts = &((Vtx *) gDots)[gCount];` lets the compiler load them in the expression's own order. `single_use_inline` takes
an assignment or a literal initialiser, and a non-literal initialiser only when it is read twice or more, so a one-read
global kept in a declaration had no family: a glyph drawing function sat at 20 (two `lui` in each other's places) until
the index was written into the subscript (-> 0, SN GCC 2.8.1, docs of decompdecomp:
docs/learnings/function/glyph-vertex-index-initializer-inline.md).

The initialiser must be pure (no call, assignment, increment or address of a local) and the statement that reads it a
plain expression statement or `return` that calls nothing and changes nothing the initialiser reads, so the value is the
same where it moves to. A local narrower or of another type than the global it reads keeps its conversion as a cast.
"""
import re

from .csource import _blank
from .integer_repair_support import edit, view
from .local_inline_repairs import _block_end, _plain

FAMILY = 'initializer_single_use_inline'
FAMILIES = (FAMILY,)

_SCALAR = r'(?:unsigned\s+(?:char|short|int)|signed\s+(?:char|short|int)|[su](?:8|16|32)|char|short|int|f32|float)'
# one declarator with an initialiser, starting a line or following `{` or `;`: `s32 i = G;`, `Vtx *p = D_x + 4;`
_DECL = re.compile(rf'(?:(?<=[{{;])|^)[ \t]*(?P<type>{_SCALAR}(?:\s*\*+|(?=\s))|[A-Za-z_]\w*\s*\*+)\s*'
                   r'(?P<name>[A-Za-z_]\w*)\s*=(?!=)\s*(?P<expr>[^;{}=,]+);', re.M)
# the statement right after it: an expression statement or a return, on one logical line, holding no block
_NEXT = re.compile(r'\s*(?P<statement>[^;{}]+;)')
_CONTROL = re.compile(r'^(?:if|for|while|do|switch|else|case|default|goto)\b|^[A-Za-z_]\w*\s*:(?!:)')
# a cast: not after a name (`find(x)` is a call), and followed by its operand
_CAST = re.compile(r'(?<![\w\]])(?<![\w\]]\s)\(\s*(?:const\s+|struct\s+|unsigned\s+)?[A-Za-z_]\w*(?:\s*\*)*\s*\)(?=\s*[\w(&*~!])')


def _calls(text):
    """A call (or `sizeof`, or a macro) left once the casts are taken out."""
    return bool(re.search(r'[\w\])]\s*\(', _CAST.sub('', re.sub(r'\breturn\b', '=', text))))


def _volatile(expression, body, context):
    """A volatile access could move: any in the function, or a name the expression reads declared volatile. A
    project header's other volatile registers are not this function's."""
    if re.search(r'\bvolatile\b', body):
        return True
    return any(re.search(rf'\bvolatile\b[^;{{}}]*\b{word}\b', context) for word in set(re.findall(r'[A-Za-z_]\w*', expression)))


def _same_type(expression, kind, context):
    """Whether `expression` is a global declared with exactly `kind`, so no conversion is lost with the local."""
    if not re.fullmatch(r'[A-Za-z_]\w*', expression):
        return False
    declared = re.findall(rf'(?m)^[ \t]*extern\s+([^;()\[\]{{}}=,]*?[\s*])\s*{expression}\s*;', context)
    return bool(declared) and all(re.sub(r'\s+', '', d) == re.sub(r'\s+', '', kind) for d in declared)


def variants(source, name, header='', limit=8):
    part = view(source, name)
    if not part or re.search(r'\b(?:asm|__asm|__asm__)\b', part.body):
        return []
    clean, base = part.clean, part.opening + 1
    context = _blank(header) + '\n' + clean
    result = []
    for decl in _DECL.finditer(clean, base, part.end):
        kind, local = decl['type'].strip(), decl['name']
        expression = source[decl.start('expr'):decl.end('expr')].strip()
        bare = _CAST.sub('', expression)
        if not _plain(bare) or _calls(expression) or _volatile(expression, part.body, context):
            continue
        following = _NEXT.match(clean, decl.end(), part.end)
        if not following:
            continue
        statement = following['statement'].strip()
        if _CONTROL.match(statement) or _calls(statement) or '++' in statement or '--' in statement:
            continue
        block_end = _block_end(clean, base, decl.start(), part.end)
        if block_end is None:
            continue
        reads = [m for m in re.finditer(rf'(?<![\w.])(?<!->){local}\b', clean[decl.end():block_end])]
        if len(reads) != 1:
            continue
        at = decl.end() + reads[0].start()
        if not following.start('statement') <= at < following.end('statement'):
            continue
        before, after = clean[:at].rstrip(), clean[at + len(local):].lstrip()
        if before.endswith('&') and not before.endswith('&&'):
            continue  # its address (or a mask, which reads the same either way: leave it)
        if re.match(r'(?:[-+*/%&|^]|<<|>>)?=(?!=)', after):
            continue
        # a store in the reading statement happens after its operands are read; two stores could change one first
        if len(re.findall(r'(?<![=!<>])=(?!=)', statement)) > 1:
            continue
        text = expression
        simple = re.fullmatch(r'[A-Za-z_]\w*', expression)
        if not _same_type(expression, kind, context):
            text = f'({kind}) {expression}' if simple else f'({kind}) ({expression})'
        if not (before.endswith('[') and after.startswith(']')) and not re.fullmatch(r'[A-Za-z_]\w*', text):
            text = f'({text})'
        line_end = clean.find('\n', decl.end())
        stop = decl.end()
        if line_end >= 0 and not clean[stop:line_end].strip():
            stop = line_end + 1
        result.append((FAMILY, edit(source, [(decl.start(), stop, ''), (at, at + len(local), text)])))
        if len(result) >= limit:
            break
    return result


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'header')}
