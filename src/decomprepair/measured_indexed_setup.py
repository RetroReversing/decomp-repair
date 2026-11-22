"""Stage a signed-index table read and the two bases of a measured setup block."""
import re

from .csource import _blank
from .integer_repair_support import IDENT, edit, integer, view
from .large_stack_drafts import _shape
from .mips import normalized_integer_lines
from .pattern_repairs import close

FAMILY = 'measured_indexed_setup'
FAMILIES = (FAMILY,)

BODY = _shape('''
    if (M2C_FIELD(M2C_FIELD(&@state, void **, @headoff), s16 *, @kindoff) == @kind) {
        @read(M2C_FIELD((M2C_FIELD(&@state, s32 *, @tableoff) + M2C_FIELD(@global, s8 *, @indexoff)), u8 *, @byteoff));
        @call();
    }
    @reset(@firstarg, @secondarg);
    M2C_FIELD(@global, s8 *, @firstoff) = 0;
    M2C_FIELD(@global, M2C_UNK **, @pointeroneoff) = &@pointerone;
    M2C_FIELD(@global, M2C_UNK **, @pointertwooff) = &@pointertwo;
    M2C_FIELD(@global, s8 *, @lastoff) = 0;
    return 0;
''', numbers=('headoff', 'kindoff', 'kind', 'tableoff', 'indexoff', 'byteoff', 'firstoff',
              'pointeroneoff', 'pointertwooff', 'lastoff'))


def variants(source, name, header, rows, flags, resolve):
    flags = set(flags or ())
    if not resolve or not flags.intersection({'-mgp32', '-mabi=32'}) or flags.intersection(
            {'-m64', '-mgp64', '-mabi=64', '-mabi=n32', '-mabi=eabi'}):
        return []
    part = view(source, name)
    if not part:
        return []
    end = close(part.clean, part.opening, '{', '}')
    if not end or re.search(r'/\*|//|(?m:^\s*#)', source[part.opening + 1:end - 1]):
        return []
    m = BODY.fullmatch(' '.join(part.clean[part.opening + 1:end - 1].split()))
    signature = (re.search(r'\bs32\s+' + re.escape(name) + r'\s*\(\s*s32\s+' + re.escape(m['firstarg'])
                           + r'\s*,\s*M2C_UNK\s+' + re.escape(m['secondarg']) + r'\s*\)\s*$',
                           part.clean[:part.opening]) if m else None)
    if not signature:
        return []
    roles = ('state', 'global', 'read', 'call', 'reset', 'firstarg', 'secondarg', 'pointerone', 'pointertwo')
    names = [m[k] for k in roles]
    if len(set(names)) != len(names):
        return []
    values = {key: integer(m[key]) for key in ('kindoff', 'indexoff', 'byteoff', 'firstoff', 'pointeroneoff',
                                               'pointertwooff', 'lastoff')}
    if any(not 0 <= value <= 32767 for value in values.values()):
        return []
    target = '\n'.join(normalized_integer_lines(left for _, left, _ in rows if left))
    table = re.search(rf'lui \$v1, %hi\((?P<table>{IDENT})\)\nlw \$v1, %lo\((?P=table)\)\(\$v1\)\n'
                      rf'lb \$v0, {values["indexoff"]}\(\$v0\)\naddu \$v1, \$v1, \$v0\n'
                      rf'jal {re.escape(m["read"])}\nlbu \$a0, {values["byteoff"]}\(\$v1\)', target)
    if not table:
        return []
    base, tableaddr = resolve(m['state']), resolve(table['table'])
    if base is None or tableaddr is None or tableaddr != base + integer(m['tableoff']):
        return []
    global_ = re.escape(m['global'])
    tail = (rf'lui \$a0, %hi\({global_}\)\nlw \$a0, %lo\({global_}\)\(\$a0\)\n'
            rf'sb \$zero, {values["firstoff"]}\(\$a0\)\nlui \$a1, %hi\({global_}\)\n'
            rf'lw \$a1, %lo\({global_}\)\(\$a1\).*?'
            rf'sw \$v1, {values["pointeroneoff"]}\(\$a0\).*?'
            rf'sw \$v1, {values["pointertwooff"]}\(\$a0\)\n'
            rf'sb \$zero, {values["lastoff"]}\(\$a1\)')
    if not re.search(tail, target, re.S):
        return []
    context = _blank(header + '\n' + source)
    fresh = ('__repair_table', '__repair_first', '__repair_last')
    macros = set(re.findall(r'(?m)^\s*#\s*(?:define|undef)\s+(' + IDENT + r')', context))
    if (macros.intersection(names + list(fresh) + ['s32', 's8', 's16', 'u8', 'M2C_UNK'])
            or re.search(r'(?m)^\s*#\s*undef\s+M2C_FIELD\b', context)
            or any(re.search(r'\b' + n + r'\b', context) for n in fresh)):
        return []
    for typ, expected in [('s32', r'(?:signed\s+)?int'), ('s8', r'(?:signed\s+)?char'),
                          ('s16', r'(?:signed\s+)?short(?:\s+int)?'), ('u8', r'unsigned\s+char'),
                          ('M2C_UNK', r's32')]:
        aliases = re.findall(r'\btypedef\s+([^;{}]+?)\s+' + typ + r'\s*;', context)
        if len(aliases) != 1 or not re.fullmatch(expected, aliases[0].strip()):
            return []
    macro = re.findall(r'(?m)^\s*#\s*define\s+M2C_FIELD\(expr,\s*type_ptr,\s*offset\)\s+([^\n]+)', context)
    if len(macro) != 1 or re.sub(r'\s+', '', macro[0]) != '(*(type_ptr)((s8*)(expr)+(offset)))':
        return []
    if not re.search(r'\bextern\s+void\s*\*\s*' + global_ + r'\s*;', context):
        return []
    state, g = m['state'], m['global']
    body = f'''
    s32 __repair_table;
    void *__repair_first;
    void *__repair_last;
    if (M2C_FIELD(M2C_FIELD(&{state}, void **, {m['headoff']}), s16 *, {m['kindoff']}) == {m['kind']}) {{
        __repair_table = M2C_FIELD(&{state}, s32 *, {m['tableoff']});
        {m['read']}(M2C_FIELD((__repair_table + M2C_FIELD({g}, s8 *, {m['indexoff']})), u8 *, {m['byteoff']}));
        {m['call']}();
    }}
    {m['reset']}({m['firstarg']}, {m['secondarg']});
    __repair_first = {g};
    M2C_FIELD(__repair_first, s8 *, {m['firstoff']}) = 0;
    __repair_last = {g};
    M2C_FIELD(__repair_first, M2C_UNK **, {m['pointeroneoff']}) = &{m['pointerone']};
    M2C_FIELD(__repair_first, M2C_UNK **, {m['pointertwooff']}) = &{m['pointertwo']};
    M2C_FIELD(__repair_last, s8 *, {m['lastoff']}) = 0;
    return 0;
'''
    return [(FAMILY, edit(source, [(part.opening + 1, end - 1, body)]))]
