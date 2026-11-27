"""A byte pointer plus a byte index under a pointer cast, written as an integer sum with the index first.

    *(s32 *)(base + idx)  ->  *(s32 *)(idx + (s32) base)        and        *(s32 *)((s32) base + idx)

`base + idx` on a `char *` or `u8 *` is pointer arithmetic: the add keeps the pointer first, `addu $v0,$a2,$v0`. The
target of an SN GCC 2.7.2 N64 setter had the scaled index first, `addu $v0,$v0,$a2`, the only difference (5) of a
function whose every hand spelling of the same sum (parenthesised, hoisted into a temporary, the index re-read from
the table) compiled to the same wrong order. The sum is built as an integer, where the operand order written is the
order kept: `(idx + (s32) base)` scored 0; `((s32) base + idx)` stays pointer-first (5), so both are offered.
`pointer_index_int_form` does this for `p = base + i` of 2, 4 and 8 byte elements, `reassociate` and
`address_association` regroup a longer sum; this is the byte pointer under a cast.

Offered for `(T *) (P + E)` (a cast to a pointer, then a parenthesised sum) where P is an identifier declared in the
function or the file as a pointer or array of one-byte elements (`char`, `u8`, `s8`, `void`) and E is an expression
without a call or assignment that does not name P. One child per site and operand order, and one with every site
(`byte_pointer_sum_int_first`). A hypothesis from the operand order, not read from the compiler's source; the judge
decides.
"""
import re

from .integer_repair_support import IDENT, edit, view

FAMILY = 'byte_pointer_sum_int_first'
FAMILIES = (FAMILY,)
LIMIT = 8
BYTE_TYPES = {'char', 'u8', 's8', 'void', 'M2C_UNK8', 'int8_t', 'uint8_t', 'Byte', 'u_char'}
QUALIFIERS = {'extern', 'static', 'const', 'register', 'volatile', 'struct', 'union', 'enum', 'signed', 'unsigned'}
SITE = re.compile(rf'\(\s*[A-Za-z_][\w \t]*\*\s*\)\s*\(\s*(?P<p>{IDENT})\s*\+\s*(?!\+)')


def _byte_pointer(clean, name):
    """Whether NAME is declared as a pointer or array of one-byte elements."""
    escaped = re.escape(name)
    for hit in re.finditer(rf'\b(?P<type>{IDENT})\s*(?P<stars>\*+)\s*{escaped}\b(?!\s*\()', clean):
        before = clean[:hit.start()].rstrip()
        if not before or before[-1] in ';{}(,' or (re.search(rf'({IDENT})$', before) or [0, ''])[1] in QUALIFIERS:
            return len(hit['stars']) == 1 and hit['type'] in BYTE_TYPES
    for hit in re.finditer(rf'\b(?P<type>{IDENT})\s+{escaped}\s*\[', clean):
        if hit['type'] not in QUALIFIERS:
            return hit['type'] in BYTE_TYPES
    return False


def _close(text, start):
    """The index of the ')' that closes the '(' before START, or -1."""
    depth = 1
    for index in range(start, len(text)):
        if text[index] in '([':
            depth += 1
        elif text[index] in ')]':
            depth -= 1
            if not depth:
                return index
    return -1


def variants(source, name):
    part = view(source, name)
    if not part:
        return []
    clean = part.clean
    found = []
    for hit in SITE.finditer(clean, part.opening, part.end):
        end = _close(clean, hit.end())
        if end < 0 or clean[end] != ')':
            continue
        index = clean[hit.end():end].strip()
        if (not index or re.search(r'(?<![=!<>])=(?!=)|\+\+|--|\(\s*\)|\b' + IDENT + r'\s*\(', index)
                or re.search(rf'\b{re.escape(hit["p"])}\b', index) or not _byte_pointer(clean, hit['p']) or index[0] in '*&'):
            continue
        whole = index[0] == '(' and _close(index, 1) == len(index) - 1
        wrapped = f'({index})' if re.search(r'[<>&|^?:=!]', index) and not whole else index
        found.append((hit.start('p'), end, hit['p'], wrapped))
    found = found[:LIMIT]
    out = []
    for order in (0, 1):
        edits = [(site[0], site[1], (f'{site[3]} + (s32) {site[2]}', f'(s32) {site[2]} + {site[3]}')[order])
                 for site in found]
        out += [(FAMILY, edit(source, [one])) for one in edits]
        if len(edits) > 1:
            out.append((FAMILY, edit(source, edits)))
    return out


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}
