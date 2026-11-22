"""Copy a once-written loop comparison key to recover a measured register layout."""
import re

from .csource import _blank
from .entry_parameter_copy_repairs import _after_declarations, _parameters
from .integer_repair_support import IDENT, edit, view
from .mips import normalized_integer_lines
from .pattern_repairs import close
from .permuter_macro_effects import DEFINE

FAMILY = 'measured_loop_key_copy'
FAMILIES = (FAMILY,)


def variants(source, name, header, rows, flags):
    flags = set(flags or ())
    if not flags.intersection({'-mgp32', '-mabi=32'}) or flags.intersection(
            {'-m64', '-mgp64', '-mabi=64', '-mabi=n32', '-mabi=eabi'}):
        return []
    part = view(source, name)
    if not part:
        return []
    end = close(part.clean, part.opening, '{', '}')
    if not end:
        return []
    body = part.clean[part.opening + 1:end - 1]
    if re.search(r'\b(?:volatile|asm|__asm__|setjmp|longjmp|__LINE__|__COUNTER__)\b|(?m:^\s*#)', body):
        return []
    params = _parameters(part)
    if not params or len(params) > 4:
        return []
    # All earlier parameters must occupy one o32 argument register each.
    valid = r'(?:s32|u32|int|unsigned\s+int|void\s*\*|char\s*\*|s8\s*\*|u8\s*\*|s16\s*\*|u16\s*\*|s32\s*\*|u32\s*\*)'
    if any(not re.fullmatch(valid, kind) for _, _, kind in params):
        return []
    context = _blank(header + '\n' + source)
    fresh = '__repair_loop_key'
    if re.search(r'\b' + fresh + r'\b|(?m:^\s*#\s*undef\s+M2C_FIELD\b)', context):
        return []
    # An unknown macro may hide a write to the parameter. Permit only inert
    # literals and the draft's ordinary field-access macro.
    used = set(re.findall(IDENT, body))
    definitions = list(DEFINE.finditer(re.sub(r'\\\r?\n', ' ', context)))
    for macro in definitions:
        if macro[1] not in used:
            continue
        if macro[1] == 'M2C_FIELD':
            if macro[2] != '(expr, type_ptr, offset)' or re.sub(r'\s+', '', macro[3]) != '(*(type_ptr)((s8*)(expr)+(offset)))':
                return []
        elif macro[2] is not None or not re.fullmatch(r'\s*\(*\s*(?:\(\s*void\s*\*\s*\)\s*)?(?:0[xX][0-9a-fA-F]+|\d+)[uUlL]*\s*\)*\s*', macro[3]):
            return []
    if sum(m[1] == 'M2C_FIELD' for m in definitions) > 1:
        return []
    target, candidate = ('\n'.join(normalized_integer_lines(row[side] for row in rows if row[side]))
                         for side in (1, 2))
    if sum(1 for marker, left, right in rows if marker == 'r' and left != right) < 2:
        return []
    labels = [(m[1], m.start()) for m in re.finditer(r'(?m)^\s*(' + IDENT + r')\s*:(?!:)', body)]
    loops = [(at, jump.start()) for label, at in labels
             for jump in re.finditer(r'\bgoto\s+' + re.escape(label) + r'\s*;', body) if jump.start() > at]
    if not loops:
        return []
    out = []
    for index, (_, param, kind) in enumerate(params):
        if kind not in {'s32', 'u32', 'int', 'unsigned int'}:
            continue
        if kind in {'s32', 'u32'}:
            expected = r'(?:signed\s+)?int' if kind == 's32' else r'unsigned\s+int'
            aliases = re.findall(r'\btypedef\s+([^;{}]+?)\s+' + kind + r'\s*;', context)
            if len(aliases) != 1 or not re.fullmatch(expected, aliases[0].strip()):
                continue
        if any(m[1] in {param, kind, fresh, 'int', 'signed', 'unsigned'} for m in definitions):
            continue
        uses = list(re.finditer(r'(?<![\w.>])' + re.escape(param) + r'\b', body))
        if len(uses) != 1:
            continue
        use = uses[0]
        if not any(start < use.start() < stop for start, stop in loops):
            continue
        condition = re.compile(r'\bif\s*\((?P<expr>[^;{}]+)\)\s*\{')
        if not any(c.start('expr') <= use.start() < c.end('expr') and re.search(r'==|!=|<=|>=|(?<!<)<(?!<)|(?<!>)>(?!>)', c['expr'])
                   and not re.search(r'\+\+|--|(?<!&)\&\s*\(*\s*' + re.escape(param) + r'\b', c['expr'])
                   for c in condition.finditer(body)):
            continue
        reg = f'$a{index}'
        branch = re.compile(rf'\bb(?:ne|eq)l?\s+(?:\$\w+,\s*{re.escape(reg)}|{re.escape(reg)},\s*\$\w+),\s*\d+')
        if not any(hit[0] in candidate for hit in branch.finditer(target)):
            continue
        place = _after_declarations(part.clean, part.opening + 1, end - 1)
        declaration = f'\n    {kind} {fresh};'
        assignment = f'\n    {fresh} = {param};\n'
        if place == part.opening + 1:
            changes = [(place, place, declaration + assignment)]
        else:
            changes = [(part.opening + 1, part.opening + 1, declaration), (place, place, assignment)]
        offset = part.opening + 1
        changes.append((offset + use.start(), offset + use.end(), fresh))
        out.append((FAMILY, edit(source, changes)))
        if len(out) == 2:
            break
    return out
