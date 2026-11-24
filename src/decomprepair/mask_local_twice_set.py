"""A word cleared with a mask too wide for `andi`, the mask staged in a block local that the `and` sets again:
`(*(s32 *)((char *)(p) + 0x58)) &= -0x1C1;` as `{ s32 m = -0x1C1; m &= (*(s32 *)((char *)(p) + 0x58)); ... = m; }`.

KMC GCC 2.7.2 (`-O2`, N64): the mask is loaded into a register of its own. Written `x &= K`, that register is set once,
and the first scheduler gives an insn that makes a register live with one set (`birthing_insn_p`) the block's highest
priority: the constant is scheduled right before its `and`, after the loads and the next call's argument setup.
Staged in a local that the `and` sets again, its register has two sets, keeps its own low priority and is loaded
first in the block, before the call's arguments and the loads (`addiu $v0, $zero, -0x1c1; addiu $a1, $sp, 0x88;
lw $a3, 0x58($a0)`), which also hands it `$v0` in local-alloc. A 2,503-instruction projectile update: 295 -> 5,
where every spelling of the mask (`~0x1C0`, `0xFFFFFE3F`, `u32`, a record member, a mask local set once, the operands
swapped) compiled the same. The reading is from the output; the judge decides.

A site is a statement `L &= K;` whose `K` is an integer literal `andi` cannot take (negative, `~...`, or above
0xFFFF) and whose `L` has no call or `++`/`--` (it is read and written once each, as before). Each site gives a child,
and with several sites one more child has them all.
"""
import re

from .integer_repair_support import view

FAMILY = 'mask_local_twice_set'
FAMILIES = (FAMILY,)
LIMIT = 6
LOCAL = 'andMask'
_SITE = re.compile(r'(?m)^(?P<ind>[ \t]*)(?P<lhs>[^;{}\n=]+?)\s*&=\s*(?P<k>-\s*(?:0x[0-9A-Fa-f]+|\d+)|~\s*(?:0x[0-9A-Fa-f]+|\d+)'
                   r'|0x[0-9A-Fa-f]{5,8}|\d{6,10})[uUlL]*\s*;[ \t]*\n')


def _wide(k):
    k = re.sub(r'\s+', '', k)
    if k[0] in '-~':
        return True
    return int(k, 0) > 0xFFFF


def _sites(source, name):
    part = view(source, name)
    if not part:
        return []
    clean, lo, hi = part.clean, part.opening + 1, part.end - 1
    if re.search(rf'\b{LOCAL}\b', clean[lo:hi]):
        return []
    sites = []
    for found in _SITE.finditer(clean, lo, hi):
        lhs = found['lhs'].strip()
        if not _wide(found['k']) or '++' in lhs or '--' in lhs or re.search(r'\w\s*\(\s*[^*(]', lhs.replace('(*(', '')):
            continue
        if lhs.startswith(('if', 'while', 'for', 'return', 'else')):
            continue
        sites.append(found)
    return sites


def _apply(source, sites):
    out = source
    for found in sorted(sites, key=lambda m: m.start(), reverse=True):
        lhs = source[found.start('lhs'):found.end('lhs')].strip()
        k = re.sub(r'\s+', '', found['k'])
        line = f"{found['ind']}{{ s32 {LOCAL} = {k}; {LOCAL} &= {lhs}; {lhs} = {LOCAL}; }}\n"
        out = out[:found.start()] + line + out[found.end():]
    return out


def variants(source, name, header=''):
    sites = _sites(source, name)[:LIMIT]
    picks = [[site] for site in sites] + ([sites] if len(sites) > 1 else [])
    return [(FAMILY, _apply(source, pick)) for pick in picks]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'header')}  # the registry: no caller wiring (registry.py)
