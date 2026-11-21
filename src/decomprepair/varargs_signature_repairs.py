"""A function m2c read as fixed parameters that the game wrote with `...`.

A varargs function's first instructions, before its frame, store its unnamed argument registers to their home slots
(`sw $a2, 0x8($sp)`, `sw $a3, 0xC($sp)`), so that `va_start` can walk them. m2c reads those parameters as named and
the `va_list` as the address of the first: `_Printf(f, buf, arg1, &arg2)`. Compiled so, the spills go and the frame
changes; an N64 function was 72.3% so and 94.9% as `(void *arg0, s32 arg1, ...)` with `__builtin_next_arg(arg1)` in
place of `&arg2` (gcc 2.7.2's own `va_start`), and exact once its `buf[n] = 0` stored a byte (raw_store_width). Offered
only when the target spills before its frame and the C takes the address of a parameter it spills.
"""
import re

from . import m2cfix
from .csource import _blank, find
from .integer_repair_support import edit, view
from .pattern_repairs import close

FAMILY = 'varargs_signature'
IDENT = r'[A-Za-z_]\w*'


def _home_spills(asm):
    """The argument registers (1-3) the target stores to their home slots before it allocates its frame."""
    spilled = []
    for line in (asm or '').splitlines():
        if re.search(r'\baddiu\s+\$sp\s*,\s*\$sp\s*,\s*-', line):
            break
        m = re.search(r'\bsw\s+\$a([1-3])\s*,\s*(0x[0-9a-fA-F]+|\d+)\(\$sp\)', line)
        if m and int(m[2], 0) == 4 * int(m[1]):
            spilled.append(int(m[1]))
    return spilled


def _varargs(source, name, asm):
    span = find(source, name)
    spills = _home_spills(asm)
    if not span or not spills:
        return []
    clean = _blank(source)
    opening = clean.find('{', span[0], span[1])
    end = close(clean, opening, '{', '}') if opening >= 0 else None
    if not end:
        return []
    paren = clean.find('(', clean.find(name, span[0]))
    closing = close(clean, paren)
    params = [p.strip() for p in m2cfix._split_top_level(clean[paren + 1:closing - 1])]
    names = [re.search(IDENT + r'\s*$', p)[0].strip() if re.search(IDENT + r'\s*$', p) else '' for p in params]
    # (gcc spills from the first named parameter after the first too: the first unnamed one is the spilled
    # parameter whose address the C takes, m2c's view of the va_list)
    first = next((k for k in spills if k < len(names) and re.search(r'&\s*' + names[k] + r'\b', clean[opening:end])),
                 None)
    if first is None or first < 1 or '...' in params:
        return []
    unnamed, last = names[first], names[first - 1]
    taken = re.search(r'&\s*' + unnamed + r'\b', clean[opening:end])
    # the unnamed parameters may only be reached through the va_list
    if not taken or any(re.search(r'(?<![\w&])' + n + r'\b', clean[opening:end].replace('&' + unnamed, ''))
                        for n in names[first:]):
        return []
    at = opening + taken.start()
    line_start = source.rfind('\n', 0, at) + 1
    indent = re.match(r'[ \t]*', source[line_start:])[0]
    text = source[:at] + '__repair_ap' + source[opening + taken.end():]
    text = text[:line_start] + f'{indent}__repair_ap = (char *) __builtin_next_arg({last});\n' + text[line_start:]
    text = text[:opening + 1] + '\n    char *__repair_ap;' + text[opening + 1:]
    text = text[:paren + 1] + ', '.join(params[:first] + ['...']) + text[closing - 1:]
    return [(FAMILY, text)]


STORE_FAMILY = 'raw_store_width'
FAMILIES = (FAMILY, STORE_FAMILY)
WIDTHS = {'sb': 's8', 'sh': 's16'}


def store_widths(source, name, asm):
    """m2c's `*(s32 *)(expr) = value;` where the target stores a narrower width at offset 0: a `printf`-style
    terminator `buf[n] = 0` came back as a word store where the game stored a byte (`sb $zero, 0x0($v0)`)."""
    span = find(source, name)
    if not span or not asm:
        return []
    clean = _blank(source)
    opening = clean.find('{', span[0], span[1])
    end = close(clean, opening, '{', '}') if opening >= 0 else None
    if not end:
        return []
    narrow = {WIDTHS[m[1]] for m in re.finditer(r'\b(sb|sh)\s+\$\w+\s*,\s*0x0\(', asm)}
    result = []
    for kind in sorted(narrow):
        text = source
        for m in reversed(list(re.finditer(r'\*\s*\(\s*s32\s*\*\s*\)\s*(?=\()', clean[opening:end]))):
            stmt_end = clean.find(';', opening + m.end())
            paren_end = close(clean, opening + m.end())
            if not paren_end or not re.match(r'\s*=(?!=)', clean[paren_end:stmt_end + 1]):
                continue  # (a store, not a load)
            text = text[:opening + m.start()] + f'*({kind} *)' + text[opening + m.end():]
        if text != source:
            result.append((STORE_FAMILY, text))
    # The other way: m2c's `*p = (s32) e;` through a pointer it typed narrower, where the target stores a word at
    # offset 0. m2c's own cast says so: a branch stored `lbu`'s value with `sw` (93.6% -> exact as `*(s32 *) p = e;`).
    if re.search(r'\bsw\s+\$\w+\s*,\s*0x0\(', asm):
        narrow_ptrs = set(re.findall(r'(?m)^[ \t]*(?:s8|u8|s16|u16|char|short)\s*\*\s*(' + IDENT + r')\s*;', clean[opening:end]))
        for m in re.finditer(r'(?m)^(?P<ind>[ \t]*)\*(?P<p>' + IDENT + r')\s*=\s*\(\s*s32\s*\)\s*', clean[opening:end]):
            if m['p'] not in narrow_ptrs:
                continue
            at = opening + m.start()
            text = source[:at] + f"{m['ind']}*(s32 *) {m['p']} = " + source[opening + m.end():]
            if text not in [t for _, t in result]:
                result.append((STORE_FAMILY, text))
    return result[:6]


def empty_home_leaf(source, name):
    """The whole target is the O32 four-register varargs save sequence."""
    part = view(source, name)
    if not part or part.clean[part.opening+1:part.clean.rfind('}', part.opening, part.end)].strip():
        return None
    pattern = re.compile(
        rf'\bvoid\s+{re.escape(name)}\s*\(\s*(?P<first>(?:s32|u32|M2C_UNK)\s+{IDENT})'
        rf'(?P<other>(?:\s*,\s*(?:s32|u32|M2C_UNK)\s+{IDENT}){{3}})\s*\)\s*$')
    signature = pattern.search(part.clean[:part.opening])
    if not signature:
        return None
    return edit(source, [(*signature.span('other'), ', ...')])


def variants(source, name, asm):
    return _varargs(source, name, asm) + store_widths(source, name, asm)
