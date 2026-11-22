"""Pair a typed sign-field read with the missing slot in a later clamp."""

import re

from .balanced_clamp_predicates import _clamp_edit, _clamp_sites, _clamp_sources, _source_within_limit
from .clamp_return_local import _field
from .compiler_phase_repairs import fresh
from .integer_repair_support import IDENT, NUMBER, edit, integer
from .operand_lifetime_repairs import _typed_locals, _visible
from .trig_axis_reuse import _SAVED

FAMILY = 'balanced_sign_field_clamp'
_AXIS = re.compile(rf'lwc1 ({_SAVED}), ({NUMBER})\(\$\w+\)')
_POINTER = re.compile(rf'lw (\$\w+), ({NUMBER})\(\$\w+\)')
_SIGN = re.compile(rf'lwc1 \$f4, ({NUMBER})\((\$\w+)\)')
_GLOBAL = re.compile(rf'lui \$at, %hi\(({IDENT})\)')
_POINTER_SOURCE = re.compile(rf'\*\(\(void\*\*\)\(\(\(char\*\)({IDENT})\)\+({NUMBER})\)\)')
_SOURCE = re.compile(
    rf'(?m)^[ \t]*(?P<pointer>{IDENT})\s*=\s*(?P<address>\*[^;={{}}\n]+)\s*;\s*'
    rf'\{{\s*f32\s+(?P<previous>{IDENT})\s*=\s*(?P<axis>{IDENT})\s*;\s*'
    rf'(?P=axis)\s*=\s*(?P<axis_read>\*[^;={{}}\n]+)\s*;\s*'
    rf'(?P<global>{IDENT})\s*-=\s*(?P=axis)\s*;\s*(?P=axis)\s*=\s*(?P=previous)\s*;\s*\}}\s*'
    rf'if\s*\(\s*(?P<sign>\(\s*(?P<field>\*[^;{{}}\n]+)\s*\))\s*<=\s*0\.0[fF]\s*\)'
)


def _sign_sites(rows, target):
    for index in range(len(target) - 12):
        window = [op for _, op in target[index:index + 13]]
        axis, pointer = _AXIS.fullmatch(window[0]), _POINTER.fullmatch(window[1])
        symbol, sign = _GLOBAL.fullmatch(window[2]), _SIGN.fullmatch(window[4])
        if not (axis and pointer and symbol and sign and pointer[1] == sign[2]):
            continue
        load = f'lwc1 $f0, %lo({symbol[1]})($at)'
        store = f'swc1 $f0, %lo({symbol[1]})($at)'
        subtract = f'sub.s $f0, $f0, {axis[1]}'
        if (window[3] != load or window[5:11] != [subtract, 'mtc1 $zero, $f2', 'nop', 'c.le.s $f4, $f2',
                                                  window[2], store]
                or not window[11].startswith('bc1f ') or window[12] != 'nop'):
            continue
        first, final = target[index][0], target[index + 12][0]
        candidate = [right for _, _, right in rows[first:final + 1] if right]
        expected = [window[0], window[2], load, subtract, window[1], window[2], store,
                    f'lwc1 $f2, {sign[1]}({sign[2]})', 'mtc1 $zero, $f0', 'nop', 'c.le.s $f2, $f0', 'nop']
        if len(candidate) == 14 and candidate[:12] == expected and candidate[12].startswith('bc1f ') and candidate[13] == 'nop':
            yield index, symbol[1], integer(pointer[2]), integer(sign[1]), integer(axis[2])


def variants(source, name, rows, *, header='', max_bytes=None):
    target = [(i, left) for i, (_, left, _) in enumerate(rows) if left]
    signs = list(_sign_sites(rows, target))
    clamps = _clamp_sites(rows, target)
    pairs = [(sign, clamp) for sign in signs for clamp in clamps if 0 < clamp[0] - sign[0] <= 160]
    visible = _visible(source, name, header) if len(pairs) == 1 else None
    if not visible:
        return []
    part, context = visible
    (_, symbol, pointer_offset, sign_offset, axis_offset), (_, clamp_offset, bits) = pairs[0]
    typedefs = re.findall(r'\btypedef\s+([^;{}]+?)\s+f32\s*;', context)
    if (sign_offset <= 0 or sign_offset > 4096 or sign_offset % 4
            or not re.search(rf'\bextern\s+f32\s+{symbol}\s*;', context)
            or any(alias.strip() != 'float' for alias in typedefs)):
        return []
    floats = _typed_locals(part, r'(?:float|f32)')
    macros = set(re.findall(rf'(?m)^[ \t]*#\s*(?:define|undef)\s+({IDENT})', context))
    if {'f32', 'char'} & macros:
        return []
    clamp_candidates = list(_clamp_sources(part, floats, macros, {(clamp_offset, bits)}))
    if len(clamp_candidates) != 1:
        return []
    clamp = clamp_candidates[0]
    prefix = part.clean[:part.opening]
    matches = []
    for hit in _SOURCE.finditer(part.clean, part.opening + 1, clamp.start()):
        if (hit['global'] != symbol or hit['axis'] not in floats
                or macros & set(re.findall(IDENT, hit[0]))):
            continue
        address = _POINTER_SOURCE.fullmatch(re.sub(r'\s+', '', hit['address']))
        axis = _field(hit['axis_read'], prefix)
        sign = _field(hit['field'], prefix)
        if (address and integer(address[2]) == pointer_offset and axis and axis[1] == axis_offset
                and sign == (hit['pointer'], sign_offset)):
            matches.append(hit)
    if len(matches) != 1:
        return []
    hit = matches[0]
    layout = fresh(source, header, 'RepairSignRecord')
    member = fresh(source, header, 'repair_sign_sample')
    padding = fresh(source, header, 'repair_sign_padding')
    result = edit(source, [
        (part.opening + 1, part.opening + 1,
         f'\n    typedef struct {{ unsigned char {padding}[{sign_offset:#x}]; f32 {member}; }} {layout};'),
        (*hit.span('sign'), f'(({layout} *) {hit["pointer"]})->{member}'),
        (clamp.start('pad'), clamp.end(), _clamp_edit(clamp)),
    ])
    checked = _source_within_limit(result, max_bytes)
    return [(FAMILY, checked)] if checked is not None else []
