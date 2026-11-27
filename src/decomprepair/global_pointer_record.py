"""A global pointer that the target reloads before each store through it, declared as the one-member record it was.

Matched on a KMC gcc 2.7.2 (`-G0 -mips3 -mgp32 -mfp32 -O2`) projectile update of 2,503 instructions. It stores three
floats and a vector through a global pointer, `*(f32 *)((char *)(gBlock) + 0x34) = ...;` and so on, and the target
reloads the pointer (`lui`/`lw`) before every store; the candidate loaded it once. Spellings of the store addresses
(an index, an integer sum, `M2C_FIELD`) all compiled to the same code. With the global declared as a record of one
pointer, `extern struct { void *block; } gBlock;`, and read as `gBlock.block`, the reloads came back: 5435 -> 4835
(the same as declaring the pointer `volatile`, which the game is less likely to have done).

global_pointer_record
    A global pointer the source declares itself (`extern T *G;`, not in the project header) that is the base of at
    least two stores `*(U *)((char *)(G) + K) = ...;` or `M2C_FIELD(G, U *, K) = ...;` becomes
    `extern struct { T *block; } G;` with every use read as `G.block`, an assignment of the pointer included
    (`G = alloc();` is `G.block = alloc();`). One child per global, none for a global whose address is taken.
    On an SN gcc 2.8.1 (`-G0 -mips3 -O2 -mfp64`) voice setup of 55 instructions, which stores an allocation in the
    global and then sets 17 of its fields, the m2c draft with only this change went 1585 -> 0.

global_scalar_record
    The same for a scalar global the source declares itself (`extern s32 G;`) and updates in place (`G += 1;`,
    `G++;`, `G = G op ...;`): the target forms its address once (`lui`/`addiu`, then `lw`/`sw` through it) where a
    scalar is read and written with two `%lo` relocations. As `extern struct { s32 value; } G;` read as `G.value`
    the same function went 3302 -> 2797. One child per global.

global_pointer_read_record
    The same for a pointer global the source declares itself that is only *read* (fewer than two stores through it,
    never assigned or address-taken) at two or more places with a store between them: after a store through another
    pointer the target loads the global again, and the candidate keeps the first load. Matched on an SN gcc 2.8.1
    (`-G0 -mips3 -O2 -mfp64`) effect update of 71 instructions: after `sh` at offset 2 of the object the target
    reloads the pointer before reading a word through it. A store through a constant offset is a structure member to
    the compiler and did not invalidate the plain global's load; as `extern struct { void *block; } G;` it did
    (500 -> 240 alone, 0 with the two other edits). One child per global.

global_pointer_base_record
    m2c's address local for such a global (`void **base; base = &G;` with every use `(*base)`) hides the global from
    the steps above, which refuse a global whose address is taken. The local is written out (`G` at each use, its
    declaration and assignment dropped) and `global_pointer_record` or `global_pointer_read_record` applied to the
    result, as one child. The local's other uses must all be `*base` reads. On an SN gcc 2.8.1 (`-G0 -mips3 -O2 -mfp64`)
    actor update of 51 instructions the autopilot's best held the pointer this way: 210 -> 50 as the record, and 0 with
    its one-shot fence then removed.

Hypothesis, read from expr.c's `MEM_IN_STRUCT_P` marking but not traced through
    cse.c: a store marked as a structure member does not invalidate a scalar global's load, a member's load it does.
    The exact judge decides.
"""
import re

FAMILY = 'global_pointer_record'
SCALAR = 'global_scalar_record'
READ = 'global_pointer_read_record'
BASE = 'global_pointer_base_record'
FAMILIES = (FAMILY, SCALAR, READ, BASE)
LIMIT = 6
MEMBER = 'block'

_ID = r'[A-Za-z_]\w*'
_SCALAR = re.compile(rf'(?m)^extern (?P<type>(?:unsigned |signed )?{_ID}) (?P<name>{_ID});[ \t]*$')
_EXTERN = re.compile(rf'(?m)^extern (?P<type>(?:const )?{_ID}) \*(?P<name>{_ID});[ \t]*$')


