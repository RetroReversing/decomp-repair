"""Recover the two global pointer lifetimes of a measured teardown sequence."""
import re

from .csource import _blank
from .integer_repair_support import IDENT, edit, integer, view
from .large_stack_drafts import _shape
from .mips import normalized_integer_lines
from .pattern_repairs import close

FAMILY = 'measured_teardown_pointer_order'
FAMILIES = (FAMILY,)

BODY = _shape('''
    @first();
    @reset(@argone, @argtwo);
    @phase = @phasevalue;
    M2C_FIELD(@selection, M2C_UNK **, @callbackoffa) = &@callbacka;
    M2C_FIELD(@selection, M2C_UNK **, @callbackoffb) = &@callbackb;
    M2C_FIELD(M2C_FIELD(&@state, void **, @stateoff), s16 *, @flagoff) = 0;
    @teardown(M2C_FIELD(&@state, void **, @stateoff));
    @finish();
    return 1;
''', numbers=('phasevalue', 'callbackoffa', 'callbackoffb', 'stateoff', 'flagoff'))


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
    signature = (re.search(r'\bs32\s+' + re.escape(name) + r'\s*\(\s*s32\s+' + re.escape(m['argone'])
                           + r'\s*,\s*M2C_UNK\s+' + re.escape(m['argtwo']) + r'\s*\)\s*$',
                           part.clean[:part.opening]) if m else None)
    if not signature:
        return []
    roles = [m[k] for k in ('first', 'reset', 'argone', 'argtwo', 'phase', 'selection', 'callbacka', 'callbackb',
                             'state', 'teardown', 'finish')]
    if len(set(roles)) != len(roles):
        return []
    target, candidate = ('\n'.join(normalized_integer_lines(row[side] for row in rows if row[side]))
                         for side in (1, 2))
    select = re.escape(m['selection'])
    target_order = re.compile(
        rf'lui \$v1, %hi\({select}\)\nlw \$v1, %lo\({select}\)\(\$v1\)\n'
        rf'lui \$a0, %hi\((?P<list>{IDENT})\)\nlw \$a0, %lo\((?P=list)\)\(\$a0\)')
    found = target_order.search(target)
    if not found or target_order.search(candidate):
        return []
    base, actual = resolve(m['state']), resolve(found['list'])
    if base is None or actual != base + integer(m['stateoff']):
        return []
    a, b, field = (integer(m[k]) for k in ('callbackoffa', 'callbackoffb', 'flagoff'))
    if not all(0 <= off <= 32767 for off in (a, b, field)) or abs(a - b) < 4:
        return []
    if not all((f'jal {m["first"]}' in target, f'jal {m["reset"]}' in target,
                f'addiu $v0, $zero, {integer(m["phasevalue"])}\nlui $at, %hi({m["phase"]})\n'
                f'sb $v0, %lo({m["phase"]})($at)' in target,
                f'lui $v0, %hi({m["callbacka"]})\naddiu $v0, $v0, %lo({m["callbacka"]})\n'
                f'sw $v0, {a}($v1)' in target,
                f'lui $v0, %hi({m["callbackb"]})\naddiu $v0, $v0, %lo({m["callbackb"]})\n'
                f'sw $v0, {b}($v1)' in target,
                f'jal {m["teardown"]}\nsh $zero, {field}($a0)' in target,
                f'jal {m["finish"]}\nnop' in target)):
        return []
    context = _blank(header + '\n' + source)
    fresh = ('__repair_list', '__repair_selection')
    types = ('s8', 's16', 's32', 'M2C_UNK')
    macros = set(re.findall(r'(?m)^\s*#\s*(?:define|undef)\s+(' + IDENT + r')', context))
    if (macros.intersection(roles + list(fresh) + list(types)) or re.search(r'(?m)^\s*#\s*undef\s+M2C_FIELD\b', context)
            or any(re.search(r'\b' + n + r'\b', context) for n in fresh)):
        return []
    for typ, expected in [('s8', r'(?:signed\s+)?char'), ('s16', r'(?:signed\s+)?short(?:\s+int)?'),
                          ('s32', r'(?:signed\s+)?int'), ('M2C_UNK', r's32')]:
        aliases = re.findall(r'\btypedef\s+([^;{}]+?)\s+' + typ + r'\s*;', context)
        if len(aliases) != 1 or not re.fullmatch(expected, aliases[0].strip()):
            return []
    macro = re.findall(r'(?m)^\s*#\s*define\s+M2C_FIELD\(expr,\s*type_ptr,\s*offset\)\s+([^\n]+)', context)
    if len(macro) != 1 or re.sub(r'\s+', '', macro[0]) != '(*(type_ptr)((s8*)(expr)+(offset)))':
        return []
    for typ, role in [('void\\s*\\*', 'selection'), ('s8\\s+', 'phase'), ('M2C_UNK\\s+', 'state')]:
        if not re.search(r'\bextern\s+' + typ + r'\s*' + re.escape(m[role]) + r'\s*;', context):
            return []
    g, state = m['selection'], m['state']
    base_expr = f'M2C_FIELD(&{state}, void **, {m["stateoff"]})'
    # An extra ordinary pointer test gives the old optimizer another scheduling
    # shape. Both arms execute the same work and return; no data-dependent arm
    # is added to the generated machine code unless the judge accepts it.
    body = f'''    {m['reset']}({m['argone']}, {m['argtwo']});
    {m['phase']} = {m['phasevalue']};
    __repair_list = (s16 *)((char *){base_expr} + {m['flagoff']});
    __repair_selection = {g};
    M2C_FIELD(__repair_selection, M2C_UNK **, {m['callbackoffa']}) = &{m['callbacka']};
    M2C_FIELD(__repair_selection, M2C_UNK **, {m['callbackoffb']}) = &{m['callbackb']};
    *__repair_list = 0;
    {m['teardown']}({base_expr});
    {m['finish']}();
    return 1;
'''
    replacement = (f'\n    s16 *__repair_list;\n    void *__repair_selection;\n    {m["first"]}();\n'
                   f'    if ({g}) {{\n{body}    }} else {{\n{body}    }}\n')
    return [(FAMILY, edit(source, [(part.opening + 1, end - 1, replacement)]))]
