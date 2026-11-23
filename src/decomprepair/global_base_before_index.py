"""A global base pointer read into a local ahead of the index statement that is added to it.

`off = arg * K; ... G + off ... call(..., G + off + C);` with `G` a global pointer: the first scheduler places the
load of `G` by priority and, on a tie, by the order the source reads things in. The index chain (`sll/addu` steps)
written first starts first and the load of `G` lands several insns into it, and the sum is `off + G` where the target
has `G + off`: five or so rows of order and one operand swap, none of which any spelling of the expression moves
(`off + G`, `(char *) G + off`, the index inlined, `off` assigned inside the sum, the statements permuted). A local
read from `G` just before the index statement, `base = G;`, and used for the reads up to the next call puts the load
first and the sum in the target's operand order.

The case (KMC GCC 2.7.2, `-O2 -G0 -mips3`): the end of a 218-instruction object-matrix function; `off = arg0 * 0xD4`,
a halfword read at `G + off + 0x96`, then `off += 0x14` and the argument `G + off + 0x88` of a call, a third read of
`G` after that call (it stays: the call may change `G`). After `pointer_sum_cse_barrier` the function stood at 120 with
only that order and operand row left; the base local written before the index statement was 0. The local written
after the index statement, or the statements permuted, stayed at 120; the index inlined into the sum at 5 with the
operand swapped. The scheduler reading (sched.c's tie on the original order of insns) is a hypothesis; the judge
decides each child.

The child (`global_base_before_index`, one per index statement and global, bounded) declares `T base_G;` at the head of
the function, inserts `base_G = G;` before the index statement `I = X * K;` and writes `base_G` for `G` in every `G + I`
or `I + G` up to and including the first statement that calls something, when:
- `G` is a pointer declared `extern T *G;` in the source or the header (not volatile, not an array), `I` a local
  assigned a product or a shift (`*` or `<<`) that does not mention `G`;
- `G + I` (or `I + G`) is read at least twice before that call, and `G` is not assigned before it.
"""
import re

from .csource import _blank, find
from .reassigned_local_inline import IDENT

FAMILY = 'global_base_before_index'
FAMILIES = (FAMILY,)
LIMIT = 6
EXTERN = re.compile(rf'(?:^|[;}}\n])\s*extern\s+(?P<type>(?:const\s+)?[A-Za-z_][\w\s]*?\s*\*+)\s*(?P<name>{IDENT})\s*;')
CALL = re.compile(rf'(?<![\w)\]>.])(?!(?:if|while|for|switch|return|sizeof)\b)({IDENT})\s*\(')


def _pointers(text):
    found = {}
    for hit in EXTERN.finditer(text):
        if 'volatile' not in hit['type']:
            found.setdefault(hit['name'], re.sub(r'\s+', ' ', hit['type']).strip())
    return found


def variants(source, name, header=''):
    clean = _blank(source)
    span = find(source, name)
    if not span:
        return []
    start, end = span
    opening = clean.find('{', start, end)
    if opening < 0:
        return []
    pointers = _pointers(_blank(header or '') + '\n' + clean[:start])
    if not pointers:
        return []
    result = []
    for index in re.finditer(rf'(?<![\w.>*])(?P<i>{IDENT})\s*=(?!=)\s*(?P<rhs>[^;{{}}]*(?:\*|<<)[^;{{}}]*);', clean[opening:end]):
        at = opening + index.start()
        var, rhs = index['i'], index['rhs']
        tail_start = opening + index.end()
        # the run after the index statement, up to the end of the first statement that calls something
        run_end = end
        position = tail_start
        while position < end:
            stop = clean.find(';', position)
            if stop < 0:
                break
            if CALL.search(clean, position, stop):
                run_end = stop + 1
                break
            position = stop + 1
        run = clean[tail_start:run_end]
        for glob, typ in pointers.items():
            if re.search(rf'\b{glob}\b', rhs) or glob in ('NULL',):
                continue
            if re.search(rf'(?<![\w.>*&]){glob}\s*=(?!=)', run) or re.search(rf'\b{glob}\s*(?:\+\+|--)', run):
                continue
            uses = list(re.finditer(rf'(?<![\w.>]){glob}\b\s*\+\s*\b{var}\b|(?<![\w.>])\b{var}\b\s*\+\s*{glob}\b', run))
            if len(uses) < 2:
                continue
            base = f'{glob}_base'
            if re.search(rf'\b{base}\b', clean):
                continue
            body = source[tail_start:run_end]
            body = re.sub(rf'(?<![\w.>]){glob}\b(?=\s*\+\s*\b{var}\b)', base, body)
            body = re.sub(rf'(\b{var}\b\s*\+\s*){glob}\b', rf'\g<1>{base}', body)
            line_start = max(source.rfind(';', 0, at), source.rfind('{', 0, at), source.rfind('}', 0, at)) + 1
            first = line_start + len(re.match(r'\s*', source[line_start:]).group())
            head = source[:first] + f'{base} = {glob}; ' + source[first:tail_start]
            declare = opening + 1
            text = head[:declare] + f' {typ} {base};' + head[declare:] + body + source[run_end:]
            if text != source and text not in result:
                result.append(text)
    return [(FAMILY, text) for text in result[:LIMIT]]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'header'), 'order': 71}  # the registry: no caller wiring (registry.py)
