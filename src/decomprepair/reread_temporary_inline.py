"""A value m2c kept in a local ahead of the calls it is multiplied by, written whole at each read.

m2c names a term the compiler computed once and kept, and writes it ahead of the call it was computed after:

    speed = ((u32) (raw & 0xFFFF) >> 8) + 0x266;      out->x = (sine(angle) * (s32) (((raw ...) >> 8) + 0x266)) >> 9;
    out->x = (sine(angle) * speed) >> 9;          ->  out->y = (cosine(angle) * (s32) (((raw ...) >> 8) + 0x266)) >> 9;
    out->y = (cosine(angle) * speed) >> 9;

The operands are evaluated left to right, so written inline the call comes first and the arithmetic after it, and the
compiler's value reuse keeps one result for the second read. A local set ahead computes it before the call instead.
On a 111-instruction N64 object initialiser (SN64 GCC, `-O2 -mips3`) the two arms' temporaries were such a placement
(480 -> 0 with the other steps of the chain in). The left-to-right reading is a hypothesis the measurement agrees with;
the judge decides each child.

`accumulated_temporary_inline` takes only a value built up over two or more statements, and `single_use_inline` only a
value read once. `reread_temporary_inline` takes a plain integer local set by one statement and read two or more times
later in the same block with a call between the set and the last read, whose value reads only literals and integer
locals or parameters that nothing assigns or takes the address of from there on. Every such local at once first (each
arm often has its own), then each alone. `variants` returns [(family, source)]."""
import re

from .accumulated_temporary_inline import _NARROW, _STATEMENT, _TYPE_WORDS, _assigned, _block_end, _plain
from .integer_repair_support import DECL, IDENT, INTEGER, edit, locals_for, refs, view

FAMILY = 'reread_temporary_inline'
FAMILIES = (FAMILY,)
LIMIT = 6
_CALL = re.compile(r'\b(?!(?:if|while|for|switch|return|sizeof)\b)[A-Za-z_]\w*\s*\(')


def _sites(source, name):
    """(local, child with that local's value written at each read) for each qualifying local."""
    part = view(source, name)
    if not part or re.search(r'\b(?:volatile|asm|__asm__)\b', part.body):
        return []
    clean = part.clean
    declared = {decl['name']: decl for decl in locals_for(part)}
    header = clean[max(clean.rfind(';', 0, part.opening), clean.rfind('}', 0, part.opening)) + 1:part.opening]
    parameters = {hit[1] for hit in re.finditer(rf'\b{INTEGER}\s+({IDENT})\s*(?=[,)])', header)
                  if not re.search(rf'&\s*{hit[1]}\b', part.body)}
    operands = set(declared) | parameters
    result = []
    for local, decl in declared.items():
        mentions = refs(part, decl)
        if len(mentions) < 3:
            continue
        first = mentions[0].start()
        if clean[part.opening:first].rstrip()[-1:] not in (';', '{', '}'):
            continue
        found = re.compile(_STATEMENT).match(clean, first)
        if not found or found[1] != local or found[2]:
            continue
        position = found.end()
        block_end = _block_end(part, first)
        reads = mentions[1:]
        if block_end is None or reads[0].start() < position or reads[-1].start() >= block_end:
            continue
        between = clean[position:reads[-1].start()]
        if (not _CALL.search(between) or _assigned(local, clean[position:block_end])
                or re.search(rf'(?<![?\w]){IDENT}\s*:(?!:)\s*(?!\s*\d)', re.sub(r'\?[^;]*:', '', between))):
            continue
        value = source[found.start(3):found.end(3)].strip()
        bare = clean[found.start(3):found.end(3)].strip()
        if re.fullmatch(r'-?\w+', bare) or not _plain(bare, operands - {local}):
            continue
        used = set(re.findall(r'(?<!\w)[A-Za-z_]\w*', value)) - _TYPE_WORDS
        if any(_assigned(word, clean[position:block_end]) for word in used):
            continue
        kind = ' '.join(decl['type'].split())
        spelled = f'(({kind}) ({value}))'
        if _NARROW.fullmatch(kind):  # read as the local holds it: promoted from the narrow type
            spelled = f'((s32) {spelled})'
        start = found.start(1)
        while start > 0 and source[start - 1] in ' \t':
            start -= 1
        end = position
        if (start == 0 or source[start - 1] == '\n') and source[end:end + 1] == '\n':
            end += 1
        edits = [(start, end, '')] + [(hit.start(), hit.end(), spelled) for hit in reads]
        line = DECL.match(source, decl.start())
        if line:
            begin = source.rfind('\n', 0, line.start()) + 1
            if not source[begin:line.start()].strip() and source[line.end():line.end() + 1] == '\n':
                edits.append((begin, line.end() + 1, ''))
        result.append((local, edit(source, edits)))
    return result


def variants(source, name):
    sites = _sites(source, name)
    children = []
    if len(sites) > 1:
        combined, done = source, set()
        while True:  # one local at a time on the child so far: the offsets move with each edit
            left = [(local, child) for local, child in _sites(combined, name) if local not in done]
            if not left:
                break
            done.add(left[0][0])
            combined = left[0][1]
        children.append(combined)
    children += [child for _, child in sites]
    return [(FAMILY, child) for child in dict.fromkeys(children) if child != source][:LIMIT]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}  # registry.py
