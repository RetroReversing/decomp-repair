"""A loop bound m2c copied out of a global (`u32 n = gCount; for (i = 0; i < n; i++)`) read from the global in the
condition again, with the loop's stores through byte offsets written as a member of a one-word record and an unsigned
counter of the loop's own.

KMC GCC 2.7.2 (`-O2`, N64): the target loads the bound once (`lbu $v0, gCount`), tests it for the zero-trip guard and
keeps a copy for the loop's test (`move $t0, $v0` after the guard): loop.c hoisted the condition's load out of the loop
and cse2 turned the hoisted load into a copy of the guard's. loop.c hoists a load only when no store in the loop may
alias it (`invariant_p`, sched.c `true_dependence`): a store through `*((s32 *) (((char *) &table) + off))` is not a
structure reference (the cast hides the sum) and may alias the bound, while `((Word *) (((char *) &table) + off))->w`
is a member at a varying address, which a fixed scalar of another size cannot alias. The counter is compared
unsigned (`sltu`) against the byte bound, so it is a `u32` of the loop's own (m2c's function-wide `long` counter
gives `slt`). On a 1315-instruction sound-sequence interpreter's voice scan, 4000 -> 3870 with the three together (the
bound alone was worse, 5475). The reading is from loop.c and sched.c; the judge decides.

Rewrites a `for (C = 0; C < N; C++)` whose bound `N` is a local of the enclosing block initialised from a global
(`T N = G;`, read nowhere else): the declaration goes, the condition reads `G`, the loop's stores `*((T *) (((char *)
(&S)) + X)) op= E;` become `((RepairWordT *) (((char *) (&S)) + X))->w op= E;` (a typedef added before the function),
and when the counter is a function-level signed local that the code after the loop assigns before reading, the loop
counts with a block-local `u32 C` of its own (the same name, so nothing else changes).
"""
import re

from .integer_repair_support import IDENT, view
from .pattern_repairs import close

FAMILY = 'loop_global_bound_member_store'
FAMILIES = (FAMILY,)
LIMIT = 4
_STORE = re.compile(r'\*\s*\(\s*\(\s*(?P<type>s32|u32|s16|u16|int)\s*\*\s*\)\s*\(\s*\(\s*\(\s*char\s*\*\s*\)\s*\(\s*&\s*'
                    rf'(?P<sym>{IDENT})\s*\)\s*\)\s*\+\s*(?P<off>{IDENT})\s*\)\s*\)\s*(?P<op>[|&^+-]?=)(?!=)')


def variants(source, name, header=''):
    part = view(source, name)
    if not part:
        return []
    clean, lo, hi = part.clean, part.opening + 1, part.end - 1
    out = []
    for loop in re.finditer(rf'\bfor\s*\(\s*(?P<c>{IDENT})\s*=\s*0\s*;\s*(?P=c)\s*<\s*(?P<n>{IDENT})\s*;\s*(?P=c)\s*\+\+\s*\)',
                            clean[lo:hi]):
        at = lo + loop.start()
        counter, bound = loop['c'], loop['n']
        decl = None
        for found in re.finditer(rf'(?m)^[ \t]*(?:u8|u16|u32|s32|int|unsigned int)\s+{bound}\s*=\s*(?P<g>{IDENT})\s*;[ \t]*\n',
                                 clean[lo:at]):
            decl = found
        if not decl:
            continue
        glob = decl['g']
        start, stop = lo + decl.start(), lo + decl.end()
        if re.search(rf'(?m)^[ \t]*[\w \t*]*\b{glob}\s*[;=\[]', clean[lo:hi]) or glob in (counter, bound):
            continue  # the "global" is declared in the function
        body_open = re.compile(r'\s*\{').match(clean, lo + loop.end())
        if not body_open:
            continue
        body_end = close(clean, body_open.end() - 1, '{', '}')
        if not body_end:
            continue
        mentions = [m.start() for m in re.finditer(rf'(?<![\w.>]){bound}\b', clean[lo:hi])]
        if len(mentions) != 2:
            continue  # the copy is read only in the condition
        body = clean[body_open.end():body_end - 1]
        stores = list(_STORE.finditer(clean, body_open.end(), body_end - 1))
        if not stores or re.search(r'\bvolatile\b', body):
            continue
        calls = re.sub(r'\(\s*(?:\w+\s*)+\**\s*\)', ' ', body)  # casts are not calls
        if re.search(rf'\b(?!(?:if|while|for|switch|sizeof)\b){IDENT}\s*\(', calls) or re.search(rf'\b{glob}\s*(?:[-+*/|&^]?=(?!=)|\+\+|--)|&\s*{glob}\b', body):
            continue  # the body could change the global the bound is read from again
        edits = [(start, stop, ''), (lo + loop.start('n'), lo + loop.end('n'), glob)]
        kinds = set()
        for store in stores:
            word = 'RepairWord' + store['type'].replace('unsigned ', 'u').capitalize()
            kinds.add((word, store['type']))
            edits.append((store.start(), store.start('op'),
                          f'(({word} *) (((char *) (&{store["sym"]})) + {store["off"]}))->w '))
        counter_decl = re.search(rf'(?m)^[ \t]*(?:long|s32|int|signed int)\s+{counter}\s*;', clean[lo:hi])
        block_open = clean.rfind('{', lo, start)
        if counter_decl and lo + counter_decl.start() < block_open:
            later = re.search(rf'(?<![\w.>]){counter}\b', clean[body_end:hi])
            if later and not re.match(rf'{counter}\s*=(?!=)', clean[body_end + later.start():]):
                continue
            line = clean.find('\n', block_open) + 1
            indent = re.match(r'[ \t]*', clean[line:])[0]
            edits.append((line, line, f'{indent}u32 {counter};\n'))
        text = source
        for begin, end, new in sorted(edits, key=lambda item: item[0], reverse=True):
            text = text[:begin] + new + text[end:]
        typedefs = ''.join(f'typedef struct {{ {kind} w; }} {word};\n' for word, kind in sorted(kinds)
                           if not re.search(rf'\b{word}\b', source))
        head = text.rfind('\n', 0, source.rfind(name, 0, part.opening)) + 1
        text = text[:head] + typedefs + text[head:]
        out.append((FAMILY, text))
        if len(out) >= LIMIT:
            break
    return out


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'header')}  # the registry: no caller wiring (registry.py)
