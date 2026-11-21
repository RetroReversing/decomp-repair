"""Give KMC cartridge status polls and their following accesses volatile types."""

import re

from .integer_repair_support import IDENT, NUMBER, edit, integer, view
from .measured_stack_drafts import _lines
from .pattern_repairs import close
from .stack_read_retry import _decimal

FAMILY = 'kmc_cartridge_io'
_LABEL = r'\.L\w+'
_IO = 0xA4600000

# The initial and loop-carried volatile loads use separate register carriers.
_FIRST = (
    r'lui \$v0, \((?P<status>\d+) >> 16\)\nori \$v0, \$v0, \((?P=status) & 65535\)\n'
)
_LOOP = (
    r'andi \$v0, \$v0, (?P<busy>\d+)\n'
    rf'beqz \$v0, (?P<ready>{_LABEL})\n'
)
_REREAD = (
    r'ori \$v1, \$v1, \((?P=status) & 65535\)\n'
    rf'(?P<poll>{_LABEL}):\nlw \$v0, 0\(\$v1\)\n'
    r'andi \$v0, \$v0, (?P=busy)\nbnez \$v0, (?P=poll)\nnop\n(?P=ready):\n'
)
_UPPER = r'lui \$v1, \((?P=status) >> 16\)\n'
_READ = re.compile(
    r'addiu \$sp, \$sp, -32\nsw \$s1, 20\(\$sp\)\naddu \$s1, \$a0, \$zero\n'
    r'sw \$s0, 16\(\$sp\)\naddu \$s0, \$a1, \$zero\n'
    rf'bnez \$s0, (?P<checked>{_LABEL})\nsw \$ra, 24\(\$sp\)\n'
    rf'lui \$a0, %hi\((?P<file>{IDENT})\)\naddiu \$a0, \$a0, %lo\((?P=file)\)\n'
    rf'lui \$a1, %hi\((?P<message>{IDENT})\)\naddiu \$a1, \$a1, %lo\((?P=message)\)\n'
    rf'jal (?P<call>{IDENT})\naddiu \$a2, \$zero, (?P<line>\d+)\n(?P=checked):\n'
    + _FIRST + r'lw \$v0, 0\(\$v0\)\n' + _LOOP + _UPPER + _REREAD
    + rf'lui \$v0, %hi\((?P<base>{IDENT})\)\nlw \$v0, %lo\((?P=base)\)\(\$v0\)\n'
    rf'lui \$v1, %hi\((?P<segment>{IDENT})\)\nor \$v0, \$v0, \$s1\nor \$v0, \$v0, \$v1\n'
    r'lw \$v0, %lo\((?P=segment)\)\(\$v0\)\nsw \$v0, 0\(\$s0\)\naddu \$v0, \$zero, \$zero\n'
    r'lw \$ra, 24\(\$sp\)\nlw \$s1, 20\(\$sp\)\nlw \$s0, 16\(\$sp\)\njr \$ra\naddiu \$sp, \$sp, 32'
)
_DMA = re.compile(
    r'addiu \$sp, \$sp, -32\nsw \$s0, 16\(\$sp\)\naddu \$s0, \$a0, \$zero\n'
    r'sw \$s1, 20\(\$sp\)\naddu \$s1, \$a1, \$zero\n'
    + _FIRST + r'sw \$ra, 28\(\$sp\)\nsw \$s2, 24\(\$sp\)\nlw \$v0, 0\(\$v0\)\naddu \$a0, \$a2, \$zero\n'
    + _LOOP + r'addu \$s2, \$a3, \$zero\n' + _UPPER + _REREAD
    + rf'jal (?P<call>{IDENT})\nnop\n'
    r'lui \$a2, \((?P<offset>\d+) >> 16\)\nori \$a2, \$a2, \((?P=offset) & 65535\)\n'
    r'lui \$a1, \((?P<mask>\d+) >> 16\)\n'
    rf'lui \$v1, %hi\((?P<base>{IDENT})\)\nlw \$v1, %lo\((?P=base)\)\(\$v1\)\n'
    r'ori \$a1, \$a1, \((?P=mask) & 65535\)\n'
    rf'lui \$a0, %hi\((?P<dest>{IDENT})\)\nsw \$v0, %lo\((?P=dest)\)\(\$a0\)\n'
    r'or \$v1, \$v1, \$s1\nand \$v1, \$v1, \$a1\nsw \$v1, 0\(\$a2\)\n'
    rf'beqz \$s0, (?P<write_case>{_LABEL})\naddiu \$v0, \$zero, 1\n'
    rf'beq \$s0, \$v0, (?P<read_case>{_LABEL})\nlui \$v1, \((?P<read>\d+) >> 16\)\n'
    rf'j (?P<exit>{_LABEL})\naddiu \$v0, \$zero, -1\n(?P=write_case):\n'
    rf'lui \$v1, \((?P<write>\d+) >> 16\)\nj (?P<commit>{_LABEL})\nori \$v1, \$v1, \((?P=write) & 65535\)\n'
    r'(?P=read_case):\nori \$v1, \$v1, \((?P=read) & 65535\)\n(?P=commit):\n'
    r'addiu \$v0, \$s2, -1\nsw \$v0, 0\(\$v1\)\naddu \$v0, \$zero, \$zero\n'
    r'(?P=exit):\nlw \$ra, 28\(\$sp\)\nlw \$s2, 24\(\$sp\)\nlw \$s1, 20\(\$sp\)\n'
    r'lw \$s0, 16\(\$sp\)\njr \$ra\naddiu \$sp, \$sp, 32'
)
_POLL_SOURCE = (
    rf'if \(\*\(s32 \*\)(?P<status>{NUMBER}) & (?P<busy>{NUMBER})\) \{{ do \{{\s*\}} while '
    r'\(\*\(void \*\)(?P=status) & (?P=busy)\); \} '
)


