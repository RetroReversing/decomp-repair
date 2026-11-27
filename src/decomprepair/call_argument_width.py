"""A local (or a callee's parameter) narrowed to the width the target masks that call argument to.

A draft types a value `s32` and declares its callee with `s32` parameters, but the target narrows the argument on its way
into the register (`andi $a1,$s1,0xffff` before the `jal`) where the compiled draft only moves it. The original had a
narrow local (or a narrow parameter in the callee's prototype). Measured on one KMC gcc 2.7.2 (`-O1`) function that
stepped a screen position down a column of digits: both locals as `u16` took the saved source from 2000 to 1295, and from
1020 to 305 after four other repairs; the narrow prototype alone took the same state to 620.

call_argument_width_local
    Every word-typed local passed bare (or cast) at a position the target masks (`andi $aN,..,0xff|0xffff`) or
    sign-extends (`sll`/`sra $aN`) is declared at that width: all of them together, then one at a time.
call_argument_width_prototype
    The candidate's own prototype of such a callee takes those positions at that width.
call_argument_width_cast
    An argument that is an expression (`f(base + i)`), where there is no local to retype and the callee's prototype may
    be the shared header's, is cast to that width at the call: all of them together, then one at a time. On a KMC gcc
    2.7.2 (`-O2`) controller pak routine whose block address was a word sum, the missing `andi $a2,$a2,0xffff` before the
    read was the last difference (160 -> 0).

Evidence is the target's own assembly; the exact judge decides every child.
"""
import re

from .integer_repair_support import IDENT, calls, edit, locals_for, split_args, view
from .repair_preflight import _PROTO

LOCAL = 'call_argument_width_local'
PROTOTYPE = 'call_argument_width_prototype'
CAST = 'call_argument_width_cast'
FAMILIES = (LOCAL, PROTOTYPE, CAST)
LIMIT = 8
WORD = {'s32', 'u32', 'int', 'signed int', 'unsigned int'}
# a name or a number, however it is cast: nothing to wrap (a local is retyped instead)
_SIMPLE = re.compile(r'(?:\(\s*[\w ]+\)\s*)*-?\w+')
_COMMENT = re.compile(r'/\*.*?\*/')
_CALL = re.compile(r'^jal\s+(' + IDENT + r')\b')
_BRANCH = re.compile(r'^(?:j|jr|jal|jalr|b[a-z0-9]*)\s')
_LABEL = re.compile(r':$|^(?:glabel|endlabel)\b')
_MASK = re.compile(r'^andi\s+\$a([0-3])\s*,\s*\$\w+\s*,\s*(0x0*ff|0x0*ffff|255|65535)$', re.I)
_SIGNED = re.compile(r'^sra\s+\$a([0-3])\s*,\s*\$\w+\s*,\s*(16|24|0x10|0x18)$', re.I)


def witnessed(asm):
    """{callee: {argument position: type}} for the register arguments the target narrows at a call."""
    lines = [_COMMENT.sub('', line).strip() for line in (asm or '').splitlines()]
    lines = [line for line in lines if line]
    found = {}
    for at, line in enumerate(lines):
        call = _CALL.match(line)
        if not call:
            continue
        low = at
        # back to the label or branch before; a branch's delay slot belongs to that branch
        while (low > 0 and not _LABEL.search(lines[low - 1]) and not _BRANCH.match(lines[low - 1])
               and not (low > 1 and _BRANCH.match(lines[low - 2]))):
            low -= 1
        for row in lines[low:at] + lines[at + 1:at + 2]:
            mask, signed = _MASK.match(row), _SIGNED.match(row)
            if mask:
                kind = 'u8' if int(mask[2], 0) == 0xFF else 'u16'
            elif signed:
                kind = 's16' if int(signed[2], 0) == 16 else 's8'
            else:
                continue
            found.setdefault(call[1], {})[int((mask or signed)[1])] = kind
    return found


def variants(source, name, asm=''):
    part = view(source, name)
    evidence = witnessed(asm)
    if not part or not evidence or re.search(r'^\s*#', part.clean, re.M):
        return []
    declared = {d['name']: d for d in locals_for(part) if ' '.join(d['type'].split()) in WORD}
    retypes, prototypes, casts = {}, [], []
    for callee, positions in evidence.items():
        for start, end in calls(part, callee):
            args = split_args(part.clean[start:end])
            for position, kind in positions.items():
                if position >= len(args):
                    continue
                low, high = args[position]
                bare = re.fullmatch(r'\s*(?:\(\s*[\w ]+\)\s*)*(' + IDENT + r')\s*', part.clean[start + low:start + high])
                if bare and bare[1] in declared:
                    retypes.setdefault(bare[1], kind)
                text = part.clean[start + low:start + high]
                expression = text.strip()
                if expression and not _SIMPLE.fullmatch(expression) and not re.match(rf'\(\s*{kind}\s*\)', expression):
                    at = start + low + len(text) - len(text.lstrip())
                    casts.append((at, at + len(expression), f'({kind}) ({source[at:at + len(expression)]})'))
        prototype = [p for p in _PROTO.finditer(part.clean[:part.opening]) if p[1] == callee]
        if len(prototype) != 1:
            continue
        params = split_args(prototype[0][2])
        for position, kind in positions.items():
            if position >= len(params):
                continue
            low, high = params[position]
            typed = re.match(r'\s*(unsigned\s+int|signed\s+int|[su]32|int)\b(?!\s*\*)', prototype[0][2][low:high])
            if typed:
                offset = prototype[0].start(2) + low
                prototypes.append((offset + typed.start(1), offset + typed.end(1), kind))
    changes = [(declared[n].start('type'), declared[n].end('type'), kind) for n, kind in retypes.items()]
    children = []
    if changes:
        children.append((LOCAL, edit(source, changes)))
    if prototypes:
        children.append((PROTOTYPE, edit(source, prototypes)))
    if len(changes) > 1:
        children += [(LOCAL, edit(source, [change])) for change in changes[:LIMIT]]
    children = children[:LIMIT + 2]
    if casts:
        children.append((CAST, edit(source, casts)))
    if len(casts) > 1:
        children += [(CAST, edit(source, [change])) for change in casts[:LIMIT]]
    return children


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'asm'), 'archs': ('mips',)}
