"""An array element updated in place, and a one-line reader helper expanded at its call sites.

Two m2c-era shapes that gcc 2.7.2 schedules differently from the game's source:

- `p = &table[row][col]; *p += 1;` (the address kept in a local, then a compound update through it) against
  `table[row][col] += 1;`. The local pointer is a pseudo that lives across the statements between its two uses; written
  in place the compiler computes the address once, where it is needed. `element_pointer_compound` offers the in-place
  form when the pointer is used nowhere else.
- `static inline u8 field(void *o) { return ((Field_u8 *) (((char *) o) + 0x34))->v; }` and `table[row][field(o)]`
  against the field read written at the use. A call to an inline helper is expanded at the point of the call as a
  scope of its own (parameter pseudo, return pseudo), which in a subscript moves the column load ahead of the row's
  arithmetic in the first scheduler's order; the plain read has the load where the target does. `index_helper_unwrap`
  expands every call of a single-`return` helper whose argument is a plain name.

`element_update_shape` is both at once. On a 374-instruction N64 effect spawner (KMC GCC 2.7.2,
`-G0 -mips3 -mgp32 -mfp32 -O2`) the compound update alone scored 1197 against 1397 (a gain), the unwrap alone 657
against 392 (a loss), and the two together 22 against 392: the loss and the gain are one edit to the scheduler, so the
pair is one child (docs/COMPILER_MATCHING_LEARNINGS.md). Hypothesis, not confirmed in the compiler source: the first
scheduler's priorities on the row's `sll/subu` chain and the column's load change together with where the helper's scope
ends.
"""
import re

from .integer_repair_support import IDENT, edit, view

FAMILY_COMPOUND = 'element_pointer_compound'
FAMILY_UNWRAP = 'index_helper_unwrap'
FAMILY_BOTH = 'element_update_shape'
FAMILIES = (FAMILY_COMPOUND, FAMILY_UNWRAP, FAMILY_BOTH)
HELPER = re.compile(rf'(?:static\s+inline|inline\s+static)\s+(?P<ret>{IDENT}(?:\s+{IDENT})?)\s+(?P<name>{IDENT})\s*\(\s*[\w\s*]+?\b(?P<param>{IDENT})\s*\)\s*'
                    r'{\s*return\s+(?P<expression>[^;{}]+);\s*}')
COMPOUND = re.compile(rf'(?P<pointer>{IDENT})\s*=\s*&\s*(?P<lvalue>[^;{{}}]+?);\s*\*\s*(?P=pointer)\s*(?P<operator>[-+*|&^]|<<|>>)=\s*(?P<value>[^;{{}}]+);')


def _compound(source, part):
    """The function with each single-use `p = &x; *p op= e;` written as `x op= e;`, or None."""
    edits = []
    helpers = {helper['name'] for helper in HELPER.finditer(part.clean)}  # pure one-line readers may stay in the address
    for hit in COMPOUND.finditer(part.clean, part.opening, part.end):
        pointer = hit['pointer']
        uses = len(re.findall(rf'(?<![\w.>]){re.escape(pointer)}\b', part.clean[part.opening:part.end]))
        declared = re.search(rf'\*\s*{re.escape(pointer)}\s*;', part.clean[part.opening:part.end])
        if uses != (3 if declared else 2) or re.search(rf'\b{re.escape(pointer)}\b', hit['lvalue']):
            continue
        casts_removed = re.sub(r'\(\s*[\w\s]+\*+\s*\)', '', hit['lvalue'])
        if any(called not in helpers for called in re.findall(rf'(?<![\w])({IDENT})\s*\(', re.sub(r'\bsizeof\b', '', casts_removed))):
            continue
        edits.append((hit.start(), hit.end(), f"{source[hit.start('lvalue'):hit.end('lvalue')].strip()} {hit['operator']}= {source[hit.start('value'):hit.end('value')].strip()};"))
    return edit(source, edits) if edits else None


def _unwrap(source, part):
    """The function with each call of a one-line helper expanded, or None."""
    edits = []
    for helper in HELPER.finditer(_clean(source)):
        name, param, expression, ret = helper['name'], helper['param'], helper['expression'].strip(), helper['ret'].strip()
        if helper.start() > part.opening or re.search(rf'\b{re.escape(name)}\s*\(|\b{re.escape(name)}\s*=', helper['expression']):
            continue
        cast = '' if re.search(rf'\bField_{re.escape(ret)}\b', expression) else f'({ret}) '
        for call in re.finditer(rf'(?<![\w.>]){re.escape(name)}\s*\(\s*(?P<argument>{IDENT})\s*\)', part.clean[part.opening:part.end]):
            where = part.opening + call.start()
            body = re.sub(rf'(?<![\w.>]){re.escape(param)}\b', call['argument'], expression)
            edits.append((where, part.opening + call.end(), f'{cast}({body})' if cast else body))
    return edit(source, edits) if edits else None


def _clean(source):
    from .csource import _blank
    return _blank(source)


def variants(source, name):
    part = view(source, name)
    if not part or re.search(r'\b(?:asm|__asm__|setjmp|longjmp)\b|^\s*#', part.body, re.M):
        return []
    compound = _compound(source, part)
    unwrapped = _unwrap(source, part)
    result = []
    if compound:
        result.append((FAMILY_COMPOUND, compound))
    if unwrapped:
        result.append((FAMILY_UNWRAP, unwrapped))
    if compound and unwrapped:
        both_part = view(compound, name)
        both = _unwrap(compound, both_part) if both_part else None
        if both:
            result.append((FAMILY_BOTH, both))
    return result
