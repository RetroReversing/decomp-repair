"""Recover short KMC function forms whose complete target instructions prove the repair."""

import re

from . import leaf_frame_repairs, varargs_signature_repairs
from .integer_repair_support import IDENT, NUMBER, edit, integer, view
from .measured_stack_drafts import _lines

SQUARE_ROOT = re.compile(r'jr \$ra\nsqrt\.s \$(?:f0|fv0), \$(?:f12|fa0)')
HALFWORD_STORE = re.compile(
    rf'ori \$v0, \$zero, (?P<value>{NUMBER})\nlui \$at, %hi\((?P<address>'
    rf'(?P<symbol>{IDENT})(?: \+ (?P<offset>{NUMBER}))?)\)\n'
    r'jr \$ra\nsh \$v0, %lo\((?P=address)\)\(\$at\)'
)
BIT_RETURN = re.compile(
    rf'lui \$v0, %hi\((?P<address>(?P<symbol>{IDENT})(?: \+ (?P<offset>{NUMBER}))?)\)\n'
    rf'lw \$v0, %lo\((?P=address)\)\(\$v0\)\nandi \$v0, \$v0, (?P<mask>{NUMBER})\n'
    r'jr \$ra\nsltu \$v0, \$zero, \$v0'
)
FRAMED_RETURN = re.compile(
    rf'addiu \$sp, \$sp, -(?P<size>{NUMBER})\naddiu \$v0, \$zero, (?P<value>-?{NUMBER})\n'
    r'jr \$ra\naddiu \$sp, \$sp, (?P=size)'
)
VARARGS_SPILL = re.compile(
    r'sw \$a0, (?:0x0|0)?\(\$sp\)\nsw \$a1, (?:0x4|4)\(\$sp\)\n'
    r'sw \$a2, (?:0x8|8)\(\$sp\)\njr \$ra\nsw \$a3, (?:0x[cC]|12)\(\$sp\)'
)
PATTERNS = (SQUARE_ROOT, HALFWORD_STORE, BIT_RETURN, FRAMED_RETURN, VARARGS_SPILL)


def _target(asm):
    if not asm or len(asm) > 900 or asm.count('\n') > 12:
        return None
    text = '\n'.join(' '.join(line.split()) for line in _lines(asm)
                     if not line.startswith(('glabel ', 'endlabel ')))
    return next((target for pattern in PATTERNS if (target := pattern.fullmatch(text))), None)


def applies(asm):
    return _target(asm) is not None


def variants(source, name, asm, header=''):
    target = _target(asm)
    if not target or not (part := view(source, name)):
        return []
    key = target.re
    start = part.opening + 1
    end = part.clean.rfind('}', start, part.end)
    body = part.clean[start:end]
    if key is VARARGS_SPILL:
        fixed = varargs_signature_repairs.empty_home_leaf(source, name)
        return [(varargs_signature_repairs.FAMILY, fixed)] if fixed else []
    if key is FRAMED_RETURN:
        result = re.fullmatch(rf'\s*return\s+(-?{NUMBER})\s*;\s*', body)
        if (not result or result[1].startswith('-') != target['value'].startswith('-')
                or integer(result[1].lstrip('-')) != integer(target['value'].lstrip('-'))
                or '__repair_frame' in header):
            return []
        size = integer(target['size'])
        if not 8 <= size <= 0x7ff8 or size % 8:
            return []
        return [(family, fixed) for family, fixed in leaf_frame_repairs.variants(source, name, asm)
                if family == leaf_frame_repairs.FRAME]
    if key is SQUARE_ROOT:
        signature = re.search(
            rf'\b(?:f32|float)\s+{re.escape(name)}\s*\(\s*(?:f32|float)\s+({IDENT})\s*\)\s*$',
            part.clean[:part.opening])
        if not signature or '__builtin_sqrtf' in source + header:
            return []
        result = re.fullmatch(rf'\s*return\s+(?P<callee>{re.escape(name)}|sqrtf)\({signature[1]}\);\s*', body)
        if not result:
            return []
        a, b = result.span('callee')
        return [('measured_sqrt_leaf', edit(source, [(start+a, start+b, '__builtin_sqrtf')]))]

    symbol = target['symbol']
    offset = integer(target['offset'] or '0')
    if re.search(rf'\bvolatile\b[^;{{}}\n]*\b{symbol}\b', header + source[:part.opening]):
        return []
    if key is HALFWORD_STORE:
        pattern = rf'\s*M2C_FIELD\(&{symbol}, (?P<type>s16) \*, (?P<offset>{NUMBER})\) = (?P<value>{NUMBER});\s*'
        value = integer(target['value'])
        result = re.fullmatch(pattern, body)
        if not result or not 32768 <= value <= 65535 or integer(result['value']) != value:
            return []
        if integer(result['offset']) != offset:
            return []
        a, b = result.span('type')
        return [('measured_unsigned_halfword_store', edit(source, [(start+a, start+b, 'u16')]))]

    result = re.fullmatch(
        rf'(?P<space>\s*)return (?P<condition>\(M2C_FIELD\(&{symbol}, (?:s32|u32) \*, (?P<offset>{NUMBER})\)'
        rf' & (?P<mask>{NUMBER})\) != 0);(?P<tail>\s*)', body)
    if not result or integer(result['offset']) != offset or integer(result['mask']) != integer(target['mask']):
        return []
    pad = result['space'].rsplit('\n', 1)[-1]
    replacement = result['space'] + f'if ({result["condition"]}) return 1;\n{pad}return 0;' + result['tail']
    return [('measured_mask_boolean_return', edit(source, [(start, end, replacement)]))]
