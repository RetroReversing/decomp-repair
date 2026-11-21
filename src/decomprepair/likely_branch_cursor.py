"""Recover a KMC list loop whose branch-likely and call advance the same cursor."""

import re

from .integer_repair_support import IDENT, edit, view
from .mips import abi_register_names
from .pattern_repairs import close

ROW = r'^[ \t]*(?:/\*[^\n]*?\*/[ \t]*)?'
SAVED = r'\$s[0-7]'
LABEL = r'\.L\w+'
SKIP = '.Ldecomp_cursor_active'
LIKELY = re.compile(
    rf'{ROW}beql[ \t]+(?P<test>\$\w+),[ \t]*\$zero,[ \t]*(?P<join>{LABEL})[ \t]*\n'
    rf'(?P<slot>{ROW}addu[ \t]+(?P<cursor>{SAVED}),[ \t]*(?P<next>{SAVED}),[ \t]*\$zero)[ \t]*\n',
    re.M,
)

DRAFT = re.compile(
    rf'(?m)^(?P<indent>[ \t]+)(?P<next>temp_s[0-7]) = '
    rf'M2C_FIELD\((?P<cursor>var_s[0-7]), void \*\*, (?:0|0x0)\);\n'
    rf'(?P=indent)if \((?P<active>{IDENT}) == 0\) {{\n'
    r'(?P=indent)[ \t]+(?P=cursor) = (?P=next);\n'
    r'(?P=indent)} else \{'
)


def _evidence(asm):
    if 'beql' not in asm or SKIP in asm:
        return None
    asm = abi_register_names(asm)
    candidates = list(LIKELY.finditer(asm))
    if len(candidates) != 1:
        return None
    branch = candidates[0]
    cursor, successor, test = (re.escape(branch[key]) for key in ('cursor', 'next', 'test'))
    if branch['cursor'] == branch['next'] or branch['test'] in ('$zero', branch['cursor'], branch['next']):
        return None
    # m2c folds matching slots by moving the join back onto the call's delay slot.
    # Require both the cursor load and the exact shared advance before splitting it.
    tail = re.search(
        rf'{ROW}jal[ \t]+(?P<release>{IDENT})[ \t]*\n'
        rf'{ROW}addu[ \t]+{cursor},[ \t]*{successor},[ \t]*\$zero[ \t]*\n'
        rf'^{re.escape(branch["join"])}:[ \t]*\n'
        rf'{ROW}bnez[ \t]+{cursor},[ \t]*(?P<loop>{LABEL})[ \t]*\n'
        rf'{ROW}nop[ \t]*$', asm, re.M)
    if tail is None or branch.end() >= tail.start():
        return None
    load = re.search(rf'{ROW}lw[ \t]+{successor},[ \t]*(?:0|0x0)?\({cursor}\)[ \t]*\n\Z',
                     asm[:branch.start()], re.M)
    if load is None or not re.search(rf'(?m)^{re.escape(tail["loop"])}:[ \t]*\n', asm[:load.start()]):
        return None
    return asm, branch, tail['release']


def applies(asm):
    return _evidence(asm) is not None


def draft_asm(asm):
    """Expand the likely branch for m2c while preserving its taken-only move."""
    if not (evidence := _evidence(asm)):
        return asm
    text, branch, _ = evidence
    replacement = (f'    bnez {branch["test"]}, {SKIP}\n    nop\n'
                   f'    addu {branch["cursor"]}, {branch["next"]}, $zero\n'
                   f'    b {branch["join"]}\n    nop\n{SKIP}:\n')
    return edit(text, [(*branch.span(), replacement)])


def rewrite(source, name, asm, header=''):
    """Put the shared local advance after the conditional body."""
    if 'M2C_FIELD' not in source or not (evidence := _evidence(asm)):
        return None
    _, branch, release = evidence
    part = view(source, name)
    if not part or re.search(r'\b(?:asm|__asm__|goto)\b', part.body):
        return None
    hits = list(DRAFT.finditer(part.clean, part.opening + 1, part.end - 1))
    if len(hits) != 1:
        return None
    head = hits[0]
    if head['cursor'] != 'var_' + branch['cursor'][1:] or head['next'] != 'temp_' + branch['next'][1:]:
        return None
    cursor, successor, indent = (head[key] for key in ('cursor', 'next', 'indent'))
    if re.search(rf'&[ \t\n]*(?:\([ \t\n]*)*\b{cursor}\b', part.body):
        return None
    for local in (cursor, successor):
        declarations = re.findall(rf'(?m)^[ \t]*{IDENT}[ \t*]+{local}[ \t]*(?=[;=,\[])', part.body)
        if len(declarations) != 1:
            return None
    if re.search(rf'(?m)^\s*#\s*define\s+(?:{cursor}|{successor}|{release})\b', source + '\n' + header):
        return None
    end = close(part.clean, head.end() - 1, '{', '}')
    if not end:
        return None
    tail = re.search(
        rf'(?m)^[ \t]+{cursor} = {successor};\n[ \t]+{release}\(\);\n{indent}}}\Z',
        part.clean[head.end():end])
    loop_test = rf'\n[ \t]*}} while \({cursor} != (?:NULL|0)\);'
    if not tail or not re.match(loop_test, part.clean[end:]):
        return None
    if_start = source.index('\n', head.start()) + 1
    tail_start = head.end() + tail.start()
    advance_end = source.index('\n', tail_start) + 1
    return edit(source, [
        (if_start, head.end(), f'{indent}if ({head["active"]} != 0) {{'),
        (tail_start, advance_end, ''),
        (end, end, f'\n{indent}{cursor} = {successor};'),
    ])
