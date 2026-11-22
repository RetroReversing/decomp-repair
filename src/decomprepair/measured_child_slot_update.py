"""Reuse a child parameter and stage the measured indexed slot addresses."""
import re

from .csource import _blank
from .integer_repair_support import IDENT, edit, integer, view
from .large_stack_drafts import _shape
from .mips import normalized_integer_lines
from .pattern_repairs import close

FAMILY = 'measured_child_slot_update'
FAMILIES = (FAMILY,)

BODY = _shape('''
    u16 @flag; u8 @index; void *@child;
    if (M2C_FIELD(M2C_FIELD(&@state, void **, @stateoff), u16 *, @gateoff) == 0) {
        @flag = M2C_FIELD(M2C_FIELD(&@state, void **, @stateoff), u16 *, @flagoff);
        if (@flag == 1) {
            @index = M2C_FIELD(M2C_FIELD(@arg, s32 **, @indexbase), u8 *, @indexoff);
            if ((@index < @limit) && (M2C_FIELD((@table + (@index * @stride)), u16 *, @maskoff) & @mask)) {
                @child = M2C_FIELD(@arg, void **, @childoff);
                @callee(@child, @callvalue);
                M2C_FIELD(M2C_FIELD(@child, void **, @firstoff), s32 *, @valueoff) = (s32) @flag;
                M2C_FIELD(M2C_FIELD(@child, void **, @secondoff), s32 *, @valueoff) = (s32) @flag;
                M2C_FIELD((@table + (*M2C_FIELD(@arg, s32 **, @indexbase) * @stride)), s16 *, @zerooff) = 0;
                M2C_FIELD((@table + (*M2C_FIELD(@arg, s32 **, @indexbase) * @stride)), s16 *, @lastoff) = @last;
            }
        }
    }
''', numbers=('stateoff', 'gateoff', 'flagoff', 'indexbase', 'indexoff', 'limit', 'stride', 'maskoff', 'mask',
              'childoff', 'callvalue', 'firstoff', 'secondoff', 'valueoff', 'zerooff', 'lastoff', 'last'))


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
    if not m or not re.search(r'\bvoid\s+' + re.escape(name) + r'\s*\(\s*void\s*\*\s*' + re.escape(m['arg'])
                             + r'\s*\)\s*$', part.clean[:part.opening]):
        return []
    roles = [m[k] for k in ('flag', 'index', 'child', 'state', 'arg', 'table', 'callee')]
    if len(set(roles)) != len(roles) or integer(m['stride']) != 68:
        return []
    target = '\n'.join(normalized_integer_lines(left for _, left, _ in rows if left))
    origin = re.search(rf'lui \$v1, %hi\((?P<name>{IDENT})\)\nlw \$v1, %lo\((?P=name)\)\(\$v1\)', target)
    base = resolve(m['state'])
    if not origin or base is None or resolve(origin['name']) != base + integer(m['stateoff']):
        return []
    offsets = {key: integer(m[key]) for key in ('gateoff', 'flagoff', 'indexbase', 'indexoff', 'maskoff',
                                               'childoff', 'firstoff', 'secondoff', 'valueoff', 'zerooff', 'lastoff')}
    if any(not 0 <= n <= 32767 for n in offsets.values()):
        return []
    if not all((f'lhu $v0, {offsets["gateoff"]}($v1)' in target,
                f'lhu $s2, {offsets["flagoff"]}($v1)' in target,
                f'lbu $a0, {offsets["indexoff"]}($v0)' in target,
                f'sltiu $v0, $a0, {integer(m["limit"])}' in target,
                f'andi $v0, $v0, {integer(m["mask"])}' in target,
                f'lhu $v0, {offsets["maskoff"]}($v0)' in target,
                f'lui $v0, %hi({m["table"]})\nlw $v0, %lo({m["table"]})($v0)' in target,
                f'lui $a0, %hi({m["table"]})\nlw $a0, %lo({m["table"]})($a0)' in target,
                f'sh $zero, {offsets["zerooff"]}($v0)' in target)):
        return []
    if not re.search(rf'move \$s0, \$s1\nlw \$s1, {offsets["childoff"]}\(\$s1\)\n'
                     rf'addiu \$a1, \$zero, {integer(m["callvalue"])}\n'
                     rf'jal {re.escape(m["callee"])}\nmove \$a0, \$s1', target):
        return []
    if not all(f'lw $v0, {offsets[key]}($s1)\nsw $s2, {offsets["valueoff"]}($v0)' in target
               for key in ('firstoff', 'secondoff')):
        return []
    if not re.search(rf'sll \$v0, \$v1, 4\naddu \$v0, \$v0, \$v1\nsll \$v0, \$v0, 2\n'
                     rf'addu \$a0, \$a0, \$v0\naddiu \$v0, \$zero, {integer(m["last"])}\n'
                     rf'sh \$v0, {offsets["lastoff"]}\(\$a0\)', target):
        return []
    context = _blank(header + '\n' + source)
    fresh = ('__repair_original', '__repair_base', '__repair_slot', '__repair_addr')
    types = ('s8', 'u8', 's16', 'u16', 's32', 'M2C_UNK')
    macros = set(re.findall(r'(?m)^\s*#\s*(?:define|undef)\s+(' + IDENT + r')', context))
    if (macros.intersection(roles + list(fresh) + list(types)) or re.search(
            r'(?m)^\s*#\s*undef\s+M2C_FIELD\b', context)
            or any(re.search(r'\b' + n + r'\b', context) for n in fresh)):
        return []
    for typ, expected in [('s8', r'(?:signed\s+)?char'), ('u8', r'unsigned\s+char'),
                          ('s16', r'(?:signed\s+)?short(?:\s+int)?'), ('u16', r'unsigned\s+short(?:\s+int)?'),
                          ('s32', r'(?:signed\s+)?int'), ('M2C_UNK', r's32')]:
        aliases = re.findall(r'\btypedef\s+([^;{}]+?)\s+' + typ + r'\s*;', context)
        if len(aliases) != 1 or not re.fullmatch(expected, aliases[0].strip()):
            return []
    macro = re.findall(r'(?m)^\s*#\s*define\s+M2C_FIELD\(expr,\s*type_ptr,\s*offset\)\s+([^\n]+)', context)
    if len(macro) != 1 or re.sub(r'\s+', '', macro[0]) != '(*(type_ptr)((s8*)(expr)+(offset)))':
        return []
    if not re.search(r'\bextern\s+s32\s+' + re.escape(m['table']) + r'\s*;', context):
        return []
    a, table, flag, index, child, callee, state = (m[k] for k in ('arg', 'table', 'flag', 'index', 'child', 'callee', 'state'))
    addr = f'(*M2C_FIELD(__repair_original, s32 **, {m["indexbase"]}) * {m["stride"]})'
    replacement = f'''
    s32 __repair_base;
    s32 __repair_slot;
    s32 __repair_addr;
    u16 {flag};
    u8 {index};
    void *{child};
    void *__repair_original;
    if (M2C_FIELD(M2C_FIELD(&{state}, void **, {m['stateoff']}), u16 *, {m['gateoff']}) == 0) {{
        {flag} = M2C_FIELD(M2C_FIELD(&{state}, void **, {m['stateoff']}), u16 *, {m['flagoff']});
        if ({flag} == 1) {{
            {index} = M2C_FIELD(M2C_FIELD({a}, s32 **, {m['indexbase']}), u8 *, {m['indexoff']});
            if (({index} < {m['limit']}) && ((__repair_base = {table}, __repair_base += {index} * {m['stride']}, M2C_FIELD(__repair_base, u16 *, {m['maskoff']})) & {m['mask']})) {{
                __repair_original = {a};
                {a} = M2C_FIELD({a}, void **, {m['childoff']});
                {callee}({a}, {m['callvalue']});
                M2C_FIELD(M2C_FIELD({a}, void **, {m['firstoff']}), s32 *, {m['valueoff']}) = (s32) {flag};
                M2C_FIELD(M2C_FIELD({a}, void **, {m['secondoff']}), s32 *, {m['valueoff']}) = (s32) {flag};
                __repair_slot = {table};
                __repair_addr = __repair_slot + {addr};
                M2C_FIELD(__repair_addr, s16 *, {m['zerooff']}) = 0;
                __repair_slot += {addr};
                M2C_FIELD(__repair_slot, s16 *, {m['lastoff']}) = {m['last']};
            }}
        }}
    }}
'''
    return [(FAMILY, edit(source, [(part.opening + 1, end - 1, replacement)]))]
