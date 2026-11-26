"""A callee with a prototype, called from several places, that the target hands the caller's own leading argument too.

m2c drafts a call that never loads `$a0` as one with that argument missing, and when its other arguments are loaded
it writes the prototype it saw (`s32 f(s32);`, the value put in `$a1` seen as the only argument). One call is
`passthrough_argument`'s case (it widens the prototype only when the call is the callee's only one) and calls without
a prototype are `argument_passthrough_to_callees`'s. The mix is common in a dispatcher: the callee sits in two arms, so
neither family could pass the caller's pointer on, and the target's `addiu $a1, $zero, 0x12c` where the draft has
`addiu $a0, $zero, 0x12c` is two register rows that no statement order removes:

    s32 f(s32);   ...   case 8:  v = 0x12C; f(v); break;   default: v = 0x1B8; if (c) { f(v); } break;
 -> s32 f(void *, s32); ...  case 8:  v = 0x12C; f(arg0, v); break;   default: ...  f(arg0, v); ...

A KMC GCC 2.7.2 N64 dispatcher (`-G0 -mips3 -mgp32 -mfp32 -O2`, 8 cases) was 10 with the one-argument calls and 1
(then exact with its jump table's labels, `linked_switch_labels`) with `f(arg0, v)` in both of its calls.

The evidence is the target's assembly: `argument_passthrough_to_callees.incoming_sites` says, for every `jal`, which
argument registers still hold the caller's own value on every path from the entry. A callee qualifies when the body
calls it at least as often as the target does (cross-jumping merges calls), every call has as many arguments as the prototype (before this source's
function, `extern` allowed, no variadics, and no other prototype in the project header), every `jal` of it sees the
caller's `$a0` (K leading registers) and the caller names those parameters `arg0`..`arg(K-1)` itself without ever
writing them. Each K from 1 up to what every call sees (and 4 registers in all) is one child: `arg0`.. first in every
call, their types first in the prototype. Several callees are separate children, at most 6."""
import re

from .argument_passthrough_to_callees import _REGISTERS, _kills, _parameters, _program, _written, incoming_sites
from .csource import _blank
from .integer_repair_support import IDENT, edit, view
from .pattern_repairs import close

FAMILY = 'leading_argument_widen'
FAMILIES = (FAMILY,)
LIMIT = 6
_KEYWORDS = {'if', 'while', 'for', 'switch', 'return', 'sizeof'}


def _split(text):
    parts, depth, current = [], 0, ''
    for ch in text:
        if ch == ',' and depth == 0:
            parts.append(current.strip())
            current = ''
            continue
        depth += (ch in '([{') - (ch in ')]}')
        current += ch
    if current.strip():
        parts.append(current.strip())
    return parts


def _unwritten_sites(asm):
    """{callee: [{argument index}, ...]} for code `incoming_sites` cannot follow (a `switch`'s jump table: `jr $v0`):
    the argument registers that nothing in the function writes (the draft's own `$a1` loads and its callees' results
    never touch `$a0` in a dispatcher). Weaker than the walk, which proves a register along every path: here a callee
    that ran earlier on a path may have clobbered it, so the judge is the proof."""
    instructions, _ = _program(asm)
    if not any(op == 'jr' and operands.strip() != '$ra' for op, operands in instructions):
        return {}
    written = set()
    for op, operands in instructions:
        written |= _kills(op, operands)
    kept = {index for index, register in enumerate(_REGISTERS) if register not in written}
    sites = {}
    for op, operands in instructions:
        if op == 'jal':
            sites.setdefault(operands, []).append(set(kept))
    return sites


def variants(source, name, asm=None, arch=None, header=''):
    if arch not in (None, 'mips') or not asm:
        return []
    part = view(source, name)
    if not part:
        return []
    parameters = _parameters(part)
    if not parameters or [index for _, index in parameters] != list(range(len(parameters))):
        return []
    clean = part.clean
    body = clean[part.opening + 1:part.end - 1]
    if any(_written(body, f'arg{index}') for _, index in parameters):
        return []
    sites = incoming_sites(asm) or _unwritten_sites(asm)
    if not sites:
        return []
    preamble = clean[:part.opening]
    outside_header = _blank(header)
    kinds = [kind for kind, _ in parameters]
    calls = {}
    for hit in re.finditer(rf'(?<![\w.>])({IDENT})\s*\(', body):
        callee = hit[1]
        if callee in _KEYWORDS or callee == name:
            continue
        opening = part.opening + 1 + hit.end() - 1
        end = close(clean, opening, '(', ')')
        if not end:
            continue
        calls.setdefault(callee, []).append((opening + 1, end - 1))
    out = []
    for callee, spots in calls.items():
        if callee not in sites or len(sites[callee]) > len(spots):
            continue
        if any(found.group(1).strip() for found in re.finditer(
                rf'\b{re.escape(callee)}\s*\(([^()]*)\)\s*;', outside_header)):
            continue
        prototypes = list(re.finditer(
            rf'(?m)^[ \t]*(?:extern\s+)?[\w ]+?[\s*]+{re.escape(callee)}\s*\((?P<params>[^()]*)\)\s*;', preamble))
        if len(prototypes) != 1:
            continue
        declared = prototypes[0]['params'].strip()
        if not declared or declared == 'void' or '...' in declared:
            continue
        count = len(_split(declared))
        if any(not clean[start:stop].strip() or len(_split(clean[start:stop])) != count for start, stop in spots):
            continue
        if any(clean[start:stop].strip().startswith('arg0') for start, stop in spots):
            continue
        reach = 0
        while reach < len(kinds) and reach + count < 4 and all(reach in found for found in sites[callee]):
            reach += 1
        for lead in range(1, reach + 1):
            names = ', '.join(f'arg{index}' for index in range(lead))
            types = ', '.join(kinds[:lead])
            at = prototypes[0].start('params')
            changes = [(at, at, types + ', ')] + [(start, start, names + ', ') for start, _ in spots]
            out.append((FAMILY, edit(source, changes)))
    return list(dict.fromkeys(out))[:LIMIT]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'asm', 'arch', 'header'),
          'archs': ('mips',)}
