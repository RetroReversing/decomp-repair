"""Recover a counted record walk whose bound is a separately named global."""
import re

from .csource import _blank
from .integer_repair_support import IDENT, edit, integer, view
from .large_stack_drafts import _shape
from .mips import normalized_integer_lines
from .pattern_repairs import close

FAMILY = 'measured_flag_count_loop'
FAMILIES = (FAMILY,)

BODY = _shape('''
    s32 @hits; s32 @index; void *@cursor;
    @index = 0;
    @cursor = M2C_FIELD(&@owner, void **, @owneroff);
    @hits = 0;
    if (M2C_FIELD(&@state, s32 *, @countoff) > 0) {
        do {
            if (M2C_FIELD(@cursor, s32 *, @activeoff) != 0) {
                if (M2C_FIELD(@cursor, u16 *, @flagoff) != 0) {
                    if (!(@arg & @maskone)) { @index += 1; }
                    else { goto @hitlabel; }
                } else {
                    if (@arg & @masktwo) { @hitlabel: @hits += 1; }
                    goto @nextlabel;
                }
            } else { @nextlabel: @index += 1; }
            @cursor += @stride;
        } while (@index < M2C_FIELD(&@state, s32 *, @countoff));
    }
    return @hits;
''', numbers=('owneroff', 'countoff', 'activeoff', 'flagoff', 'maskone', 'masktwo', 'stride'))


def variants(source, name, header, rows, resolve):
    if not resolve:
        return []
    target = '\n'.join(normalized_integer_lines(left for _, left, _ in rows if left))
    found = re.search(rf'lui \$v0, %hi\((?P<count>{IDENT})\)\nlw \$v0, %lo\((?P=count)\)\(\$v0\)', target)
    if not found or not re.search(r'blez \$v0, \d+', target):
        return []
    part = view(source, name)
    if not part:
        return []
    end = close(part.clean, part.opening, '{', '}')
    if not end or re.search(r'/\*|//|(?m:^\s*#)', source[part.opening + 1:end - 1]):
        return []
    m = BODY.fullmatch(' '.join(part.clean[part.opening + 1:end - 1].split()))
    signature = (re.search(r'\bs32\s+' + re.escape(name) + r'\s*\(\s*s32\s+' + re.escape(m['arg'])
                           + r'\s*\)\s*$', part.clean[:part.opening]) if m else None)
    if not signature or '\n' in part.clean[signature.start():part.opening]:
        return []
    names = [m[k] for k in ('hits', 'index', 'cursor', 'owner', 'state', 'arg', 'hitlabel', 'nextlabel')]
    if len(set(names)) != len(names) or found['count'] in names:
        return []
    base, count = resolve(m['state']), resolve(found['count'])
    if base is None or count is None or count != base + integer(m['countoff']):
        return []
    if not (0 <= integer(m['activeoff']) <= 32767 and 0 <= integer(m['flagoff']) <= 32767
            and 0 < integer(m['stride']) <= 32767 and 0 < integer(m['maskone']) <= 65535
            and 0 < integer(m['masktwo']) <= 65535):
        return []
    if not all((f'lhu $v0, {integer(m["flagoff"])}($v1)' in target,
                f'addiu $v1, $v1, {integer(m["stride"])}' in target)):
        return []
    context = _blank(header + '\n' + source)
    macros = set(re.findall(r'(?m)^\s*#\s*(?:define|undef)\s+(' + IDENT + r')', context))
    if macros & (set(names) | {found['count'], '__repair_zero'}):
        return []
    # Avoid conflicts with an existing declaration or another use of the new name.
    if re.search(r'\b' + re.escape(found['count']) + r'\b|\b__repair_zero\b', context):
        return []
    for typ, expected in [('s32', r'(?:signed\s+)?int'), ('s8', r'(?:signed\s+)?char'),
                          ('u16', r'unsigned\s+short(?:\s+int)?')]:
        aliases = re.findall(r'\btypedef\s+([^;{}]+?)\s+' + typ + r'\s*;', context)
        if len(aliases) != 1 or not re.fullmatch(expected, aliases[0].strip()):
            return []
    macro = re.findall(r'(?m)^\s*#\s*define\s+M2C_FIELD\(expr,\s*type_ptr,\s*offset\)\s+([^\n]+)', context)
    if len(macro) != 1 or re.sub(r'\s+', '', macro[0]) != '(*(type_ptr)((s8*)(expr)+(offset)))':
        return []
    h, i, p, arg, hit, next_ = (m[k] for k in ('hits', 'index', 'cursor', 'arg', 'hitlabel', 'nextlabel'))
    countname = found['count']
    body = f'''
    int __repair_zero;
    s32 {h};
    s32 {i};
    void *{p};
    {i} = 0;
    {p} = M2C_FIELD(&{m['owner']}, void **, {m['owneroff']});
    {h} = 0;
    __repair_zero = 0;
    if ({countname} > __repair_zero) {{
        do {{
            if (M2C_FIELD({p}, s32 *, {m['activeoff']}) != 0) {{
                if (M2C_FIELD({p}, u16 *, {m['flagoff']}) != 0) {{
                    if ({arg} & {m['maskone']}) goto {hit};
                }} else if ({arg} & {m['masktwo']}) goto {hit};
            }}
            goto {next_};
{hit}:
            {h} += 1;
{next_}:
            {i} += 1;
            {p} += {m['stride']};
        }} while ({i} < {countname});
    }}
    return {h};
'''
    return [(FAMILY, edit(source, [(part.opening + 1, end - 1, body),
                                   (part.clean.rfind('\n', 0, part.opening) + 1,
                                    part.clean.rfind('\n', 0, part.opening) + 1,
                                    f'extern s32 {countname};\n')]))]
