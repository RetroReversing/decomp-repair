"""Recover a measured slot address and preserved incoming call argument."""
import re

from .csource import _blank
from .integer_repair_support import IDENT, edit, integer, view
from .large_stack_drafts import _shape
from .mips import normalized_integer_lines
from .pattern_repairs import close

FAMILY = 'measured_call_slot_setup'
FAMILIES = (FAMILY,)

_HEAD = '''
    s32 @result;
    {stores}
    M2C_FIELD(&@global, s8 *, @flagoff) = 1;
    M2C_FIELD(@argzero, s32 *, @fieldoff) = 1;
    @result = 0;
    if (M2C_FIELD(@argone, u8 *, @testoff) != 0) {{
        M2C_FIELD(&@global, void **, @owneroff) = @argzero;
        M2C_FIELD(&@global, void **, @slotoff) = @argone;
        M2C_FIELD(@argzero, s32 *, @fieldoff) = 1;
        @callee({args});
        @result = 1;
    }}
    return @result;
'''
_STORE_OWNER = 'M2C_FIELD(&@global, void **, @owneroff) = @argzero;'
_STORE_SLOT = 'M2C_FIELD(&@global, void **, @slotoff) = @argone;'
_NUMBERS = ('flagoff', 'fieldoff', 'testoff', 'owneroff', 'slotoff')


def _pattern(order, args):
    template = _HEAD.format(stores=' '.join(order), args=args)
    return _shape(template, numbers=_NUMBERS)


