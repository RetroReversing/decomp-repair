"""A function the game wrote with a `...` tail, spelled with fixed (or `volatile`) parameters instead.

A varargs function stores its argument registers to their home slots in the caller's frame (`sw $a0, 0x0($sp)` ...
`sw $a3, 0xC($sp)`) as its very first instructions, before `addiu $sp` allocates its own frame: `va_start` may need
them. Nothing else puts a store of an argument register to `sp+4*reg` ahead of the frame. A small N64 printf-like
wrapper (SN GCC 2.8.1, a body that only calls the formatter) sat at 110 as `volatile` fixed parameters: the volatile
reads/writes put the spills in, but after the frame and at the wrong offsets; plain fixed parameters left them out
(400). Written `void f(s32 arg0, ...) { callee(); }` it was exact (0).

The target tells how many parameters are named: SN GCC 2.8.1 spills from the last named parameter's register
(hypothesis: its own va_start starts at the last named argument), so spills from `$a0` mean one named parameter and
spills from `$a1` two. GCC 2.7.2 (KMC) spills only the unnamed registers, so spills from `$a1` can also mean one named
parameter. Both counts are offered (one or two named parameters; the judge decides) and the rest becomes `...`.

Evidence read from the target: the instructions before the first `addiu $sp, $sp, -N` (or the first non-store) are
`sw $aK, 4*K($sp)` for K from the first spilled register up to `$a3`. Declined when the C already has a `...`, when the
body reads a parameter that would become unnamed (it would need `va_arg`), or when the function isn't a plain
definition. The named parameters keep their type and name minus `volatile` (a 64-bit or floating type becomes `s32`:
each named argument is one register here), and an earlier prototype of the function is rewritten to match, or it
would conflict with the definition.
"""
import re

from . import m2cfix
from .csource import _blank
from .integer_repair_support import edit, view

FAMILY = 'variadic_home_spill'
FAMILIES = (FAMILY,)
IDENT = r'[A-Za-z_]\w*'
WIDE = re.compile(r'\b(?:long\s+long|s64|u64|f64|f32|float|double)\b')
_SPILL = re.compile(r'^sw\s+\$a([0-3])\s*,\s*(0x[0-9a-fA-F]+|\d+)?\(\$sp\)\s*$')
_NOT_A_DECLARATION = {'return', 'else', 'do', 'goto', 'case', 'sizeof'}


def spilled_from(asm):
    """The first argument register of the run `sw $aK, 4K($sp)` .. `$a3` that opens the function, or None."""
    regs = []
    for raw in (asm or '').splitlines():
        line = re.sub(r'/\*.*?\*/', '', raw).strip()
        if not line or line.startswith(('glabel', '.', 'endlabel', 'nonmatching')):
            continue
        hit = _SPILL.match(line)
        if not hit or int(hit[2] or '0', 0) != 4 * int(hit[1]):
            break
        regs.append(int(hit[1]))
    if not regs or regs != list(range(regs[0], 4)) or regs[0] > 1:
        return None
    return regs[0]


def _named(param, index):
    """One named parameter as the variadic definition writes it: no `volatile`, one register wide."""
    text = re.sub(r'\bvolatile\b', '', param).strip()
    text = re.sub(r'\s+', ' ', text)
    if WIDE.search(text) and '*' not in text:
        text = WIDE.sub('s32', text, count=1)
    return text or f's32 arg{index}'


def _list(params, count):
    return [_named(params[i], i) if i < len(params) and params[i].strip() else f's32 arg{i}' for i in range(count)]


def _params(clean, opening):
    """(index of the definition's `(`, index of its `)`, parameters) before the body's `{`."""
    right = clean.rfind(')', 0, opening)
    depth, left = 0, right
    while left >= 0:
        depth += (clean[left] == ')') - (clean[left] == '(')
        if depth == 0:
            break
        left -= 1
    if right < 0 or left < 0:
        return None
    text = clean[left + 1:right].strip()
    parts = [] if text in ('', 'void') else [p.strip() for p in m2cfix._split_top_level(text)]
    return left, right, parts


def _rewrite(source, clean, part, name, count):
    got = _params(clean, part.opening)
    if not got:
        return None
    left, right, params = got
    if any('...' in p for p in params):
        return None
    body = part.clean[part.opening:part.end]
    for p in params[count:]:
        hit = re.search(IDENT + r'\s*$', p)
        if hit and re.search(r'(?<![\w.])' + re.escape(hit[0]) + r'\b', body):
            return None  # an unnamed parameter the body reads would need va_arg
    named = _list(params, count)
    edits = [(left + 1, right, ', '.join(named + ['...']))]
    # an earlier prototype conflicts with a variadic definition: spell it the same way
    prototype = re.compile(r'(?m)^(?P<head>[ \t]*(?:extern\s+|static\s+)*(?P<type>[A-Za-z_][\w \t\*]*?)\b' + re.escape(name)
                           + r'\s*)\((?P<list>[^(){};]*)\)\s*;')
    for hit in prototype.finditer(clean):
        if set(hit['type'].split()) & _NOT_A_DECLARATION or not hit['type'].strip():
            continue
        text = hit['list'].strip()
        old = [] if text in ('', 'void') else [p.strip() for p in m2cfix._split_top_level(text)]
        if any('...' in p for p in old):
            continue
        pieces = _list(old, count) if old else named
        edits.append((hit.start('list'), hit.end('list'), ', '.join(pieces + ['...'])))
    return edit(source, edits)


def variants(source, name, asm):
    first = spilled_from(asm)
    part = view(source, name)
    if first is None or not part:
        return []
    clean = _blank(source)
    counts = [first + 1] + ([first] if first >= 1 else [])
    out = []
    for count in counts:
        text = _rewrite(source, clean, part, name, count)
        if text and text != source and (FAMILY, text) not in out:
            out.append((FAMILY, text))
    return out


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'asm'), 'order': 64,
          'archs': ('mips',)}  # the registry: no caller wiring (registry.py)
