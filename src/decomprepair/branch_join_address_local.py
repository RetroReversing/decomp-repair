"""A stack buffer's address that the target holds in a saved register across a branch: a pointer set before the `if`.

    u8 colour[3] = ...;
    p = colour;
    if (n < 20) sprintf(buf, "%d left", 20 - n); else sprintf(buf, "none left");
    draw(buf, x, y, scale, p, 0, 0);

The target then computes `addiu $s0, $sp, 0xA0` before the branch (in its delay slot) and the call after the join
stores `$s0`. Written as `&sp...` at the call, GCC computes the address into a temporary there and saves no register,
so the frame is also eight bytes off. Here each call that follows an `if` containing calls, and passes the address of
a stack slot the target keeps in a saved register, gets one pointer local set just before that `if`.

An SN-N64 GCC 2.8.1 (`-O2`) HUD routine of 84 instructions went from 1081 to 60 with it, and `float_argument_prototype`
then reached 0. That the original named such a pointer is a hypothesis: the bytes only show the address was computed
before the branch.

branch_join_address_local
    One child per such call and address.
"""
import re

from .integer_repair_support import edit, view
from .pattern_repairs import close

FAMILY = 'branch_join_address_local'
FAMILIES = (FAMILY,)
LOCAL = '__repair_held_address'
LIMIT = 4

_HELD = re.compile(r'\baddiu\s+\$(?:s[0-7]|fp)\s*,\s*\$sp\s*,\s*(0x[0-9A-Fa-f]+|\d+)')
_CALL = re.compile(r'(?m)^(?P<indent>[ \t]*)(?:[A-Za-z_]\w*[ \t]*=[ \t]*)?(?!(?:if|while|for|switch|return|sizeof)\b)'
                   r'[A-Za-z_]\w*[ \t]*\([^;{}\n]*\)[ \t]*;')
_ADDRESS = re.compile(r'(?<=[(,])(?P<space>[ \t]*)&[ \t]*sp(?P<slot>[0-9A-F]+)\b(?=[ \t]*[,)])')


def _opening(clean, closing, pair):
    """The index of the bracket that `clean[closing]` closes, or -1."""
    depth = 0
    for at in range(closing, -1, -1):
        if clean[at] == pair[1]:
            depth += 1
        elif clean[at] == pair[0]:
            depth -= 1
            if not depth:
                return at
    return -1


def _if_before(clean, at):
    """The start of the `if` (with its `else`, if any) that ends right before `at`, when it holds a call; else None."""
    end = len(clean[:at].rstrip())
    last = end - 1
    for _ in range(8):  # an `else if` ladder walks back one arm at a time
        if last < 0 or clean[last] != '}':
            return None
        brace = _opening(clean, last, '{}')
        head = clean[:brace].rstrip() if brace >= 0 else ''
        if head.endswith('else'):
            last = len(head[:-4].rstrip()) - 1
            continue
        if not head.endswith(')'):
            return None
        paren = _opening(clean, len(head) - 1, '()')
        found = re.search(r'\bif[ \t]*$', clean[:paren]) if paren >= 0 else None
        if not found:
            return None
        before = clean[:found.start()].rstrip()
        if before.endswith('else'):
            last = len(before[:-4].rstrip()) - 1
            continue
        inside = clean[paren:end]
        calls = [m for m in re.finditer(r'\b([A-Za-z_]\w*)[ \t]*\(', inside[1:])
                 if m[1] not in ('if', 'while', 'for', 'switch', 'sizeof')]
        return found.start() if calls and close(clean, brace, '{', '}') else None
    return None


def variants(source, name, asm=''):
    held = {int(found, 0) for found in _HELD.findall(asm or '')}
    part = view(source, name) if held else None
    if not part or LOCAL in part.clean:
        return []
    clean, opening, end = part.clean, part.opening, part.end
    out = []
    for call in _CALL.finditer(clean, opening, end):
        for address in _ADDRESS.finditer(clean, call.start(), call.end()):
            if int(address['slot'], 16) not in held:
                continue
            start = _if_before(clean, call.start())
            if start is None or start <= opening:
                continue
            line = clean.rfind('\n', 0, start) + 1
            indent = clean[line:start]
            if indent.strip():
                continue
            text = edit(source, [
                (opening + 1, opening + 1, f'\n    void *{LOCAL};'),
                (start, start, f'{LOCAL} = &sp{address["slot"]};\n{indent}'),
                (address.start(), address.end(), f'{address["space"]}{LOCAL}'),
            ])
            out.append((FAMILY, text))
    return out[:LIMIT]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'asm'), 'order': 100,
          'archs': ('mips',)}
