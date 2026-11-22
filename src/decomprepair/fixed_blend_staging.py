"""Stage the two products and rounded result of a three-component integer blend.

KMC GCC 2.7.2 used the first gain register for the final result of one saved
blend. The draft used separate sums and stored the shifts directly; staging
those values and reusing the gain after its last read reproduces the target.
"""
import re

from .integer_repair_support import IDENT, view
from .pattern_repairs import close

FAMILY = 'fixed_blend_staging'
FAMILIES = (FAMILY,)


def variants(source, name, rows, *, header=''):
    part = view(source, name)
    if not part:
        return []
    target = [left for _, left, _ in rows if left]
    if sum(bool(re.match(r'mult\s', line)) for line in target) != 6 or sum(
            bool(re.match(r'sra\s', line)) for line in target) != 3:
        return []
    signature = re.search(r'\b' + re.escape(name) + r'\s*\(\s*void\s*\*\s*(' + IDENT + r')\s*,\s*'
                          r'void\s*\*\s*(' + IDENT + r')\s*,\s*s32\s+(' + IDENT + r')\s*,\s*'
                          r's32\s+(' + IDENT + r')\s*,\s*void\s*\*\s*(' + IDENT + r')\s*\)\s*$',
                          part.clean[:part.opening])
    if not signature or len(set(signature.groups())) != 5:
        return []
    a, b, gain, other, dst = signature.groups()
    # The measured form uses ordinary 32-bit integer scalars and the standard
    # draft field macro; reject aliases or macros that could make writes visible.
    context = header + '\n' + source[:part.opening]
    for typ, expected in [('s32', r'(?:signed\s+)?int'), ('s16', r'(?:signed\s+)?short(?:\s+int)?')]:
        aliases = re.findall(r'\btypedef\s+([^;{}]+?)\s+' + typ + r'\s*;', context)
        if len(aliases) != 1 or not re.fullmatch(expected, aliases[0].strip()):
            return []
    macro = re.findall(r'(?m)^\s*#\s*define\s+M2C_FIELD\(expr,\s*type_ptr,\s*offset\)\s+([^\n]+)', context)
    if len(macro) != 1 or re.sub(r'\s+', '', macro[0]) != '(*(type_ptr)((s8*)(expr)+(offset)))':
        return []
    names = set(signature.groups()) | {'s16', 's32', 'M2C_FIELD'}
    if any(m in names - {'M2C_FIELD'} for m in re.findall(r'(?m)^\s*#\s*(?:define|undef)\s+(' + IDENT + r')', context)):
        return []
    closing = close(part.clean, part.opening, '{', '}')
    if not closing:
        return []
    body = part.clean[part.opening + 1:closing - 1]
    declarations = re.match(r'\s*((?:s32\s+' + IDENT + r'\s*;\s*)+)', body)
    if not declarations:
        return []
    locals_ = re.findall(r'\bs32\s+(' + IDENT + r')\s*;', declarations[1])
    if len(set(locals_)) != len(locals_) or set(locals_) & set(signature.groups()):
        return []
    defined = set(re.findall(r'(?m)^\s*#\s*(?:define|undef)\s+(' + IDENT + r')', context))
    if defined & set(locals_):
        return []
    begin = part.opening + 1 + declarations.end()
    end = closing - 1
    if re.search(r'/\*|//|(?m:^\s*#)', source[part.opening + 1:end]):
        return []
    stage = (r'\s*(?P<t{n}>' + IDENT + r')\s*=\s*\(M2C_FIELD\(\s*' + re.escape(a)
             + r'\s*,\s*s16\s*\*\s*,\s*{offset}\s*\)\s*\*\s*' + re.escape(gain)
             + r'\s*\)\s*\+\s*\(M2C_FIELD\(\s*' + re.escape(b)
             + r'\s*,\s*s16\s*\*\s*,\s*{offset}\s*\)\s*\*\s*' + re.escape(other)
             + r'\s*\)\s*;\s*(?P<v{n}>' + IDENT + r')\s*=\s*(?P=t{n})\s*;\s*'
             + r'if\s*\(\s*(?P=t{n})\s*<\s*0\s*\)\s*\{{\s*(?P=v{n})\s*=\s*(?P=t{n})\s*\+\s*'
             + r'(?P<bias{n}>0[xX][0-9a-fA-F]+|[0-9]+)\s*;\s*\}}\s*'
             + r'M2C_FIELD\(\s*' + re.escape(dst) + r'\s*,\s*s16\s*\*\s*,\s*{offset}\s*\)\s*=\s*'
             + r'\(s16\)\s*\(\s*(?P=v{n})\s*>>\s*(?P<shift{n}>0[xX][0-9a-fA-F]+|[0-9]+)\s*\)\s*;')
    pattern = ''.join(stage.format(n=i, offset=offset) for i, offset in enumerate(('0', '2', '4')))
    found = re.fullmatch(pattern + r'\s*', body[declarations.end():])
    if not found:
        return []
    temps = [found[f't{i}'] for i in range(3)]
    values = [found[f'v{i}'] for i in range(3)]
    if (not set(temps + values) <= set(locals_) or set(temps) & set(values)
            or len(set(values)) != 3 or len({found[f'bias{i}'] for i in range(3)}) != 1
            or len({found[f'shift{i}'] for i in range(3)}) != 1):
        return []
    # None of these local assignments escape, and the gain's final product is
    # evaluated before the gain itself is reused.
    out = []
    for i, offset in enumerate((0, 2, 4)):
        t, v = temps[i], values[i]
        product = f'(M2C_FIELD({a}, s16 *, {offset}) * {gain})'
        second = f'(M2C_FIELD({b}, s16 *, {offset}) * {other})'
        if i == 2:
            start = f'{t} = {product}; {gain} = {t}; {gain} += {second};'
            t = gain
        else:
            start = f'{t} = {product}; {t} += {second};'
        out.append(f'    {start}\n    {v} = {t};\n    if ({t} < 0) {{\n'
                   f'        {v} = {t} + {found[f"bias{i}"]};\n    }}\n'
                   f'    {t} = {v} >> {found[f"shift{i}"]}; '
                   f'M2C_FIELD({dst}, s16 *, {offset}) = (s16) {t};')
    return [(FAMILY, source[:begin] + '\n' + '\n'.join(out) + '\n' + source[end:])]
