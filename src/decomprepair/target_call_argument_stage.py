"""Stage a nested halfword call result and a late memory argument together.

A MIPS target calls a helper, keeps its result for a halfword argument, and
prepares a later stack argument before the final call. A draft nested both in
that final call. Staging the helper result in an s16 and reusing a dead s32
local for the memory argument changed one KMC score from 675 to 350. The
target establishes the call and argument preparation order; the candidate
may change a draft with side effects and is a target-guided correction.
"""
import re

from .case_temporary_repairs import DECLARATION, _depth_at
from .integer_repair_support import IDENT, edit, split_args, view
from .pattern_repairs import close

FAMILY = 'target_call_argument_stage'
FAMILIES = (FAMILY,)
LIMIT = 24


def _witness(asm, outer):
    lines = [re.sub(r'\s+', ' ', re.sub(r'/\*.*?\*/', '', row).strip()) for row in (asm or '').splitlines()]
    for i, row in enumerate(lines):
        if not re.fullmatch(r'(?i:jal) ' + re.escape(outer), row):
            continue
        before = lines[max(0, i - 14):i]
        after = lines[i + 1:i + 3]
        if (any(re.fullmatch(r'(?i:sll) \$v0,\s*\$v0,\s*(?:0x10|16)', x) for x in before)
                and any(re.fullmatch(r'(?i:sw) \$\w+,\s*(?:0x18|24)\(\$sp\)', x) for x in before)
                and any(re.fullmatch(r'(?i:sra) \$a3,\s*\$v0,\s*(?:0x10|16)', x) for x in after)):
            return True
    return False


def variants(source, name, asm, header=''):
    part = view(source, name)
    if not part or re.search(r'\b(?:volatile|goto|asm|__asm__)\b', part.clean[part.opening:part.end]):
        return []
    context = source + '\n' + (header or '')
    if re.search(r'(?m)^\s*#\s*(?:define|undef)\s+(?:s16|s32|note_vol)\b|\btypedef\b[^;]*\bvolatile\b[^;]*\b(?:s16|s32)\s*;', context):
        return []
    declarations = [d for d in DECLARATION.finditer(part.clean, part.opening + 1, part.end)
                    if _depth_at(part.clean, part.opening + 1, d.start()) == 0 and d['type'].strip() == 's32']
    result = []
    pan = re.compile(r'(?m)^(?P<indent>[ \t]*)(?P<var>' + IDENT + r')\s*=\s*' + IDENT + r'\s*\([^;{}]*\)\s*;')
    for match in pan.finditer(part.clean, part.opening + 1, part.end):
        if re.search(r'\b(?:for|while|do)\b', part.clean[part.opening:match.start()]):
            continue
        call = re.match(r'\s*(' + IDENT + r')\s*\(', part.clean[match.end():part.end])
        if not call or not _witness(asm, call[1]):
            continue
        call_start = match.end() + call.start(1)
        opening = match.end() + call.end() - 1
        stop = close(part.clean, opening)
        semi = re.match(r'\s*;', part.clean[stop:]) if stop else None
        if not stop or not semi:
            continue
        spans = split_args(part.clean[opening + 1:stop - 1])
        if len(spans) != 7:
            continue
        args = [source[opening + 1 + a:opening + 1 + b].strip() for a, b in spans]
        if not re.fullmatch(IDENT + r'\s*\(\s*' + IDENT + r'\s*,\s*' + IDENT + r'\s*\)', args[3]):
            continue
        if not re.search(r'\b' + re.escape(match['var']) + r'\b', args[4]) or not args[6].startswith('M2C_FIELD('):
            continue
        if re.search(r'\+\+|--|(?<![=!<>])=(?!=)', args[6]):
            continue
        pan_decl = next((d for d in declarations if d['name'] == match['var']), None)
        if not pan_decl or re.search(r'\bnote_vol\b', part.clean[part.opening:part.end]):
            continue
        for carrier in declarations:
            var = carrier['name']
            if any(re.search(r'\b' + re.escape(var) + r'\b', arg) for arg in args):
                continue
            if var == match['var'] or not re.search(r'\b' + re.escape(var) + r'\s*=(?!=)', part.clean[part.opening:match.start()]):
                continue
            if re.search(r'\b' + re.escape(var) + r'\b', part.clean[stop + semi.end():part.end]):
                continue
            if re.search(r'&\s*' + re.escape(var) + r'\b', part.clean[part.opening:part.end]):
                continue
            updated = args[:]
            updated[3], updated[6] = 'note_vol', var
            line = (f'note_vol = {args[3]}; {var} = {args[6]};\n{match["indent"]}'
                    f'{call[1]}(' + ', '.join(updated) + ');')
            result.append((FAMILY, edit(source, [(pan_decl.end(), pan_decl.end(), '    s16 note_vol;\n'),
                                                  (call_start, stop + semi.end(), line)])))
            if len(result) >= LIMIT:
                return result
    return result


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'asm', 'header'), 'archs': ('mips',), 'order': 40}
