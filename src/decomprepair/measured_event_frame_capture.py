"""Stage an early count and reserve the measured stack event space."""

import re

from .integer_repair_support import IDENT, edit, view
from .mips import normalized_integer_lines
from .pattern_repairs import close

_TARGET = re.compile(
    r'lw \$v1, \(\$s0\)\nmove \$s1, \$a0\naddiu \$v0, \$zero, -1\n'
    r'sw \$v0, 60\(\$s1\)\naddiu \$v0, \$zero, 16000\n'
    r'sw \$v0, 72\(\$s1\)\nsw \$v1, 68\(\$s1\)'
)
_INIT = re.compile(
    rf'(?P<first>M2C_FIELD\((?P<dst>{IDENT}), s32 \*, 0x3C\)\s*=\s*-1\s*;)\s*'
    rf'(?P<count>M2C_FIELD\((?P=dst), u32 \*, 0x44\)\s*=\s*\(u32\)\s*'
    rf'M2C_FIELD\((?P<src>{IDENT}), u32 \*, 0\)\s*;)\s*'
    rf'(?P<third>M2C_FIELD\((?P=dst), s32 \*, 0x48\)\s*=\s*0x3[Ee]80\s*;)'
)


def variants(source, name, header, rows):
    if not 60 <= len(rows) <= 100:
        return []
    target = '\n'.join(normalized_integer_lines(left for _, left, _ in rows if left))
    candidate = '\n'.join(normalized_integer_lines(right for _, _, right in rows if right))
    if (not _TARGET.search(target) or 'addiu $sp, $sp, -64' not in target
            or 'addiu $sp, $sp, -48' not in candidate
            or 'sh $v0, 24($sp)' not in target or 'addiu $a1, $sp, 24' not in target):
        return []
    part = view(source, name)
    end = close(part.clean, part.opening, '{', '}') if part else None
    if not end or re.search(r'\b(?:volatile|asm|__asm__|__LINE__|__repair_count)\b', part.clean):
        return []
    part.end = end
    hits = list(_INIT.finditer(part.body))
    if len(hits) != 1:
        return []
    hit = hits[0]
    if (hit['dst'] == hit['src']
            or not re.search(rf'\bvoid\s+{re.escape(name)}\s*\(void\s*\*\s*{re.escape(hit["dst"])}\s*,'
                             rf'\s*void\s*\*\s*{re.escape(hit["src"])}\s*\)\s*$', part.clean[:part.opening])
            or re.search(r'\b__repair_count\b', header)):
        return []
    decls = list(re.finditer(rf'\bs16\s+(?P<event>{IDENT})\s*;', part.body))
    if len(decls) != 1:
        return []
    decl, event = decls[0], decls[0]['event']
    init = list(re.finditer(rf'\b{re.escape(event)}\s*=\s*5\s*;', part.body))
    address = list(re.finditer(rf'&\s*{re.escape(event)}\b', part.body))
    if len(init) != 1 or len(address) != 1 or len(re.findall(rf'\b{re.escape(event)}\b', part.body)) != 3:
        return []
    # The target frame only proves reserved bytes, not the event's full type.
    # Nine halfwords is the smallest measured extent that produces its frame.
    original = source[part.opening + 1:part.end - 1]
    if '/*' in original or '//' in original or '#' in original:
        return []
    start = part.opening + 1
    replacement = (f'__repair_count = M2C_FIELD({hit["src"]}, u32 *, 0);\n    '
                   f'{hit["first"]}\n    {hit["third"]}\n    '
                   f'M2C_FIELD({hit["dst"]}, u32 *, 0x44) = __repair_count;')
    fixed = edit(source, [(start, start, '\n    u32 __repair_count;'),
                          (start + hit.start(), start + hit.end(), replacement),
                          (start + decl.start(), start + decl.end(), f's16 {event}[9];'),
                          (start + init[0].start(), start + init[0].end(), f'{event}[0] = 5;'),
                          (start + address[0].start(), start + address[0].end(), f'&{event}[0]')])
    return [('measured_event_frame_capture', fixed)]