def _stores(source, name):
    return len(re.findall(rf'\*\s*\(\s*{_ID}\s*\*\s*\)\s*\(\s*\(\s*char\s*\*\s*\)\s*\(?\s*{re.escape(name)}\s*\)?\s*\+'
                          rf'[^;=]*\)\s*\)?\s*=(?!=)', source))


def _field_stores(source, name):
    """m2c's `M2C_FIELD(G, T *, K) = ...;` stores through the global."""
    return len(re.findall(rf'(?m)^[ \t]*M2C_FIELD\s*\(\s*{re.escape(name)}\s*,[^;=]*\)\s*=(?!=)', source))


_STORE = re.compile(r'(?<![=!<>+\-*/|&^%])(?:[-+*/|&^%]|<<|>>)?=(?!=)|\+\+|--')


def _written_between(source, name):
    """True when a store through memory (`*...=`, `...->m =`, `a[i] =`, an M2C_FIELD) lies between two reads."""
    uses = [m.start() for m in re.finditer(rf'\b{re.escape(name)}\b', source)]
    if len(uses) < 2:
        return False
    for statement in source[uses[0]:uses[-1]].split(';'):
        store = _STORE.search(statement)
        if store and re.search(r'\*\s*\(|->|\]|FIELD\s*\(|\bF\s*\(', statement):
            return True
    return False


def _without_address_locals(source, name):
    """[source] with each `L = &G;` address local of an extern pointer written out as `G`, one per local."""
    result = []
    globals_ = {found.group('name') for found in _EXTERN.finditer(source)}
    for found in re.finditer(rf'(?m)^[ \t]*(?P<local>{_ID})[ \t]*=[ \t]*&[ \t]*(?P<global>{_ID});[ \t]*\n', source):
        local, glob = found.group('local'), found.group('global')
        if glob not in globals_:
            continue
        text = source[:found.start()] + source[found.end():]
        declaration = re.search(rf'(?m)^[ \t]*(?:const )?{_ID}[ \t]*\*[ \t]*\*[ \t]*{local};[ \t]*\n', text)
        if not declaration:
            continue
        text = text[:declaration.start()] + text[declaration.end():]
        text = re.sub(rf'\(\s*\*\s*{local}\s*\)', f'({glob})', text)
        text = re.sub(rf'\(\(\s*{glob}\s*\)\)', f'({glob})', text)
        if not re.search(rf'\b{local}\b', text):
            result.append(text)
    return result


def variants(source, name, header=''):
    result = _records(source, header)
    for inlined in _without_address_locals(source, name):
        result += [(BASE, child) for family, child in _records(inlined, header) if family in (FAMILY, READ)]
    return result[:LIMIT]


def _records(source, header):
    result = []
    for found in _EXTERN.finditer(source):
        glob = found.group('name')
        if header and re.search(rf'\b{re.escape(glob)}\b', header):
            continue
        if _stores(source, glob) + _field_stores(source, glob) < 2 or re.search(rf'&\s*{re.escape(glob)}\b', source):
            continue
        head = source[:found.start()] + f'extern struct {{ {found.group("type")} *{MEMBER}; }} {glob};'
        rest = re.sub(rf'\b{re.escape(glob)}\b(?!\s*\.)', f'{glob}.{MEMBER}', source[found.end():])
        result.append((FAMILY, head + rest))
    for found in _EXTERN.finditer(source):
        glob = found.group('name')
        if header and re.search(rf'\b{re.escape(glob)}\b', header):
            continue
        body = source[found.end():]
        if _stores(source, glob) + _field_stores(source, glob) >= 2 or not _written_between(body, glob) or re.search(
                rf'&\s*{re.escape(glob)}\b|\b{re.escape(glob)}\s*=(?!=)|(?:\.|->)\s*{re.escape(glob)}\b', body):
            continue
        head = source[:found.start()] + f'extern struct {{ {found.group("type")} *{MEMBER}; }} {glob};'
        result.append((READ, head + re.sub(rf'\b{re.escape(glob)}\b(?!\s*\.)', f'{glob}.{MEMBER}', body)))
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
