"""Stack the target reserves that no local of the draft explains: a volatile scratch the original declared.

An N64 function's frame has the outgoing-argument area at the bottom, then its locals, then the registers it saves. When
the lowest saved register sits higher than the argument area, the difference is local storage, and a draft with no
stack locals reserves less (a 0x38 frame where the draft's was 0x30). The original often had a variable the compiler
kept in memory (a `volatile` scratch). The rewrite declares one of that size; the compiler and the judge decide. Only for
functions with no stack objects of their own: a draft that names `spXX` locals or a local array is left to the families
that size those.
"""
import re

from . import mips_stack, passthrough_argument_repairs
from .integer_repair_support import edit, view

FAMILY = 'unused_frame_padding'
DROP_FAMILY = 'unused_frame_padding_drop'
POSITIONED_FAMILY = 'inferred_frame_reservation'
SHRINK_FAMILY = 'unused_frame_padding_shrink'
FAMILIES = (FAMILY, DROP_FAMILY, SHRINK_FAMILY)
_SAVE = re.compile(r'\b(?:sw|sd|swc1|sdc1)\s+\$(?:s[0-8]|ra|fp|f2[0-9]|f3[01]|fs\d)\s*,\s*(0x[0-9a-fA-F]+|\d+)\(\$sp\)')
_ARGUMENT = re.compile(r'\b(?:sw|sd|swc1|sdc1|sh|sb)\s+\$\w+\s*,\s*(0x[0-9a-fA-F]+|\d+)\(\$sp\)')
_FRAME = re.compile(r'\baddiu\s+\$sp\s*,\s*\$sp\s*,\s*-(0x[0-9a-fA-F]+|\d+)')


def padding(asm):
    """Bytes of local storage the target's frame has between its argument area and its saved registers, or 0."""
    frame = _FRAME.search(asm or '')
    saves = [int(m[1], 0) for m in _SAVE.finditer(asm or '')]
    if not frame or not saves:
        return 0
    lowest = min(saves)
    arguments = 16 if re.search(r'\bjalr?\b', asm) else 0
    for match in _ARGUMENT.finditer(asm):
        offset = int(match[1], 0)
        if offset < lowest and offset + 4 > arguments:
            arguments = (offset + 4 + 7) // 8 * 8
    return lowest - arguments if lowest - arguments >= 4 else 0


