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
INDEXED_STACK_HALFWORD = re.compile(
    rf'lw \$v0, (?P<base>{NUMBER})\(\$a0\)\nandi \$a1, \$a1, (?:0x[fF]{{4}}|65535)\n'
    rf'sll \$a1, \$a1, (?P<shift>{NUMBER})\naddu \$v0, \$a1, \$v0\n'
    r'sh \$a2, (?:0x0|0)?\(\$v0\)\nlw \$v0, (?P=base)\(\$a0\)\naddu \$v0, \$a1, \$v0\n'
    r'sh \$a3, (?:0x2|2)\(\$v0\)\nlw \$v0, (?P=base)\(\$a0\)\n'
    r'lhu \$v1, (?:0x12|18)\(\$sp\)\naddu \$a1, \$a1, \$v0\njr \$ra\nsh \$v1, (?:0x4|4)\(\$a1\)'
)
PATTERNS = (SQUARE_ROOT, HALFWORD_STORE, BIT_RETURN, FRAMED_RETURN, VARARGS_SPILL, INDEXED_STACK_HALFWORD)


def _target(asm):
    if not asm or len(asm) > 1500 or asm.count('\n') > 15:
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
    if key is INDEXED_STACK_HALFWORD:
        fixed = _indexed_stack_halfword(part, name, header, target, body)
        return [('indexed_stack_halfword', fixed)] if fixed else []
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


def _indexed_stack_halfword(part, name, header, target, body):
    """An out-of-register argument is a word, loaded as its halfword at byte two."""
    if re.search(rf'\b{re.escape(name)}\s*\(', header):
        return None
    signature = re.search(
        rf'\bvoid\s+{re.escape(name)}\(void \*(?P<obj>{IDENT}), (?P<index_type>s32) (?P<index>{IDENT}), '
        rf's16 (?P<first>{IDENT}), s16 (?P<second>{IDENT}), (?P<stack_type>u16) (?P<stack>{IDENT})\)\s*$',
        part.clean[:part.opening])
    if not signature:
        return None
    obj, index, first, second, stack = (signature[key] for key in ('obj', 'index', 'first', 'second', 'stack'))
    field = rf'M2C_FIELD\({obj}, s32 \*, (?P<base>{NUMBER})\)'
    draft = re.fullmatch(
        rf'\s*s32 (?P<local>{IDENT});\s*(?P=local) = (?P<scale_expr>\({index} & (?P<mask>{NUMBER})\) '
        rf'\* (?P<stride>{NUMBER}));\s*\*(?P<cast>\(s16 \*\))?\((?P=local) \+ {field}\) = {first};\s*'
        rf'M2C_FIELD\(\(\s*(?P=local) \+ M2C_FIELD\({obj}, s32 \*, (?P=base)\)\), s16 \*, (?P<two>{NUMBER})\)'
        rf' = {second};\s*M2C_FIELD\(\(\s*(?P=local) \+ M2C_FIELD\({obj}, s32 \*, (?P=base)\)\), '
        rf'u16 \*, (?P<four>{NUMBER})\) = (?P<value>{stack});\s*',
        body)
    shift = integer(target['shift'])
    if (not draft or not 1 <= shift <= 8 or integer(draft['stride']) != 1 << shift
            or integer(draft['base']) != integer(target['base']) or integer(draft['mask']) != 65535
            or integer(draft['two']) != 2 or integer(draft['four']) != 4):
        return None
    start = part.opening + 1
    fixes = [(*signature.span('index_type'), 'u16'), (*signature.span('stack_type'), 's32'),
             (start + draft.start('scale_expr'), start + draft.end('scale_expr'), f'{index} << {shift}'),
             (start + draft.start('value'), start + draft.end('value'), f'((u16 *)&{stack})[1]')]
    if not draft['cast']:
        first_deref = body.index('*(', draft.end('scale_expr'))
        fixes.append((start + first_deref + 1, start + first_deref + 1, '(s16 *)'))
    return edit(part.source, fixes)
