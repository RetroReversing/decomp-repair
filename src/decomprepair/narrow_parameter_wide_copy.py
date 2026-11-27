"""A narrow parameter (`s16 arg0`) written as a word parameter with a narrow local copied from it at the top, the
reads that cast it to its own width or narrower kept on the word parameter.

A function declared `void f(s16 arg0)` has two pseudos for its argument under gcc 2.7.2: the incoming register's
word copy and the `s16` variable, a subreg of it. cse rewrites a sign-extended read of the variable to the word copy,
but `(u16) arg0` stays a zero-extension of the `s16` variable, so the two reads take different registers. When the
original was `void f(s32 arg0) { s16 idx = arg0; ... (u16) arg0 ... idx * 6 ... }`, the masked test reads the word
parameter and every later index the narrow local: on an N64 function (SN GCC 2.7.2, `-G0 -mips3 -O1`, 64
instructions) the target's `andi $v0, $s1, 0xFFFF` read the incoming copy where `(u16) arg0` on the `s16` parameter
read `$s0` (5); with the word parameter and the `s16` local it was exact. Reading the masked test through the local too
stayed at 5, and widening the parameter with no local was 115, so the child writes all three at once.

narrow_parameter_wide_copy
    For each `s8`/`u8`/`s16`/`u16` (or `short`/`char`) parameter read at least twice and never address-taken, the
    signature takes `s32 NAME_in` (`u32` for an unsigned one), `T NAME = NAME_in;` opens the body, and each read cast
    to an integer type no wider than T (`(u16) NAME`, `(s8) NAME`) reads `NAME_in`; a second child reads every use
    through the local. The value of a cast read is the same either way: the low bits agree.
"""
import re

from .integer_repair_support import IDENT, edit, view

FAMILY = 'narrow_parameter_wide_copy'
FAMILIES = (FAMILY,)
WIDTH = {'s8': 8, 'u8': 8, 'char': 8, 'signed char': 8, 'unsigned char': 8,
         's16': 16, 'u16': 16, 'short': 16, 'signed short': 16, 'unsigned short': 16}
CAST_WIDTH = dict(WIDTH, **{'s32': 32, 'u32': 32, 'int': 32, 'unsigned int': 32, 'signed int': 32})
CAST = re.compile(r'\(\s*(?P<type>(?:(?:un)?signed\s+)?(?:char|short|int)|[su](?:8|16|32))\s*\)\s*$')


def _parameters(part):
    signature = re.search(r'\(([^()]*)\)\s*$', part.clean[:part.opening])
    if not signature or signature[1].strip() in ('', 'void'):
        return []
    found, position = [], signature.start(1)
    for piece in signature[1].split(','):
        match = re.fullmatch(r'\s*((?:(?:un)?signed\s+)?(?:char|short|int)|[A-Za-z_]\w*)\s+(' + IDENT + r')\s*', piece)
        if match:
            found.append((position + match.start(1), position + match.end(2), match[2], ' '.join(match[1].split())))
        position += len(piece) + 1
    return found


def variants(source, name):
    part = view(source, name)
    if not part or re.search(r'\b(?:asm|__asm__)\b|^\s*#', part.body, re.M):
        return []
    out = []
    body_start = part.opening + 1
    for start, end, param, kind in _parameters(part):
        width = WIDTH.get(kind)
        if width is None or re.search(rf'\b{param}_in\b', part.clean):
            continue
        reads = [hit for hit in re.finditer(rf'(?<![\w.>]){param}\b', part.clean[body_start:part.end])]
        if len(reads) < 2 or re.search(rf'&\s*{param}\b(?!\s*(?:->|\[))', part.body):
            continue
        if any(re.match(r'\s*(?:[-+*/%&|^]|<<|>>)?=(?!=)|\s*(?:\+\+|--)', part.clean[body_start + hit.end():])
               or re.search(r'(?:\+\+|--)\s*$', part.clean[:body_start + hit.start()]) for hit in reads):
            continue  # an assigned parameter: the copy would change which value later reads see
        wide = 'u32' if kind.startswith(('u', 'unsigned')) else 's32'
        head = [(start, end, f'{wide} {param}_in'),
                (body_start, body_start, f'\n    {kind} {param} = {param}_in;')]
        cast_reads = []
        for hit in reads:
            before = part.clean[:body_start + hit.start()]
            cast = CAST.search(before)
            if cast and CAST_WIDTH[' '.join(cast['type'].split())] <= width:
                cast_reads.append((body_start + hit.start(), body_start + hit.end(), f'{param}_in'))
        if cast_reads:
            out.append(edit(source, head + cast_reads))
        out.append(edit(source, head))
    return [(FAMILY, child) for child in dict.fromkeys(out) if child != source]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}