_PATTERNS = [
    (_pattern(order, args), omitted)
    for order in ((_STORE_OWNER, _STORE_SLOT), (_STORE_SLOT, _STORE_OWNER))
    for args, omitted in [('@argzero, 0, 1, (char *)&@global + @slotoff', False),
                          ('0, 1, (char *)&@global + @slotoff', True)]
]


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
    body = ' '.join(part.clean[part.opening + 1:end - 1].split())
    match = next(((hit, omitted) for pattern, omitted in _PATTERNS if (hit := pattern.fullmatch(body))), None)
    if not match:
        return []
    m, omitted = match
    signature = re.search(r'\bs32\s+' + re.escape(name) + r'\s*\(\s*void\s*\*\s*' + re.escape(m['argzero'])
                          + r'\s*,\s*void\s*\*\s*' + re.escape(m['argone']) + r'\s*\)\s*$', part.clean[:part.opening])
    roles = [m[k] for k in ('result', 'global', 'argzero', 'argone', 'callee')]
    if not signature or len(set(roles)) != len(roles):
        return []
    target = '\n'.join(normalized_integer_lines(left for _, left, _ in rows if left))
    slot = re.search(rf'lui \$a3, %hi\((?P<name>{IDENT})\)\naddiu \$a3, \$a3, %lo\((?P=name)\)', target)
    owner = re.search(rf'lui \$at, %hi\((?P<name>{IDENT})\)\nsw \$a0, %lo\((?P=name)\)\(\$at\)\n'
                      r'sw \$a1, \(\$a3\)', target)
    flag = re.search(rf'lui \$at, %hi\((?P<name>{IDENT})\)\nsb \$v0, %lo\((?P=name)\)\(\$at\)', target)
    if not all((slot, owner, flag)):
        return []
    base = resolve(m['global'])
    if base is None or any(resolve(hit['name']) != base + integer(m[off])
                           for hit, off in ((slot, 'slotoff'), (owner, 'owneroff'), (flag, 'flagoff'))):
        return []
    field, test = integer(m['fieldoff']), integer(m['testoff'])
    slotoff, owneroff, flagoff = (integer(m[k]) for k in ('slotoff', 'owneroff', 'flagoff'))
    if not (0 <= field <= 32767 and 0 <= test <= 32767 and abs(slotoff - owneroff) >= 4
            and flagoff not in range(slotoff, slotoff + 4) and flagoff not in range(owneroff, owneroff + 4)):
        return []
    if not re.search(rf'sw \$a2, {field}\(\$a0\)\nlbu \$v0, {test}\(\$a1\).*?'
                     rf'move \$a1, \$zero\nsw \$a2, {field}\(\$a0\)\n'
                     rf'jal {re.escape(m["callee"])}\nnop', target, re.S):
        return []
    # The first incoming argument is still in $a0 at the call.
    before_call = target[:target.index('jal ' + m['callee'])]
    if ('jal ' in before_call or re.search(r'(?m)^(?!(?:s[bhwd]|b\w*|j\w*)\s)[a-z][\w.]*\s+\$a0\s*,', before_call)):
        return []
    context = _blank(header + '\n' + source)
    macros = set(re.findall(r'(?m)^\s*#\s*(?:define|undef)\s+(' + IDENT + r')', context))
    if macros.intersection(roles + ['s32', 's8', 'u8', 'M2C_UNK', '__repair_slot']) or re.search(
            r'\b__repair_slot\b|(?m:^\s*#\s*undef\s+M2C_FIELD\b)', context):
        return []
    for typ, expected in [('s32', r'(?:signed\s+)?int'), ('s8', r'(?:signed\s+)?char'),
                          ('u8', r'unsigned\s+char'), ('M2C_UNK', r's32')]:
        aliases = re.findall(r'\btypedef\s+([^;{}]+?)\s+' + typ + r'\s*;', context)
        if len(aliases) != 1 or not re.fullmatch(expected, aliases[0].strip()):
            return []
    macro = re.findall(r'(?m)^\s*#\s*define\s+M2C_FIELD\(expr,\s*type_ptr,\s*offset\)\s+([^\n]+)', context)
    if len(macro) != 1 or re.sub(r'\s+', '', macro[0]) != '(*(type_ptr)((s8*)(expr)+(offset)))':
        return []
    if not re.search(r'\bextern\s+(?:s32|M2C_UNK)\s+' + re.escape(m['global']) + r'\s*;', context):
        return []
    edits = []
    if omitted:
        # The target forwards $a0 and has four live argument registers. Relax
        # only the draft's unique three-argument prototype; do not edit headers.
        callee_call = r'\b' + re.escape(m['callee']) + r'\s*\('
        if re.search(callee_call, header) or len(re.findall(callee_call, part.clean)) != 2:
            return []
        prototype = re.compile(r'\bM2C_UNK\s+' + re.escape(m['callee']) +
                               r'\s*\(\s*M2C_UNK\s*,\s*M2C_UNK\s*,\s*void\s*\*\s*\)\s*;')
        declarations = list(prototype.finditer(part.clean[:signature.start()]))
        if len(declarations) != 1:
            return []
        decl = declarations[0]
        edits.append((decl.start(), decl.end(), f'M2C_UNK {m["callee"]}();'))
    g, a, b, result, callee = (m[k] for k in ('global', 'argzero', 'argone', 'result', 'callee'))
    replacement = f'''
    s32 {result};
    void **__repair_slot;
    __repair_slot = (void **)((char *)&{g} + {m['slotoff']});
    M2C_FIELD(&{g}, void **, {m['owneroff']}) = {a};
    *__repair_slot = {b};
    M2C_FIELD(&{g}, s8 *, {m['flagoff']}) = 1;
    M2C_FIELD({a}, s32 *, {m['fieldoff']}) = 1;
    {result} = 0;
    if (M2C_FIELD({b}, u8 *, {m['testoff']}) != 0) {{
        M2C_FIELD(&{g}, void **, {m['owneroff']}) = {a};
        *__repair_slot = {b};
        M2C_FIELD({a}, volatile s32 *, {m['fieldoff']}) = 1;
        {callee}({a}, 0, 1, __repair_slot);
        {result} = 1;
    }}
    return {result};
'''
    edits.append((part.opening + 1, end - 1, replacement))
    return [(FAMILY, edit(source, edits))]
