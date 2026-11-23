"""A narrow loop-invariant local copied into a word local as the first statement of the loop body.

A `short` index that a loop only compares (`if (temp != index)`) is sign-extended by an insn inside the loop, which
loop.c moves to the loop's preheader like any other invariant. When the loop body also starts with another movable
(a bound read at the top, `limit = (&H)[-3];`, see `sibling_symbol_offset_read`), the movables go out in the order the
loop's insns have: the bound's load first, the extension (`move $a0, $s0`) second, and the target has them the other
way round (`blez $a2; subu; move $a0, $s0; lw $t0, -0xc($t0)`). A word local set from the narrow one as the body's first
statement (`idx = index;`), with the compare reading the local, makes the copy the first movable: 60 -> 0 in a
154-instruction save-slot function. (Hypothesis: `move_movables` emits in discovery order; the rows moved exactly as
that predicts, `loop.c` was not traced through.)

`loop_body_key_copy` is `loop_invariant_key_copy` written at the body's top instead of before the loop: for a local `V`
of a narrow integer type that the loop body reads and never writes (and the loop's own header does not need the copy),
`K = V;` becomes the first statement of the braced body and the body's reads of `V` read `K`. `K` is a `s32` declared
with the other locals. A `volatile` read or an address taken of `V` in the loop leaves the loop alone.
"""
import re

from .integer_repair_support import IDENT, _address_taken, edit, view
from .loop_invariant_key_copy import LOOP, WRITE, _loop_end
from .pattern_repairs import close

FAMILY = 'loop_body_key_copy'
FAMILIES = (FAMILY,)
LIMIT = 8
NARROW_TYPE = r'(?:[su](?:8|16)|char|short|(?:signed|unsigned)\s+(?:char|short))'


KEYWORDS = {'return', 'goto', 'else', 'if', 'while', 'for', 'do', 'switch', 'case', 'break', 'continue', 'default'}
DECLARATION = re.compile(rf'\s*(?:(?:unsigned|signed|const|volatile)\s+)*(?!(?:{"|".join(sorted(KEYWORDS))})\b){IDENT}\s+\**\s*{IDENT}'
                         rf'\s*(?:\[[^\]]*\])*\s*(?:=[^;{{}}]*)?;')


def _after_declarations(clean, cursor, end):
    """The offset past the leading declarations (initialisers may hold casts and calls)."""
    while True:
        match = DECLARATION.match(clean, cursor, end)
        if not match:
            return cursor
        cursor = match.end()


def _body(clean, loop_start, loop_end):
    """(open, close) of the braced body of the loop statement at `loop_start`, or None."""
    if clean.startswith('do', loop_start):
        opening = clean.find('{', loop_start)
    else:
        header = clean.find('(', loop_start)
        after = close(clean, header) if header >= 0 else None
        if after is None:
            return None
        opening = re.compile(r'\s*').match(clean, after).end()
        if clean[opening:opening + 1] != '{':
            return None
    stop = close(clean, opening, '{', '}')
    return (opening, stop) if stop and stop <= loop_end else None


def variants(source, name):
    part = view(source, name)
    if not part or re.search(r'\b(?:asm|__asm__|setjmp|longjmp)\b|(?m:^\s*#)', part.body):
        return []
    clean = part.clean
    top = _after_declarations(clean, part.opening + 1, part.end - 1)
    decls = {}
    for hit in re.finditer(rf'\b(?P<type>{NARROW_TYPE})\s+(?P<name>{IDENT})\s*(?:=[^;]*)?;', clean[part.opening + 1:top]):
        decl_name = hit['name']
        if len(re.findall(rf'\b(?:[su](?:8|16|32)|int|short|char|long)\s*\**\s*{decl_name}\b', part.body)) == 1 \
                and not _address_taken(part.body, decl_name):
            decls[decl_name] = hit
    if not decls:
        return []
    out = []
    for loop in LOOP.finditer(clean, part.opening + 1, part.end):
        end = _loop_end(clean, loop.start(), part.end)
        span = _body(clean, loop.start(), end) if end else None
        if not span:
            continue
        opening, stop = span
        body = clean[opening + 1:stop - 1]
        if re.search(r'\b(?:volatile|goto|case|default|continue|break)\b|\b' + IDENT + r'\s*:(?!:)', body):
            continue
        for var, decl in decls.items():
            if part.opening + 1 + decl.start() > loop.start() or not re.search(rf'(?<![\w.>]){var}\b', body):
                continue
            if re.search(WRITE.format(v=re.escape(var)), clean[loop.start():end]):
                continue
            key = f'{var}_copy'
            if re.search(rf'\b{key}\b', clean):
                continue
            first = re.compile(r'\s*').match(clean, opening + 1).end()
            indent = re.match(r'[ \t]*', clean[clean.rfind('\n', 0, first) + 1:first])[0] if '\n' in clean[opening:first] else ' '
            swapped = re.sub(rf'(?<![\w.>]){var}\b', key, source[first:stop - 1])
            edits = [(top, top, f'\n  s32 {key};'), (first, stop - 1, f'{key} = {var};\n{indent}' + swapped)]
            out.append((FAMILY, edit(source, edits)))
    return out[:LIMIT]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}