def _target(asm):
    if not asm or 'andi' not in asm or 'jal' not in asm or '0XA460' not in asm.upper():
        return None
    text = '\n'.join(' '.join(line.split()) for line in _lines(asm) if not line.startswith(('glabel ', 'endlabel ')))
    text = _decimal(text)
    for pattern in (_READ, _DMA):
        match = pattern.fullmatch(text)
        if match and int(match['status']) == _IO + 16 and int(match['busy']) in range(1, 65536):
            labels = [value for value in match.groupdict().values() if value.startswith('.L')]
            if len(set(labels)) == len(labels):
                return pattern, match
    return None


def applies(asm):
    return _target(asm) is not None


def rewrite(source, name, asm, header='', resolve=None):
    if not source or not resolve or '*(void *)' not in source or '_m2c_cart_' in source + header:
        return None
    target = _target(asm)
    part = view(source, name) if target else None
    closing = close(part.clean, part.opening, '{', '}') if part else None
    if not closing:
        return None
    pattern, witness = target
    head = part.clean[:part.opening]
    body = ' '.join(part.clean[part.opening + 1:closing - 1].split())
    replacement = (_read_body(name, head, body, witness, resolve) if pattern is _READ
                   else _dma_body(name, head, body, witness, resolve))
    if not replacement:
        return None
    return edit(source, [(part.opening + 1, closing - 1, replacement)])


def _poll(target):
    return f'while (*(volatile u32 *)0x{int(target["status"]):08X}U & {target["busy"]}U) {{}}'


def _read_body(name, head, body, target, resolve):
    sig = re.search(rf'\bs32\s+{re.escape(name)}\(s32 (?P<addr>{IDENT}), s32 \*(?P<out>{IDENT})\)\s*$', head)
    if not sig or resolve(target['segment']) != 0xA0000000:
        return None
    addr, out = sig.groups()
    call, file, message, base, seg = (target[key] for key in ('call', 'file', 'message', 'base', 'segment'))
    draft = re.fullmatch(
        rf'if \({out} == NULL\) \{{ {call}\(&{file}, &{message}, (?P<line>{NUMBER})\); \}} '
        + _POLL_SOURCE + rf'\*{out} = \*\({base} \| {addr} \| \(s32\) &{seg}\); return 0;',
        body)
    if not draft or any(integer(draft[key]) != int(target[key]) for key in ('status', 'busy', 'line')):
        return None
    return f'''
    s32 *_m2c_cart_dest;
    s32 _m2c_cart_offset;

    _m2c_cart_offset = {addr};
    _m2c_cart_dest = {out};
    if (_m2c_cart_dest == NULL) {{
        {call}(&{file}, &{message}, {draft['line']});
    }}
    {_poll(target)}
    *_m2c_cart_dest = *(s32 *)(({base} | _m2c_cart_offset) | 0xA0000000U);
    do {{ }} while (0);
    return 0;
'''


def _dma_body(name, head, body, target, resolve):
    sig = re.search(
        rf'\bs32\s+{re.escape(name)}\(s32 (?P<dir>{IDENT}), s32 (?P<offset>{IDENT}), '
        rf'(?:M2C_UNK|void \*)\s*(?P<addr>{IDENT}), s32 (?P<length>{IDENT})\)\s*$', head)
    if (not sig or resolve(target['dest']) != _IO or tuple(int(target[key]) for key in ('offset', 'read', 'write'))
            != (_IO + 4, _IO + 8, _IO + 12)):
        return None
    call, base, dest = (target[key] for key in ('call', 'base', 'dest'))
    direction, offset, addr, length = sig.groups()
    draft = re.fullmatch(
        rf's32 \*(?P<reg>{IDENT}); ' + _POLL_SOURCE
        + rf'{dest} = {call}\({addr}\); \*\(s32 \*\)(?P<offset>{NUMBER}) = \({base} \| {offset}\) & (?P<mask>{NUMBER}); '
        rf'switch \({direction}\) \{{ case 0: (?P=reg) = \(s32 \*\)(?P<write>{NUMBER}); (?P<join>{IDENT}): '
        rf'\*(?P=reg) = {length} - 1; return 0; case 1: (?P=reg) = \(s32 \*\)(?P<read>{NUMBER}); '
        r'goto (?P=join); default: return -1; \}', body)
    if not draft or any(integer(draft[key]) != int(target[key]) for key in ('status', 'busy', 'offset', 'mask', 'read', 'write')):
        return None
    return f'''
    volatile u32 *_m2c_cart_length;

    {_poll(target)}
    *(volatile u32 *)0x{_IO:08X}U = {call}({addr});
    *(volatile u32 *){draft['offset']} = ({base} | {offset}) & {draft['mask']};
    switch ({direction}) {{
    case 0:
        _m2c_cart_length = (volatile u32 *){draft['write']};
        break;
    case 1:
        _m2c_cart_length = (volatile u32 *){draft['read']};
        break;
    default:
        return -1;
    }}
    *_m2c_cart_length = {length} - 1;
    return 0;
'''
