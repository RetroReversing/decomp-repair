"""A literal factor that was just stored into a member, read back from the member.

    self->scale = self->scaleY = 0x6000;
    size = sizes[self->type] * 0x6000;        ->      size = sizes[self->type] * self->scale;

cse forwards the stored value to the read, so the program loads the constant into a register and multiplies (`li; mult;
mflo`), where the literal factor is expanded as shifts and adds. m2c folds the read to the literal and writes the second
form. An 88-instruction N64 entity placer (SN GCC 2.8.1, `-G0 -mips3 -O2 -mfp64`, 2255 -> 700) had the `mult`; no family
offered the read-back (`stored_field_readback_index` reads back array indices only).

stored_constant_operand
    One child per literal `*`, `/` or `%` operand and per stored lvalue holding that value, at most `LIMIT`. The store is
    an earlier statement of the same straight-line run, nothing between it and the use calls a function or assigns the
    lvalue or its base again, and the value fits the member's or cell's width.
"""
import re

from .field_offsets import Types, _declarations
from .integer_repair_support import IDENT, view
from .statement_slide import CALL, WIDTH, _runs

FAMILY = 'stored_constant_operand'
FAMILIES = (FAMILY,)
LIMIT = 24
NUMBER = r'0[xX][0-9a-fA-F]+|[1-9]\d*'
_CELL = re.compile(rf'M2C_FIELD\(\s*(?P<base>{IDENT})\s*,\s*(?P<type>\w+)\s*\*\s*,\s*(?:{NUMBER}|0)\s*\)')
_CAST = re.compile(rf'\*\s*\(\s*(?P<type>\w+)\s*\*\s*\)\s*\(\s*\(\s*(?:s8|u8|char)\s*\*\s*\)\s*(?P<base>{IDENT})\s*\+\s*(?:{NUMBER})\s*\)')
_MEMBER = re.compile(rf'(?P<base>{IDENT})\s*(?:->|\.)\s*(?P<member>{IDENT})')
_FIELD_NAME = re.compile(r'\bM2C_FIELD\s*\(')
_VALUE = re.compile(rf'\s*(?P<value>{NUMBER})[uU]?\s*;?\s*')
# the literal on either side of the operator; `/` and `%` take it on the right only
_USE = re.compile(rf'(?:(?<=[\w\])]\s\*\s)|(?<=[\w\])]\*)|(?<=[\w\])]\s[/%]\s))(?P<right>{NUMBER})(?![\w.])'
                  rf'|(?<![\w.])(?P<left>{NUMBER})(?=\s*\*\s*[A-Za-z_(])')


def _targets(text):
    """(targets, value) of `a = b = K;`, or None."""
    pieces = [piece.strip() for piece in re.split(r'(?<![=!<>+\-*/&|^%])=(?!=)', text)]
    value = len(pieces) > 1 and _VALUE.fullmatch(pieces[-1])
    return (pieces[:-1], int(value['value'], 0)) if value else None


def _holds(target, value, types, pointers):
    """The base of the lvalue `target` when it can be read back as `value`."""
    cell = _CELL.fullmatch(target) or _CAST.fullmatch(target)
    if cell:
        kind = types.resolve(cell['type'])
        width = WIDTH.get(cell['type']) or WIDTH.get(kind)
        signed = not kind.startswith(('u', 'unsigned'))
    else:
        found = _MEMBER.fullmatch(target)
        record = found and pointers.get(found['base'])
        member = record and next((m for m in record.members if m.name == found['member']), None)
        if not member or member.dims or member.stars:
            return None
        cell, width = found, member.size
        signed = not types.resolve(member.ctype).startswith(('u', 'unsigned'))
    if width not in (1, 2, 4) or value >= 1 << (8 * width - signed):
        return None
    return cell['base']


def variants(source, name, header=''):
    part = view(source, name)
    if not part:
        return []
    types = Types(source, header)
    pointers = {var: record for var, (record, _, array) in
                _declarations((header or '') + '\n' + source, types).items() if not array}
    found = []
    for run in _runs(part.clean, part.opening + 1, part.clean.rindex('}', part.opening, part.end), minimum=2):
        texts = [part.clean[s:e] for s, e in run]
        for index, text in enumerate(texts):
            stored = _targets(text.rstrip(';'))
            if not stored or stored[1] < 2:
                continue
            for target in stored[0]:
                base = _holds(target, stored[1], types, pointers)
                if base is None:
                    continue
                for later in range(index + 1, len(texts)):
                    if CALL.search(_FIELD_NAME.sub('(', texts[later])):
                        break  # a call may change the member
                    start = run[later][0]
                    for use in _USE.finditer(texts[later]):
                        if int(use['right'] or use['left'], 0) == stored[1]:
                            child = source[:start + use.start()] + target + source[start + use.end():]
                            if child not in found:
                                found.append(child)
                    written = re.split(r'(?<![=!<>])=(?!=)', texts[later])[:-1]
                    if (any(target in piece for piece in written)
                            or re.search(rf'(?<![\w.>]){base}\s*(?:=(?!=)|\+\+|--|[-+]=)', texts[later])):
                        break
    return [(FAMILY, child) for child in found[:LIMIT]]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'header')}
