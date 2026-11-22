"""Stage the two source coordinates of a measured fixed-point update."""
import re

from .csource import _blank
from .integer_repair_support import IDENT, edit, integer, view
from .large_stack_drafts import _shape
from .mips import normalized_integer_lines
from .pattern_repairs import close

FAMILY = 'measured_coordinate_staging'
FAMILIES = (FAMILY,)

BLOCK = _shape('''
    @origin = M2C_FIELD(M2C_FIELD(&@state, void **, @stateoff), void **, @originoff);
    @coordy = M2C_FIELD(@origin, u16 *, @origy);
    @coordx = (s16) M2C_FIELD(@origin, u16 *, @origx) / 2;
    M2C_FIELD(@dst, u16 *, @dstx) = (u16) (@coordx + ((s32) ((s16) (@coordx - M2C_FIELD(@src, u16 *, @srcx)) * @factor) >> @shift));
    @valuey = (s32) ((s16) @coordy + ((u32) (@coordy << @leftshift) >> @rightshift)) >> 1;
    @object = M2C_FIELD(@dst, void **, @objectoff);
    @result = @valuey + ((s32) ((s16) (@valuey - M2C_FIELD(@src, u16 *, @srcy)) * @factor) >> @shift);
    M2C_FIELD(@dst, s16 *, @dsty) = @result;
''', numbers=('stateoff', 'originoff', 'origy', 'origx', 'dstx', 'srcx', 'factor', 'shift', 'leftshift',
              'rightshift', 'objectoff', 'srcy', 'dsty'))
BLOCK = re.compile(BLOCK.pattern.replace(r'\ ', r'\s+'))


def variants(source, name, header, rows):
    part = view(source, name)
    if not part:
        return []
    end = close(part.clean, part.opening, '{', '}')
    if not end or re.search(r'/\*|//|(?m:^\s*#)', source[part.opening + 1:end - 1]):
        return []
    body = part.clean[part.opening + 1:end - 1]
    matches = list(BLOCK.finditer(body))
    if len(matches) != 1:
        return []
    m = matches[0]
    if body[:m.start()].rstrip()[-1:] not in (';', '{', '}'):
        return []
    signature = re.search(r'\bvoid\s+' + re.escape(name) + r'\s*\(\s*void\s*\*\s*' + re.escape(m['src'])
                          + r'\s*,\s*void\s*\*\s*' + re.escape(m['dst']) + r'\s*\)\s*$',
                          part.clean[:part.opening])
    roles = [m[k] for k in ('origin', 'state', 'coordy', 'coordx', 'dst', 'src', 'valuey', 'object', 'result')]
    if not signature or len(set(roles)) != len(roles):
        return []
    decl = re.compile(r'(?m)^[ \t]*(?P<type>u16|int)\s+' + re.escape(m['coordy']) + r'\s*;')
    decls = list(decl.finditer(body[:m.start()]))
    if len(decls) != 1 or re.search(r'\b' + re.escape(m['coordy']) + r'\b', body[m.end():]):
        return []
    # Only the declared local and the measured assignment and expression uses are allowed.
    if len(re.findall(r'\b' + re.escape(m['coordy']) + r'\b', body)) != 4:
        return []
    offsets = {key: integer(m[key]) for key in ('originoff', 'origy', 'origx', 'srcx', 'srcy', 'dstx', 'dsty', 'objectoff')}
    if any(not 0 <= value <= 32767 for value in offsets.values()) or offsets['srcx'] == offsets['srcy']:
        return []
    target = '\n'.join(normalized_integer_lines(left for _, left, _ in rows if left))
    first = (rf'lw \$a3, {offsets["originoff"]}\(\$t2\)\n'
             rf'lhu \$v1, {offsets["srcx"]}\(\$a0\)\n'
             rf'lhu \$v0, {offsets["origx"]}\(\$a3\)\n'
             rf'lhu \$a0, {offsets["srcy"]}\(\$a0\)\n'
             rf'lhu \$a3, {offsets["origy"]}\(\$a3\)')
    if not re.search(first, target) or not re.search(
            rf'lw \$a3, {offsets["objectoff"]}\(\$a1\)\nsra \$v0, \$v0, {integer(m["shift"])}', target):
        return []
    context = _blank(header + '\n' + source)
    macros = set(re.findall(r'(?m)^\s*#\s*(?:define|undef)\s+(' + IDENT + r')', context))
    types = ('s8', 'u8', 's16', 'u16', 's32', 'u32')
    if (macros.intersection(roles + list(types) + ['__repair_srcy']) or re.search(
            r'\b__repair_srcy\b|(?m:^\s*#\s*undef\s+M2C_FIELD\b)', context)):
        return []
    for typ, expected in [('s8', r'(?:signed\s+)?char'), ('s16', r'(?:signed\s+)?short(?:\s+int)?'),
                          ('u16', r'unsigned\s+short(?:\s+int)?'), ('s32', r'(?:signed\s+)?int'),
                          ('u32', r'unsigned\s+int')]:
        aliases = re.findall(r'\btypedef\s+([^;{}]+?)\s+' + typ + r'\s*;', context)
        if len(aliases) != 1 or not re.fullmatch(expected, aliases[0].strip()):
            return []
    macro = re.findall(r'(?m)^\s*#\s*define\s+M2C_FIELD\(expr,\s*type_ptr,\s*offset\)\s+([^\n]+)', context)
    if len(macro) != 1 or re.sub(r'\s+', '', macro[0]) != '(*(type_ptr)((s8*)(expr)+(offset)))':
        return []
    origin, cy, cx, dst, src, vy, obj, result = (m[k] for k in
                                                  ('origin', 'coordy', 'coordx', 'dst', 'src', 'valuey', 'object', 'result'))
    block = f'''{origin} = M2C_FIELD(M2C_FIELD(&{m['state']}, void **, {m['stateoff']}), void **, {m['originoff']});
    {cx} = (s16) M2C_FIELD({origin}, u16 *, {m['origx']}) / 2;
    {cy} = M2C_FIELD({origin}, u16 *, {m['origy']});
    __repair_srcy = M2C_FIELD({src}, u16 *, {m['srcy']});
    M2C_FIELD({dst}, u16 *, {m['dstx']}) = (u16) ({cx} + ((s32) ((s16) ({cx} - M2C_FIELD({src}, u16 *, {m['srcx']})) * {m['factor']}) >> {m['shift']}));
    {vy} = (s32) ((s16) {cy} + ((u32) ({cy} << {m['leftshift']}) >> {m['rightshift']})) >> 1;
    {result} = {vy} + ((s32) ((s16) ({vy} - __repair_srcy) * {m['factor']}) >> {m['shift']});
    {obj} = M2C_FIELD({dst}, void **, {m['objectoff']});
    M2C_FIELD({dst}, s16 *, {m['dsty']}) = {result};'''
    offset = part.opening + 1
    changes = [(offset, offset, '\n    u16 __repair_srcy;'), (offset + m.start(), offset + m.end(), block)]
    if decls[0]['type'] == 'u16':
        changes.append((offset + decls[0].start('type'), offset + decls[0].end('type'), 'int'))
    return [(FAMILY, edit(source, changes))]