def _declarations(size):
    if size % 8 == 0:
        return ['volatile u64 scratch;'] if size == 8 else ['volatile u64 scratch[%d];' % (size // 8)]
    return (['volatile u64 scratch;'] * (size // 8) + ['volatile s32 scratch_word;']) if size > 8 else ['volatile s32 scratch;']


def variants(source, name, asm):
    part = view(source, name)
    size = padding(asm)
    if not part or not size or size > 64:
        return []
    if re.search(r'\bsp[0-9A-Fa-f]+\b|\bvolatile\b|\bscratch\b', part.clean[part.opening:part.end]):
        return []
    lines = ''.join('\n    ' + declaration for declaration in _declarations(size))
    return [(FAMILY, edit(source, [(part.opening + 1, part.opening + 1, lines)]))]


def drop_variants(source, name):
    """Remove a `volatile` scratch nothing reads or writes: padding the draft's own locals have since made redundant.

    A scratch added to reserve frame stays in the best source after other locals (a header read into the stack, a
    byte buffer) grew to cover the same bytes, and while it is there every family that refuses `volatile` (the
    loop-weight scopes among them) is off. A KMC 2.7.2 function: the same source scored 49 with the scratch and 35
    without, with the frame word for word the target's. Only a declaration the rest of the function never names.
    """
    part = view(source, name)
    if not part:
        return []
    text = part.clean[part.opening:part.end]
    out = []
    for decl in re.finditer(r'(?m)^[ \t]*volatile[ \t]+(?:unsigned[ \t]+|signed[ \t]+)?(?:char|short|int|long|[su](?:8|16|32|64))[ \t]+(?P<n>[A-Za-z_]\w*)(?:\[[^\];]*\])?[ \t]*;[ \t]*\n', text):
        if len(re.findall(r'\b'+re.escape(decl['n'])+r'\b', text)) == 1:
            start = part.opening+decl.start()
            out.append((DROP_FAMILY, edit(source, [(start, start+len(decl.group(0)), '')])))
    return out[:2]


def shrink_variants(source, name):
    """A `volatile` scratch array nothing reads, declared with fewer elements: padding the draft's other locals half cover.

    Dropping the scratch (above) and growing it are the other two moves; when the frame is a few words too big, the
    scratch that reserved it is the part to shorten. A KMC 2.7.2 text-measuring function whose search loop had become
    the plain counted form kept a four-word scratch from the days it reserved the whole gap: the frame came out 0x50
    against the target's 0x48 (score 53), and with the array two words or one long it was the target's (30; three words
    and none were 53). Each smaller size is a proposal, one word at a time down to one; the judge picks. Only a
    declaration the rest of the function never names.
    """
    part = view(source, name)
    if not part:
        return []
    text = part.clean[part.opening:part.end]
    out = []
    for decl in re.finditer(r'(?m)^(?P<head>[ \t]*volatile[ \t]+(?:unsigned[ \t]+|signed[ \t]+)?(?:char|short|int|long|[su](?:8|16|32|64))[ \t]+(?P<n>[A-Za-z_]\w*)\[)(?P<size>\d+)(?P<tail>\][ \t]*;)', text):
        if len(re.findall(r'\b' + re.escape(decl['n']) + r'\b', text)) != 1 or int(decl['size']) < 2:
            continue
        start = part.opening + decl.start('size')
        for size in range(int(decl['size']) - 1, 0, -1):
            out.append((SHRINK_FAMILY, edit(source, [(start, start + len(decl['size']), str(size))])))
    return out[:4]


def forwarded_variants(source, name, header, rows, asm, frame_delta):
    """Compose one measured reservation and one missing incoming call argument."""
    if frame_delta <= 0 or sum(marker not in (' ', 's') for marker, _, _ in rows) != 1:
        return []
    frame_rows = [row if row[0] == 's' else (' ', row[1], row[1]) for row in rows]
    frame = mips_stack.repair_layout(frame_rows) or {}
    if (frame.get('inferred_growth') != frame_delta or frame.get('local_deltas')
            or padding(asm) != frame_delta):
        return []
    call_rows = [row if row[0] != 's' else (' ', row[1], row[1]) for row in rows]
    forwarded = passthrough_argument_repairs.shifted_call_variants(source, name, header, asm, call_rows)
    return [('frame_reservation_with_forwarded_argument', padded)
            for _, candidate in forwarded for _, padded in variants(candidate, name, asm)]


_LOCAL_DECLARATION = re.compile(r'[ \t]*(?:(?:unsigned|signed|const|register|static|struct|union)\s+)*[A-Za-z_]\w*'
                                r'(?:[ \t]+[A-Za-z_]\w*)*[ \t]+\**[ \t]*[A-Za-z_]\w*(?:\[[^\]\n;]*\])*[ \t]*(?:=[^;\n]*)?;')
_NOT_A_DECLARATION = re.compile(r'\s*(?:return|goto|break|continue|else|case|default|do|if|for|while|switch|typedef)\b')


def declaration_ends(part):
    """The offset just past each declaration of the function's leading declaration block, in order."""
    ends = []
    pos = part.opening + 1
    while pos < part.end - 1:
        while pos < part.end - 1 and part.clean[pos].isspace():
            pos += 1
        if _NOT_A_DECLARATION.match(part.clean, pos):
            break
        hit = _LOCAL_DECLARATION.match(part.clean, pos)
        if not hit:
            break
        ends.append(hit.end())
        pos = hit.end()
    return ends


def positioned_variants(source, name, frame_delta):
    """One or two unused word-sized locals, declared at each gap of the leading declaration block (IDO, GCC 2.x).

    A target frame bigger than the draft's by a few bytes that no named object explains is storage the original
    declared: IDO reserves a stack word for a local nothing reads, and the words sit between the locals the way the
    declarations did, so where the unused one is declared decides which spill slots and which arrays keep their
    offsets. `unused_frame_padding` only reaches a function with no locals of its own, and the measured growth
    placement puts one char array after every declaration; an IDO bit-stream reader with five stack arrays
    and three scalars needed one `s32` right after its last array, and the same word anywhere else left the saved
    registers' slots swapped (8 rows; the array's offsets were right either way). `frame_delta` is the target's frame
    minus the draft's, in bytes; the proposals try one word and then as many as it names, at the gaps after the
    arrays first (a local array is where the frame's size is decided), then every other gap. Proposals only.
    """
    part = view(source, name)
    if not part or not 4 <= frame_delta <= 32 or frame_delta % 4:
        return []
    fresh = '__repair_unused_frame'
    if re.search(r'\b(?:volatile|' + fresh + r')\w*\b', part.clean[part.opening:part.end]):
        return []
    ends = declaration_ends(part)
    if not ends:
        return []
    gaps = list(dict.fromkeys(ends + [part.opening + 1]))
    arrays = [end for end in ends if re.search(r'\]\s*;$', part.clean[:end])]
    arrays.reverse()  # the last array first: its offset is where the next local's slot begins
    order = arrays + [gap for gap in gaps if gap not in arrays]
    words = frame_delta // 4
    result = []
    for count in dict.fromkeys((1, words)):
        for gap in order[:8]:
            lines = ''.join(f'\n    s32 {fresh}_{index};' for index in range(count))
            result.append((POSITIONED_FAMILY, edit(source, [(gap, gap, lines)])))
    return result[:12]
