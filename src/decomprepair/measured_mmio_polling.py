"""Recover a measured two-stage word polling sequence from a KMC draft."""

import re

from .integer_repair_support import IDENT, NUMBER, edit, integer, view
from .mips import abi_register_names

REG = r'\$\w+'
LABEL = r'\.L\w+'
MMIO = r'0xA[45][0-9A-Fa-f]{6}'
ZERO = r'(?:0x0|0)?'
STATUS = '__m2c_poll_status'

POLL = re.compile(
    rf'(?m)^andi (?P<test>{REG}), (?P<word>{REG}), (?P<mask>{NUMBER})\n'
    rf'beqz (?P=test), (?P<exit>{LABEL})\n'
    rf'lui (?P<base>{REG}), \((?P<addr>{MMIO}) >> 16\)\n'
    r'ori (?P=base), (?P=base), \((?P=addr) & 0xFFFF\)\n'
    rf'(?P<loop>{LABEL}):\nlw (?P=word), {ZERO}\((?P=base)\)\n'
    r'andi (?P=test), (?P=word), (?P=mask)\n'
    r'bnez (?P=test), (?P=loop)\nnop\n(?P=exit):$'
)

CAST = r'\((?:volatile )?(?:s32|u32|void) \*\)'
DRAFT = re.compile(
    rf'void \*(?P<saved>{IDENT}); (?:void \*(?P<ghost>{IDENT}); )?'
    rf'(?P=saved) = M2C_FIELD\(&(?P<base>{IDENT}), (?:s32 \*|u8 \*\*), (?P<baseoff>{NUMBER})\) '
    rf'\+ (?P<addend>{NUMBER}); '
    rf'if \(\*{CAST}(?P<status>{MMIO}) & (?P<mask>{NUMBER})\) {{ do {{ }} '
    rf'while \(\*{CAST}(?P=status) & (?P=mask)\); }} '
    rf'\*{CAST}(?P<output>{MMIO}) = M2C_FIELD\((?P=saved), s32 \*, (?P<field>{NUMBER})\) \| (?P<bit>{NUMBER}); '
    rf'(?:(?P=ghost) = \(void \*\)(?P<setup>{MMIO}); )?'
    rf'if \(\*{CAST}(?P=status) & (?P=mask)\) {{ '
    r'(?:(?P=ghost) = \(void \*\)(?P<ghost_update>(?P=status)); )?'
    rf'do {{ }} while \(\*{CAST}(?P=status) & (?P=mask)\); }} '
    rf'\*{CAST}(?P=output) = (?:\(s32\) )?M2C_FIELD\((?P=saved), s32 \*, (?P=field)\); '
    rf'(?P<callee>{IDENT})\((?P<args>(?P=ghost), (?P=output), (?P=saved))?\); '
    rf'\*{CAST}(?P=status) = (?P<ack>{NUMBER}); (?P<maskvar>{IDENT}) \|= (?P<flags>{NUMBER});'
)


def _evidence(asm):
    if 'andi' not in asm or 'bnez' not in asm or ' >> 16)' not in asm:
        return None
    lines = [' '.join(re.sub(r'/\*.*?\*/|#.*', '', row).split())
             for row in abi_register_names(asm).splitlines()]
    text = '\n'.join(filter(None, lines))
    loops = list(POLL.finditer(text))
    if len(loops) != 2 or loops[0]['addr'] != loops[1]['addr'] or loops[0]['mask'] != loops[1]['mask']:
        return None
    first = loops[0]
    addr, word = first['addr'], re.escape(first['word'])
    if not re.search(
        rf'(?m)^lui (?P<base>{REG}), \({addr} >> 16\)\n'
        rf'ori (?P=base), (?P=base), \({addr} & 0xFFFF\)\n'
        rf'sw \$ra, {NUMBER}\(\$sp\)\nlw {word}, {ZERO}\((?P=base)\)\n'
        rf'addiu \$a2, {REG}, {NUMBER}\n\Z', text[:first.start()]
    ):
        return None
    return text, loops


def applies(asm):
    return _evidence(asm) is not None


