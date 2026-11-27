"""A call's result written back into the variable its argument was computed from, through m2c's carrier local.

m2c names each value: the sum, a local for its halving's sign bias, and the call's result:

    temp_s3 = (a + b) - c;
    bias = (s32) (temp_s3 + (temp_s3 >> 0x1F));
    temp_s0 = ...;
    temp_s3_2 = f(0x100, bias >> 1);
    ... -temp_s3_2 ...

The game had one variable for the sum and the result (`x = f(0x100, half)`), so the target keeps both in one saved
register (`lh $s3; addu $s3; subu $s3; srl $a1,$s3,31; ... move $s3,$v0; negu $v0,$s3`), where the draft gives the
result a register of its own and the sum a temporary. Three edits matched an N64 function (KMC GCC 2.7.2 `-O1 -g`,
66 instructions, 80 -> 0), and only together: the result written back into the sum's variable (declared `s32`), the
halving written as `half = sum / 2;` where the bias was (the division expander's temporaries are the target's
`srl`/`addu`/`sra`), and the callee's prototype returning `s32` where the draft said `s16` (a narrow return is
extended again, `sll`/`sra`, where the target has a `move`). The merge alone with the `s16` prototype scored 420, with
the `s32` one 120.

The shape: `R = f(...);` where `R` is a local first mentioned there and never assigned again, an argument mentions a
local `B` that is assigned once before the call from an expression of a local `A`, `A` is mentioned nowhere after `B`'s
assignment and `B` nowhere after the call. Children: every `R` read as `A` (its declaration dropped, `A` declared
`s32` when it was another integer type), with the bias block written as a division when it is one, and the same with a
narrow prototype of `f` widened to `s32`. A hypothesis; the judge decides.
"""
import re

from .integer_repair_support import IDENT, edit, locals_for, refs, view

FAMILY = 'call_result_carrier_reuse'
FAMILIES = (FAMILY,)
LIMIT = 4
INTEGER = re.compile(r'^(?:s|u)(?:8|16|32)$')

_CALL = re.compile(rf'(?m)^[ \t]*(?P<r>{IDENT})[ \t]*=[ \t]*(?P<f>{IDENT})[ \t]*\((?P<args>[^;{{}}]*)\)[ \t]*;')
_ASSIGN = r'(?m)^[ \t]*{}[ \t]*=[ \t]*(?P<e>[^;{{}}]+);'
_BIAS = r'^\(?\s*(?:\(s32\)\s*)?\(?\s*{a}\s*\+\s*\(\s*{a}\s*>>\s*(?:0x1F|31)\s*\)\s*\)?\s*\)?$'


def variants(source, name):
    part = view(source, name)
    if not part or re.search(r'\b(?:volatile|asm|__asm__)\b', part.body):
        return []
    decls = {d['name']: d for d in locals_for(part)}
    out = []
    for call in _CALL.finditer(part.clean, part.opening + 1, part.end):
        result, callee = call['r'], call['f']
        if result not in decls or callee in decls or not INTEGER.match(decls[result]['type'].strip()):
            continue
        mentions = refs(part, decls[result])
        if not mentions or mentions[0].start() != call.start('r') or any(
                re.match(r'\s*(?:=(?!=)|\+\+|--|[-+*/%&|^]=)', part.clean[m.end():]) for m in mentions[1:]):
            continue
        for carrier in sorted(set(re.findall(rf'\b({IDENT})\b', call['args'])) & set(decls) - {result}):
            sets = [m for m in re.finditer(_ASSIGN.format(re.escape(carrier)), part.clean[:call.start()])
                    if m.start() > part.opening]
            later = [m for m in refs(part, decls[carrier]) if m.start() > call.end()]
            if len(sets) != 1 or later:
                continue
            define = sets[0]
            roots = [a for a in set(re.findall(rf'\b({IDENT})\b', define['e'])) & set(decls) - {carrier, result}]
            for root in roots:
                if not INTEGER.match(decls[root]['type'].strip()):
                    continue
                if any(m.start() > define.end() for m in refs(part, decls[root])):
                    continue
                if not any(m.start() < define.start() and re.match(r'\s*=(?!=)', part.clean[m.end():])
                           for m in refs(part, decls[root])):
                    continue
                edits = [(m.start(), m.end(), root) for m in mentions]
                d = decls[result]
                start = part.clean.rfind('\n', 0, d.start()) + 1
                stop = part.clean.find('\n', d.end())
                if part.clean[start:d.start()].strip() == '' and part.clean[d.end():stop].strip() == '':
                    edits.append((start, stop + 1, ''))
                else:
                    edits.append((d.start(), d.end(), ''))
                if decls[root]['type'].strip() != 's32':
                    edits.append((decls[root].start('type'), decls[root].end('type'), 's32'))
                if re.match(_BIAS.format(a=re.escape(root)), define['e'].strip()):
                    shift = re.search(rf'\b{re.escape(carrier)}\s*>>\s*1\b', call['args'])
                    if shift:
                        edits.append((define.start('e'), define.end('e'), f'{root} / 2'))
                        at = call.start('args') + shift.start()
                        edits.append((at, at + shift.end() - shift.start(), carrier))
                child = edit(source, edits)
                out.append((FAMILY, child))
                proto = re.search(rf'(?m)^(?:extern\s+)?(?P<t>s16|u16|s8|u8|short)\s+{re.escape(callee)}\s*\(', child)
                if proto:
                    out.append((FAMILY, child[:proto.start('t')] + 's32' + child[proto.end('t'):]))
                if len(out) >= LIMIT:
                    return out[:LIMIT]
    return out


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}
