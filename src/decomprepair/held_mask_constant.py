"""m2c's mask of a known constant (`4 & 0xFFFF`) written as the narrow local the game held it in.

m2c propagates a constant into an `andi` that reads the register holding it, so a halfword the game set once,

    u16 step = 4;
    ...
    if (step < abs(diff)) heading += step;

comes back as `t = 4 & 0xFFFF; if (t < abs(diff)) x = heading + t;`, once per branch. The compiler folds the mask, so the
constant is loaded where it is used: the saved register the game kept it in (`addiu $s3, $zero, 4` in an early delay slot,
`andi $a0, $s3, 0xffff` at each use), its frame slot and every register after it are lost. A steering routine of a seeking
shot that spawns linked objects (231 instructions, SN64 GCC 2.8.1, `-G0 -mips3 -O2`) went from 4253 to 3045 with this
edit alone.

Children, per constant and mask (`0xFFFF` a `u16`, `0xFF` a `u8`): one local declared with the constant, every
`K & M` reading it, and the temporaries that only ever held that value replaced by it (first), then the same keeping the
temporaries; with several constants, one child does them all. When the target's assembly is given it must have an `andi`
with that mask. The values are unchanged; whether the game held the constant is the exact judge's to decide."""
import re

from .integer_repair_support import IDENT, NUMBER, edit, integer, locals_for, refs, view

FAMILY = 'held_mask_constant'
FAMILIES = (FAMILY,)
LIMIT = 6
TYPES = {0xFF: ('u8', 'unsigned char'), 0xFFFF: ('u16', 'unsigned short')}
# a whole operand only: after `(`, `,` or a plain `=`, and before `)`, `,` or `;` (no precedence can rebind the mask)
MASKED = re.compile(rf'(?:(?<=[(,])|(?<![=!<>+\-*/%&|^]=)(?<==))(?P<lead>\s*)(?P<value>(?<![\w.])(?P<k>{NUMBER})\s*&\s*'
                    rf'(?P<m>0[xX](?:[fF]{{4}}|[fF]{{2}}))[uUlL]*)(?=\s*[),;])')


def _has_mask(asm, mask):
    return not asm or bool(re.search(rf'\bandi\b[^\n]*[,\s](?:0x0*{mask:x}|{mask})\b', asm, re.I))


def _sites(part):
    """{(constant, mask): [(start, end)]} of the masked constants in the body."""
    found = {}
    for hit in MASKED.finditer(part.clean, part.opening + 1, part.end):
        key = (integer(hit['k']), integer(hit['m']))
        if 0 < key[0] <= key[1]:
            found.setdefault(key, []).append(hit.span('value'))
    return found


def _temporaries(part, spans, local):
    """Edits that replace each temporary only ever assigned one of `spans` with `local`, and the sites they cover."""
    edits, covered = [], set()
    declared = {decl['name']: decl for decl in locals_for(part)}
    for start, end in spans:
        before = re.search(rf'(?<![\w.>])(?P<name>{IDENT})\s*=\s*$', part.clean[part.opening:start])
        after = re.compile(r'\s*;').match(part.clean, end)
        if not before or not after or before['name'] not in declared:
            continue
        decl = declared[before['name']]
        at = part.opening + before.start()
        if part.clean[:at].rstrip()[-1:] not in (';', '{', '}', ':'):
            continue  # the statement is the body of an `if` or a loop, or part of a longer expression
        uses = [use for use in refs(part, decl) if use.start() != at]
        written = r'\s*(?:[-+*/%&|^]|<<|>>)?=(?!=)|\s*(?:\+\+|--)'
        if any(use.start() < at or re.compile(written).match(part.clean, use.end())
               or part.clean[:use.start()].rstrip().endswith(('++', '--')) for use in uses):
            continue
        line = part.clean.rfind('\n', 0, at) + 1
        if not part.clean[line:at].strip():
            at = line - 1
        edits.append((at, after.end(), ''))
        gone = part.clean.rfind('\n', 0, decl.start()) + 1
        edits.append((gone - 1 if not part.clean[gone:decl.start()].strip() else decl.start(), decl.end(), ''))
        edits.extend((use.start(), use.end(), local) for use in uses)
        covered.add((start, end))
    return edits, covered


def _child(source, part, groups, header, inline):
    declarations, edits = [], []
    for (value, mask), spans in groups:
        local = f'held_{value}'
        while re.search(rf'\b{local}\b', source + header):
            local += '_'
        short, spelled = TYPES[mask]
        kind = short if re.search(rf'\b{short}\b', source + header) else spelled
        declarations.append(f'\n    {kind} {local} = {value};')
        temporaries, covered = _temporaries(part, spans, local) if inline else ([], set())
        edits += temporaries
        edits += [(start, end, local) for start, end in spans if (start, end) not in covered]
    edits.append((part.opening + 1, part.opening + 1, ''.join(declarations)))
    return edit(source, edits)


def variants(source, name, header='', asm=''):
    part = view(source, name)
    if not part or re.search(r'\b(?:asm|__asm__)\b', part.body):
        return []
    groups = [(key, spans) for key, spans in sorted(_sites(part).items()) if _has_mask(asm, key[1])]
    if not groups:
        return []
    chosen = ([groups] if len(groups) > 1 else []) + [[group] for group in groups]
    out = [_child(source, part, groups_, header, inline) for inline in (True, False) for groups_ in chosen]
    return [(FAMILY, child) for child in dict.fromkeys(out)][:LIMIT]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'header', 'asm'), 'order': 150,
          'archs': ('mips',)}
