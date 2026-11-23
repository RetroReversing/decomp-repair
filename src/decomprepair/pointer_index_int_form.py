"""An element address written as an integer sum, so the scaled index is the first operand of the add.

`p = &base[i];` and `p = base + i;` are built pointer first: the add is `addu $a2,$s3,$v0` with the base register
before the scaled index. The game had `addu $a2,$v0,$s3`. Written `p = (T *) (i * 2 + (s32) base);` the integer
sum keeps the operand order it was written in, and the same insns come out with the index first. In a `gcc-2.7.2-kmc`
save-slot reset loop that was the only operand difference of two stores through pointers (70 -> 60), and no family
produced it: `measured_guarded_index` covers a guarded index, `address_association_repairs` byte pointers.

Offered for `LHS = &BASE[INDEX];` and `LHS = BASE + INDEX;` (also as a pointer local's initializer) where BASE is a local or global pointer or array of a
2, 4 or 8 byte integer or float type declared in the function or in the file, and INDEX is an identifier, an integer
literal or a short sum or product of them. One child per assignment (`pointer_index_int_form`) and, with two or more,
a child with all of them (`pointer_index_int_form_all`). A hypothesis; the judge decides.
"""
import re

from .integer_repair_support import IDENT, edit, view

FAMILY = 'pointer_index_int_form'
FAMILY_ALL = 'pointer_index_int_form_all'
FAMILIES = (FAMILY, FAMILY_ALL)
LIMIT = 6
SIZES = {'s16': 2, 'u16': 2, 'short': 2, 'unsigned short': 2, 's32': 4, 'u32': 4, 'int': 4, 'unsigned int': 4, 'f32': 4,
         'float': 4, 's64': 8, 'u64': 8, 'f64': 8, 'double': 8}
TYPE = '|'.join(sorted((re.escape(t).replace(r'\ ', r'\s+') for t in SIZES), key=len, reverse=True))
INDEX = rf'(?:{IDENT}|\d+)(?:\s*[-+*]\s*(?:{IDENT}|\d+))?'
ASSIGN = re.compile(rf'(?m)^(?P<indent>[ \t]*)(?P<decl>(?:{IDENT}[ \t]*\*[ \t]*)?)(?P<lhs>{IDENT})\s*=\s*(?:&\s*(?P<base>{IDENT})\s*\[\s*(?P<index>{INDEX})\s*\]|'
                    rf'(?P<base2>{IDENT})\s*\+\s*(?P<index2>{INDEX}))\s*;')


def _element(clean, glob):
    """The byte size of one element of the pointer or array GLOB, from its declaration, or None."""
    for hit in re.finditer(rf'(?m)^[ \t]*(?:extern[ \t]+)?(?P<type>{TYPE})[ \t]*(?P<stars>\*?)[ \t]*{re.escape(glob)}[ \t]*(?P<array>\[[^\]]*\])?[ \t]*(?:=[^;]*)?;', clean):
        if hit['stars'] or hit['array']:
            return SIZES[re.sub(r'\s+', ' ', hit['type'])], re.sub(r'\s+', ' ', hit['type'])
    for hit in re.finditer(rf'[(,][ \t]*(?P<type>{TYPE})[ \t]*\*[ \t]*{re.escape(glob)}[ \t]*[,)]', clean):
        return SIZES[re.sub(r'\s+', ' ', hit['type'])], re.sub(r'\s+', ' ', hit['type'])
    return None


def variants(source, name):
    part = view(source, name)
    if not part:
        return []
    clean = part.clean
    body = clean[part.opening:part.end]
    found = []
    for hit in ASSIGN.finditer(body):
        glob = hit['base'] or hit['base2']
        index = (hit['index'] or hit['index2']).strip()
        kind = _element(clean, glob)
        if not kind:
            continue
        size, spelling = kind
        if re.fullmatch(r'\d+', index):
            continue
        if re.search(rf'\b{re.escape(hit["lhs"])}\b', index) or hit['lhs'] == glob:
            continue
        scaled = f'({index}) * {size}' if re.search(r'[-+*]', index) else f'{index} * {size}'
        text = f'{hit["indent"]}{hit["decl"]}{hit["lhs"]} = ({spelling} *) ({scaled} + (s32) {glob});'
        found.append((part.opening + hit.start(), part.opening + hit.end(), text))
    found = found[:LIMIT]
    out = [(FAMILY, edit(source, [one])) for one in found]
    if len(found) > 1:
        out.append((FAMILY_ALL, edit(source, found)))
    return out


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}
