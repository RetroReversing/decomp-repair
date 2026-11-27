"""The width of a read through a loaded pointer, taken from the target's own load.

m2c types `*ptr` from nothing when `ptr` was itself loaded from memory, and writes `*((s32 *) (*((s32 *) X)))`. When
the target reads that pointee with `lbu` (or `lb`, `lhu`, `lh`), the word read is a wrong source, and no field offset
or symbol names it, so `field_width` has nothing to retype. A saved N64 draft sat one row from exact on this: the first
test of an object's state byte was a `lw` in C and a `lbu` in the target.

The evidence is a `lw $r, ...` followed by a narrow load from `0($r)` before `$r` is written again; an `addu` that
adds an index to the loaded pointer (`addu $v0,$v0,$a1`) passes it on to its destination, so a byte table whose base
pointer was loaded from a record and indexed by a variable counts (an N64 object loop's count, `lbu $s1,($v0)` where the
saved C had `*(s32 *)(*(s32 *)(rec + 0x14) + i)`: 595 -> 395, and with the next fix 0). Each word read of
a read (`*(s32 *)(*...)`) is given each such width: all of them together, and one at a time.
"""
import re

from .csource import _blank, find
from .pattern_repairs import close

FAMILY = 'loaded_pointee_width'
FAMILIES = (FAMILY,)

NARROW = {'lb': 's8', 'lbu': 'u8', 'lh': 's16', 'lhu': 'u16'}
INSTRUCTION = re.compile(r'^\s*(?:/\*[^*]*\*/\s*)?([a-z][\w.]*)\s+\$(\w+)(?:\s*,\s*(.*?))?\s*$')
ZERO_OFFSET = re.compile(r'(?:0x0|0)?\(\s*\$(\w+)\s*\)')
KEEPS_FIRST = ('sb', 'sh', 'sw', 'swc1', 'sdc1', 'sd', 'swl', 'swr', 'beq', 'bne', 'beql', 'bnel', 'beqz', 'bnez',
               'beqzl', 'bnezl', 'blez', 'bgtz', 'bltz', 'bgez', 'jr', 'mtc1', 'ctc1', 'mtc0')  # (they only read it)
ADDS = ('addu', 'add', 'daddu')
REACH = 8  # instructions between the pointer's load and the read through it
WORD_READ = re.compile(r'\*\s*\(?\s*\(\s*(?P<type>s32|u32|int)\s*\*\s*\)\s*\(*\s*\*')
SITES_MAX = 6


def _widths(asm):
    """The narrow types the target reads through a pointer it had just loaded."""
    loaded, found = {}, []
    for line in (asm or '').splitlines():
        instruction = INSTRUCTION.match(line)
        if not instruction:
            if re.match(r'\s*(?:\.\w+|\w+):', line):
                loaded = {}  # (a label: another path may reach it with something else in the register)
            continue
        op, first, rest = instruction.groups()
        loaded = {register: age + 1 for register, age in loaded.items() if age < REACH}
        base = ZERO_OFFSET.fullmatch(rest or '')
        if op in NARROW and base and base[1] in loaded and NARROW[op] not in found:
            found.append(NARROW[op])
        if op in ('jal', 'jalr'):
            loaded = {}
        elif op == 'lw' and first not in ('sp', 'ra'):
            loaded[first] = 0
        elif op in ADDS and (ages := [loaded[r] for r in re.findall(r'\$(\w+)', rest or '') if r in loaded]):
            loaded[first] = min(ages)  # the pointer plus an index is still the loaded pointer's object
        elif op not in KEEPS_FIRST:
            loaded.pop(first, None)
    return found


def variants(source, name, asm):
    """[(family, source)]: each word read through a loaded pointer at the width the target reads it with."""
    span = find(source, name)
    widths = _widths(asm)
    if not span or not widths:
        return []
    clean = _blank(source)
    opening = clean.find('{', span[0], span[1])
    end = close(clean, opening, '{', '}') if opening >= 0 else None
    if not end:
        return []
    sites = []
    for read in WORD_READ.finditer(clean, opening, end):
        before = clean[opening:read.start()].rstrip()
        if before[-1:] in (')', ']') or re.search(r'[\w]$', before) and not re.search(r'\breturn$', before):
            continue  # (a multiplication, not a read)
        sites.append(read.span('type'))
    if not sites:
        return []

    def retype(chosen, kind):
        text = source
        for a, b in sorted(chosen, reverse=True):
            text = text[:a] + kind + text[b:]
        return text
    result = []
    for kind in widths:
        result.append((FAMILY, retype(sites, kind)))
        if len(sites) > 1:
            result += [(FAMILY, retype([site], kind)) for site in sites[:SITES_MAX]]
    return result


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'asm'), 'archs': ('mips',)}
