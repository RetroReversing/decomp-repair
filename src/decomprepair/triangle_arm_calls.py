"""A triangle's three vertex addresses built in the arms of a halfword-or-byte index test, each arm calling.

m2c writes the call that takes a triangle's vertices once, after an `if`/`else` that picks the halfword or the byte
index triple, and keeps the pieces in three temporaries: `a1 = verts + t[0] * 0xC; a2 = t[1] * 3; v0 = t[2];` and then
`call(plane, a1, verts + a2 * 4, verts + v0 * 0xC)`, the integer vertex base cast away from its `f32 *`. The target of an
851-instruction N64 ray test (KMC GCC 2.7.2, `-G0 -mips3 -mgp32 -mfp32 -O2`) has the arms of the original: in each arm a
pointer to the triangle's three indices, then the call with `verts + tri[k] * 3` for the three vertices (the vertex
array a `f32 *`, three floats a vertex), and gcc's cross-jumping merges the identical tails of the two arms. The mini
function written that way compiled to the target's instruction sequence in the arm and the tail exactly; in the whole
function the three sites went 4053 -> 3728 -> 1323 in the isolated judge (the first alone, then the two room sites),
every row of the first site equal, branch offsets included. m2c's temporaries made the second scheduler order the loads
and shifts differently (the t[1] load first). Hypothesis, not confirmed in the compiler source: the shared tail after the
join is scheduled as its own block, the arms' ends as another.

`triangle_arm_calls` rewrites that shape: the `if (c) { u16 triple } else { u8 triple }` followed by the call (or with
the call repeated in each arm, as an earlier search left it) into `if (c) { u16 *tri = (u16 *)tris + i * 3; call(plane,
(s32)(verts + tri[0] * 3), ...); } else { u8 *tri = (u8 *)tris + i * 3; call(...); }`, where `verts` is the vertex-base
read retyped `f32 **` and the call's arguments keep their integer type through a cast. One child for every site together
(they only matched together), then one per site. The judge decides.
"""

import re

from .integer_repair_support import IDENT, edit, view

FAMILY = 'triangle_arm_calls'
FAMILIES = (FAMILY,)
LIMIT = 4
ARMS = re.compile(r'if\s*\((?P<cond>[^{};]*)\)\s*\{(?P<half>[^{}]*)\}\s*else\s*\{(?P<byte>[^{}]*)\}(?P<after>\s*[^;{}]*;)?', re.S)
CALL = re.compile(rf'\s*(?P<call>{IDENT})\s*\((?P<plane>[^;]*?),\s*(?P<c1>{IDENT})\s*,\s*M2C_FIELD\((?P<obj>{IDENT}),\s*s32\s*\*,\s*0x34\)\s*\+\s*\(\s*(?P<c2>{IDENT})\s*\*\s*4\s*\)\s*,'
                  rf'\s*M2C_FIELD\((?P=obj),\s*s32\s*\*,\s*0x34\)\s*\+\s*\(\s*(?P<c3>{IDENT})\s*\*\s*0xC\s*\)\s*\)\s*;?\s*$', re.S)


