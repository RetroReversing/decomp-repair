"""A global pointer that the target reloads before each store through it, declared as the one-member record it was.

Matched on a KMC gcc 2.7.2 (`-G0 -mips3 -mgp32 -mfp32 -O2`) projectile update of 2,503 instructions. It stores three
floats and a vector through a global pointer, `*(f32 *)((char *)(gBlock) + 0x34) = ...;` and so on, and the target
reloads the pointer (`lui`/`lw`) before every store; the candidate loaded it once. Spellings of the store addresses
(an index, an integer sum, `M2C_FIELD`) all compiled to the same code. With the global declared as a record of one
pointer, `extern struct { void *block; } gBlock;`, and read as `gBlock.block`, the reloads came back: 5435 -> 4835
(the same as declaring the pointer `volatile`, which the game is less likely to have done).

global_pointer_record
    A global pointer the source declares itself (`extern T *G;`, not in the project header) that is the base of at
    least two stores `*(U *)((char *)(G) + K) = ...;` becomes `extern struct { T *block; } G;` with every use read as
    `G.block`. One child per global.

global_scalar_record
    The same for a scalar global the source declares itself (`extern s32 G;`) and updates in place (`G += 1;`,
    `G++;`, `G = G op ...;`): the target forms its address once (`lui`/`addiu`, then `lw`/`sw` through it) where a
    scalar is read and written with two `%lo` relocations. As `extern struct { s32 value; } G;` read as `G.value`
    the same function went 3302 -> 2797. One child per global.

Hypothesis, read from expr.c's `MEM_IN_STRUCT_P` marking but not traced through
    cse.c: a store marked as a structure member does not invalidate a scalar global's load, a member's load it does.
    The exact judge decides.
"""
import re

FAMILY = 'global_pointer_record'
SCALAR = 'global_scalar_record'
FAMILIES = (FAMILY, SCALAR)
LIMIT = 6
MEMBER = 'block'

_ID = r'[A-Za-z_]\w*'
_SCALAR = re.compile(rf'(?m)^extern (?P<type>(?:unsigned |signed )?{_ID}) (?P<name>{_ID});[ \t]*$')
_EXTERN = re.compile(rf'(?m)^extern (?P<type>(?:const )?{_ID}) \*(?P<name>{_ID});[ \t]*$')


def _stores(source, name):
    return len(re.findall(rf'\*\s*\(\s*{_ID}\s*\*\s*\)\s*\(\s*\(\s*char\s*\*\s*\)\s*\(?\s*{re.escape(name)}\s*\)?\s*\+'
                          rf'[^;=]*\)\s*\)?\s*=(?!=)', source))


def variants(source, name, header=''):
    result = []
    for found in _EXTERN.finditer(source):
        glob = found.group('name')
        if header and re.search(rf'\b{re.escape(glob)}\b', header):
            continue
        if _stores(source, glob) < 2 or re.search(rf'&\s*{re.escape(glob)}\b|\b{re.escape(glob)}\s*=(?!=)', source):
            continue
        head = source[:found.start()] + f'extern struct {{ {found.group("type")} *{MEMBER}; }} {glob};'
        rest = re.sub(rf'\b{re.escape(glob)}\b(?!\s*\.)', f'{glob}.{MEMBER}', source[found.end():])
        result.append((FAMILY, head + rest))
    for found in _SCALAR.finditer(source):
        glob = found.group('name')
        if found.group('type') in ('struct', 'union', 'enum') or (header and re.search(rf'\b{re.escape(glob)}\b', header)):
            continue
        g = re.escape(glob)
        if re.search(rf'&\s*{g}\b', source) or not re.search(
                rf'\b{g}\s*(?:[-+*/|&^]|<<|>>)=|\b{g}\s*(?:\+\+|--)|(?:\+\+|--)\s*{g}\b|\b{g}\s*=\s*\(?\s*{g}\b', source):
            continue
        head = source[:found.start()] + f'extern struct {{ {found.group("type")} value; }} {glob};'
        rest = re.sub(rf'\b{g}\b(?!\s*\.)', f'{glob}.value', source[found.end():])
        result.append((SCALAR, head + rest))
    return result[:LIMIT]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'header')}
