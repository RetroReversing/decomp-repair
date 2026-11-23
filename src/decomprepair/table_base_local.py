"""A table's address held in a pointer local, where the slot's address is taken in the middle of an expression.

`table_base_stage` and `symbol_address_local` read the statement `p = &T[i];`. The game's C also took a slot's address
inside a condition, `if (flag && (p = &T[i], *p > 0)) { ... }` (m2c writes it the same way, with the sum spelled `(i * 2) +
&T`), and there the table's address is its own register: a pointer local assigned from the array name first, then the
slot from that pointer. In a 443-instruction KMC gcc 2.7.2 display-state updater (`-G0 -mips3 -mgp32 -mfp32 -O2`) the
two temporaries of the slot's address (`sll` of the index, `lui`/`addiu` of the table) came out in the other registers
until the table had a local pointer: local-alloc ranks quantities by `refs * log / life`, and a table address that is
set before the index's shift is allocated before it (`$v0` for the table, `$v1` for the shifted index, where the
unprepared expression gave them the other way round; 25 -> 5 of the last rows, with `field_array_base_local` 5 -> 0).

    if (*lp != NULL && (p = &T[i], *p > 0)) {      ->   if (*lp != NULL && (tab = T, p = tab + i, *p > 0)) {
    p = &T[i];                                     ->   tab = T;  p = tab + i;      (two statements)

`T` is declared `extern ty T[]` in the source or the header, `p` is a pointer local, and the site is a plain assignment
that stands as a statement of its own or as an element of a parenthesised comma list. One child per site, and one with
every site. The new local is a pointer to `T`'s element type, declared with the function's other locals. A candidate for
the exact judge, never a verdict.
"""
import re

from .arm_block_support import IDENT, local_declaration
from .integer_repair_support import edit, view

FAMILY = 'table_base_local'
FAMILIES = (FAMILY,)
LIMIT = 6

SLOT = re.compile(rf'(?P<v>{IDENT})\s*=(?!=)\s*&\s*(?P<sym>{IDENT})\s*\[(?P<idx>[^\[\];,()]+(?:\([^()]*\)[^\[\];,()]*)*)\]')


def _arrays(text):
    found = {}
    for hit in re.finditer(rf'(?m)^[ \t]*extern\s+(?P<type>(?:(?:unsigned|signed|const)\s+)*{IDENT})\s+(?P<name>{IDENT})\s*\[\s*[^\]]*\]\s*;', text or ''):
        found[hit['name']] = hit['type']
    return found


def variants(source, name, header=''):
    part = view(source, name)
    if not part:
        return []
    clean = part.clean
    arrays = {**_arrays(_blank_header(header)), **_arrays(clean[:part.opening])}
    if not arrays:
        return []
    sites = []
    for hit in SLOT.finditer(clean, part.opening + 1, part.end):
        if hit['sym'] not in arrays:
            continue
        declared = local_declaration(clean, part.opening, hit['v'])
        if not declared or not declared[1]:
            continue
        before = clean[:hit.start()].rstrip()[-1:]
        after = clean[hit.end():hit.end() + 40].lstrip()[:1]
        statement = before in ';{}' and after == ';'
        listed = before in '(,' and after in ',)'
        if not (statement or listed) or re.search(rf'\b{re.escape(hit["sym"])}\s*\[[^\]]*{re.escape(hit["v"])}\b', hit.group(0)):
            continue
        sites.append((hit, statement))
    if not sites:
        return []
    decl_at = clean.find('\n', part.opening) + 1
    indent = re.match(r'[ \t]*', source[decl_at:])[0] or '    '

    def made(chosen):
        edits, declarations = [], ''
        for number, (hit, statement) in chosen:
            tab = f'tab{number}'
            if re.search(rf'\b{tab}\b', clean):
                return None
            declarations += f'{indent}{arrays[hit["sym"]]} *{tab};\n'
            index = hit['idx'].strip()
            index = index if re.fullmatch(r'\w+', index) else f'({index})'
            slot = f'{hit["v"]} = {tab} + {index}'
            if statement:
                pad = re.match(r'[ \t]*', source[source.rfind('\n', 0, hit.start()) + 1:hit.start()])[0]
                edits.append((hit.start(), hit.end(), f'{tab} = {hit["sym"]};\n{pad}{slot}'))
            else:
                edits.append((hit.start(), hit.end(), f'{tab} = {hit["sym"]}, {slot}'))
        edits.append((decl_at, decl_at, declarations))
        return edit(source, edits)

    out = []
    numbered = list(enumerate(sites, 1))
    if len(numbered) > 1:
        text = made(numbered)
        if text and text != source:
            out.append((FAMILY, text))
    for item in numbered[:LIMIT - len(out)]:
        text = made([item])
        if text and text != source and (FAMILY, text) not in out:
            out.append((FAMILY, text))
    return out


def _blank_header(header):
    from .csource import _blank
    return _blank(header or '')


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'header')}