def _arm(body, ctype, width, stride):
    """What one arm computes: its triple's address (tris, index), the object whose vertices it adds, the names holding the three
    pieces, and its call if it has one; None for any other statements."""
    triple = fields = None
    names, call, tmp = {}, None, None
    for text in (piece.strip() for piece in body.split(';')):
        if not text:
            continue
        found = re.fullmatch(rf'(?P<name>{IDENT})\s*=\s*(?P<tris>.+?)\s*\+\s*\(\s*(?P<idx>{IDENT})\s*\*\s*{stride}\s*\)', text, re.S)
        if found and 'M2C_FIELD' in found['tris'] and not tmp:
            tmp = found
            continue
        piece = re.fullmatch(rf'(?P<name>{IDENT})\s*=\s*(?:\(\s*u16\s*\)\s*)?(?P<rhs>.+)', text, re.S)
        if piece:
            rhs = piece['rhs']
            reads = re.fullmatch(rf'M2C_FIELD\((?P<obj>{IDENT}),\s*s32\s*\*,\s*0x34\)\s*\+\s*\(\s*M2C_FIELD\((?P<at>.+),\s*{ctype}\s*\*,\s*0\)\s*\*\s*0xC\s*\)', rhs, re.S)
            if reads:
                names['a1'], fields = piece['name'], (reads['obj'], reads['at'].strip())
                continue
            reads = re.fullmatch(rf'M2C_FIELD\((?P<at>.+),\s*{ctype}\s*\*,\s*{width}\)\s*\*\s*3', rhs, re.S)
            if reads:
                names['a2'] = piece['name']
                names['at2'] = reads['at'].strip()
                continue
            reads = re.fullmatch(rf'M2C_FIELD\((?P<at>.+),\s*{ctype}\s*\*,\s*{2 * width}\)', rhs, re.S)
            if reads:
                names['v0'] = piece['name']
                names['at3'] = reads['at'].strip()
                continue
        wrapped = CALL.fullmatch(text + ';') or CALL.fullmatch(text)
        if wrapped and call is None:
            call = wrapped
            continue
        return None
    if fields is None or not {'a1', 'a2', 'v0'} <= set(names) or not len({fields[1], names['at2'], names['at3']}) == 1:
        return None
    at = fields[1]
    if tmp:
        if at != tmp['name']:
            return None
        triple = (tmp['tris'].strip(), tmp['idx'])
    else:
        inline = re.fullmatch(rf'\(\s*(?P<tris>.+?)\s*\+\s*\(\s*(?P<idx>{IDENT})\s*\*\s*{stride}\s*\)\s*\)', at, re.S)
        if not inline:
            return None
        triple = (inline['tris'].strip(), inline['idx'])
    return {'triple': triple, 'obj': fields[0], 'names': (names['a1'], names['a2'], names['v0']), 'call': call}


def _call(match, names, obj):
    """The call's callee and plane argument when it takes exactly the three pieces an arm built."""
    if not match or (match['c1'], match['c2'], match['c3']) != names or match['obj'] != obj:
        return None
    return match['call'], match['plane'].strip()


def variants(source, name):
    part = view(source, name)
    if not part or re.search(r'\b(?:volatile|asm|__asm__)\b|^\s*#', part.body, re.M) or '__tri' in part.body:
        return []
    clean = part.clean
    sites = []
    for hit in ARMS.finditer(clean, part.opening, part.end):
        half, byte = _arm(hit['half'], 'u16', 2, 6), _arm(hit['byte'], 'u8', 1, 3)
        if not half or not byte or half['triple'][1] != byte['triple'][1] or half['obj'] != byte['obj'] or half['names'] != byte['names']:
            continue
        if half['call'] or byte['call']:
            # the call repeated in each arm (an earlier search's shape) with nothing shared after the arms
            calls = [_call(arm['call'], arm['names'], arm['obj']) for arm in (half, byte)]
            if None in calls or calls[0] != calls[1]:
                continue
            (callee, plane), end = calls[0], hit.end('byte') + 1
        else:
            shared = CALL.fullmatch(hit['after'] or '')
            found = _call(shared, half['names'], half['obj'])
            if not found:
                continue
            (callee, plane), end = found, hit.end()
        sites.append((hit.start(), end, hit['cond'], half, byte, callee, plane))
    if not sites:
        return []

    def rewrite(group):
        edits = []
        for start, end, cond, half, byte, callee, plane in group:
            indent = re.match(r'[ \t]*', source[source.rfind('\n', 0, start) + 1:])[0]
            verts = f'M2C_FIELD({half["obj"]}, f32 **, 0x34)'
            call = f'{callee}({plane}, ' + ', '.join(f'(s32)({verts} + tri[{k}] * 3)' for k in range(3)) + ');'
            text = (f'if ({cond.strip()}) {{\n'
                    f'{indent}    u16 *tri = (u16 *){half["triple"][0]} + {half["triple"][1]} * 3;\n{indent}    {call}\n'
                    f'{indent}}} else {{\n'
                    f'{indent}    u8 *tri = (u8 *){byte["triple"][0]} + {byte["triple"][1]} * 3;\n{indent}    {call}\n'
                    f'{indent}}}')
            edits.append((start, end, text))
        return edit(source, edits)

    found = []
    if len(sites) > 1:
        found.append((FAMILY, rewrite(sites)))
    for site in sites[:LIMIT]:
        found.append((FAMILY, rewrite([site])))
    return found