def _stores(draft, loops, asm):
    output = draft['output']
    before = asm[:loops[0].start()]
    between = asm[loops[0].end():loops[1].start()]
    last = asm[loops[1].end():]
    base_expr = rf'{draft["base"]} \+ ({NUMBER})'
    binding = re.search(rf'(?m)^lui (?P<base>{REG}), %hi\((?P<expr>{base_expr})\)\n'
                        r'lw (?P=base), %lo\((?P=expr)\)\((?P=base)\)$', before)
    if not binding or integer(binding[3]) != integer(draft['baseoff']):
        return False
    initial = re.search(rf'(?m)^addiu \$a2, {re.escape(binding["base"])}, ({NUMBER})$', before)
    if not initial or integer(initial[1]) != integer(draft['addend']):
        return False
    first = re.search(
        rf'(?m)^lui (?P<reg>{REG}), \({output} >> 16\)\n'
        rf'ori (?P=reg), (?P=reg), \({output} & 0xFFFF\)\n'
        rf'lui (?P<status>{REG}), \({draft["status"]} >> 16\)\n'
        rf'lw (?P<word>{REG}), (?P<field>{NUMBER})\(\$a2\)\n'
        rf'ori (?P=status), (?P=status), \({draft["status"]} & 0xFFFF\)\n'
        rf'lui (?P<bitreg>{REG}), \((?P<bit>{NUMBER}) >> 16\)\n'
        rf'or (?P=word), (?P=word), (?P=bitreg)\nsw (?P=word), {ZERO}\((?P=reg)\)\n'
        rf'lw {re.escape(loops[1]["word"])}, {ZERO}\((?P=status)\)\n\Z', between)
    second = re.search(
        rf'(?m)^lw (?P<word>{REG}), (?P<field>{NUMBER})\(\$a2\)\n'
        rf'lui (?P<reg>{REG}), \({output} >> 16\)\nori (?P=reg), (?P=reg), \({output} & 0xFFFF\)\n'
        rf'jal {draft["callee"]}\nsw (?P=word), {ZERO}\((?P=reg)\)$', last)
    if not first or not second or any(integer(m['field']) != integer(draft['field']) for m in (first, second)):
        return False
    if integer(first['bit']) != integer(draft['bit']):
        return False
    ack = re.search(
        rf'(?m)^lui (?P<reg>{REG}), \({draft["status"]} >> 16\)\n'
        rf'ori (?P=reg), (?P=reg), \({draft["status"]} & 0xFFFF\)\n'
        rf'(?:[^\n]*\n){{0,6}}addiu (?P<value>{REG}), \$zero, ({NUMBER})\n'
        rf'sw (?P=value), {ZERO}\((?P=reg)\)$', last[second.end():])
    return ack is not None and integer(ack[3]) == integer(draft['ack'])


def rewrite(source, name, asm, header=''):
    """Stage the status value without coalescing or adding volatile reads."""
    if '*(' not in source or STATUS in source + header or not (evidence := _evidence(asm)):
        return None
    part = view(source, name)
    if not part or not re.search(rf'\bvoid\s+{re.escape(name)}\(void\)\s*$', part.clean[:part.opening]):
        return None
    end = len(part.clean[:part.end].rstrip()) - 1
    draft = DRAFT.fullmatch(' '.join(part.clean[part.opening + 1:end].split()))
    if not draft:
        return None
    text, loops = evidence
    if (draft['output'] == draft['status'] or draft['status'] != loops[0]['addr']
            or integer(draft['mask']) != integer(loops[0]['mask']) or not _stores(draft, loops, text)):
        return None
    if any(bool(draft[key]) != bool(draft['ghost']) for key in ('args', 'setup', 'ghost_update')):
        return None
    if draft['ghost'] == draft['saved']:
        return None
    patches = []
    callee = draft['callee']
    if draft['args']:
        prototype = re.search(rf'(?m)^M2C_UNK {callee}\(void \*, M2C_UNK, void \*\);[ \t]*/\* extern \*/[ \t]*$',
                              source[:part.opening])
        if not prototype or re.search(rf'\b{callee}\b',header):
            return None
        patches.append((*prototype.span(), f'void {callee}(void);'))
    saved = draft['saved']
    status = draft['status']
    output = draft['output']
    poll = f'''    {STATUS} = *(volatile u32 *){status};
    if ({STATUS} & {draft['mask']}) {{
        do {{
            {STATUS} = *(volatile u32 *){status};
        }} while ({STATUS} & {draft['mask']});
    }}
'''
    body = f'''
    void *{saved};
    u32 {STATUS};

    {saved} = M2C_FIELD(&{draft['base']}, u8 **, {draft['baseoff']}) + {draft['addend']};
{poll}    *(volatile u32 *){output} = M2C_FIELD({saved}, s32 *, {draft['field']}) | {draft['bit']};
{poll}    *(volatile u32 *){output} = (s32) M2C_FIELD({saved}, s32 *, {draft['field']});
    {callee}();
    *(volatile u32 *){status} = {draft['ack']};
    {draft['maskvar']} |= {draft['flags']};
'''
    return edit(source, patches + [(part.opening + 1,end,body)])
