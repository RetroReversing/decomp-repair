"""A `static inline` helper's integer parameter declared at another width (`u32 value` as `u16`, `u8`, `s16` or `s32`).

KMC GCC 2.7.2 (`-O2`, N64) inlines the helper by copying each argument into a pseudo of the parameter's mode
(integrate.c); MIPS defines no PROMOTE_MODE, so a `u16` parameter is a halfword pseudo whose conversion from the
caller's expression is a separate insn, and the first scheduler places it by the parameter's uses, not where the
caller computed the value. A sound-sequence interpreter's branch helper (`value >= D_9E` then a table lookup) called
with `randomU16Next() & 0xFF` and with halfword fields: with `u16 value` the `andi` of the masked argument comes after
the helper's own loads (`lbu; lw; andi; sltu`), as the target has it, where `u32 value` put it first. 3350 -> 3230 on
a 1315-instruction function. The judge decides; the program is the same when every caller passes a value that fits,
which a width the callers' expressions are already masked or loaded at is.

Offers, for each scalar integer parameter of each `static inline` function in the source, each other width of
`u8 u16 s16 u32 s32`, one parameter at a time, and a narrower one only when every call passes a value that fits it
(a literal, a `& 0xFF`/`& 0xFFFF` mask, a `(u8)`/`(u16)` cast or a `u8`/`u16` read): a mask parameter narrowed below
its callers' constants is another program. Also each other width of a helper's integer return type, a narrower one
only when every `return` gives a literal that fits: the same interpreter's slot test (`return 1;` / `return 0;`)
returning `s32` instead of `u8` kept the caller's `andi $v0, $v0, 0xff` after the join and the registers around it,
2960 -> 2700. Bounded to `LIMIT` children.
"""
import re

from .integer_repair_support import IDENT

FAMILY = 'inline_param_width'
FAMILIES = (FAMILY,)
LIMIT = 24
WIDTHS = ('u16', 'u8', 's16', 'u32', 's32')
_HEAD = re.compile(rf'(?m)^[ \t]*(?:static\s+inline|inline\s+static)\s+(?P<ret>[^;{{()]*?)\b(?P<fn>{IDENT})\s*\((?P<params>[^)]*)\)\s*\{{')


_BITS = {'u8': 8, 'u16': 16, 's16': 15, 'u32': 32, 's32': 32}


def _python_close(text, at):
    depth = 0
    for i in range(at, len(text)):
        depth += (text[i] == '(') - (text[i] == ')')
        if depth == 0:
            return i
    return None


_close = _python_close
try:  # the typed kernel (native_build.py), when it is built: same answers, the loop in C
    from . import _scan
except ImportError:
    _scan = None
if _scan is not None:
    def _close(text, at):
        found = _scan.close_every(text, at, '(', ')', False, None)
        return _python_close(text, at) if found is NotImplemented else found


def _python_arguments(text):
    parts, depth, start = [], 0, 0
    for at, char in enumerate(text):
        depth += (char in '([') - (char in ')]')
        if char == ',' and depth == 0:
            parts.append(text[start:at].strip())
            start = at + 1
    parts.append(text[start:].strip())
    return parts


_arguments = _python_arguments
try:  # the typed kernel (native_build.py), when it is built: same answers, the loop in C
    from . import _scan
except ImportError:
    _scan = None
if _scan is not None:
    def _arguments(text):
        return [piece.strip() for piece in _scan.top_pieces(text, ',', 2)]


def _bits(arg):
    """How many value bits `arg` can carry at most, or 32 when it is not evident."""
    arg = arg.strip()
    while arg.startswith('(') and _close(arg, 0) == len(arg) - 1:
        arg = arg[1:-1].strip()
    if re.fullmatch(r'0[xX][0-9a-fA-F]+|\d+', arg):
        return max(int(arg, 0).bit_length(), 1)
    mask = re.search(r'(?<!&)&\s*(0[xX][0-9a-fA-F]+|\d+)\s*$', arg)
    depth, loose = 0, False
    for at, char in enumerate(arg):
        depth += (char in '([') - (char in ')]')
        if depth == 0 and (char in '^?,' or (char == '|' and '|' not in arg[at - 1:at + 2].replace('|', '', 1))):
            loose = True  # an `a | b & K` keeps a's bits
    if mask and not loose:
        return int(mask.group(1), 0).bit_length()
    cast = re.match(r'\(\s*(u8|u16)\s*\)', arg)
    if cast:
        return _BITS[cast.group(1)]
    if re.fullmatch(r'\*\s*\(\s*\(\s*(?:u8|u16)\s*\*\s*\)[^;]*\)', arg):
        return 8 if 'u8' in arg.split('*')[1] else 16
    return 32


def variants(source, name, header=''):
    out = []
    for head in _HEAD.finditer(source):
        if head['fn'] == name:
            continue
        params_start = head.start('params')
        offset = 0
        for piece in head['params'].split(','):
            found = re.fullmatch(rf'(\s*)(u8|u16|s16|u32|s32|int|unsigned int)(\s+)({IDENT})(\s*)', piece)
            if found:
                start = params_start + offset + found.start(2)
                end = params_start + offset + found.end(2)
                index = len(head['params'][:offset].split(',')) - 1 if offset else 0
                need = 0
                for call in re.finditer(rf'\b{head["fn"]}\s*\(', source[head.end():]):
                    at = head.end() + call.end() - 1
                    shut = _close(source, at)
                    args = _arguments(source[at + 1:shut]) if shut else []
                    need = max(need, _bits(args[index]) if index < len(args) else 32)
                for width in WIDTHS:
                    if width != found.group(2) and _BITS[width] >= need:
                        out.append((FAMILY, source[:start] + width + source[end:]))
            offset += len(piece) + 1
        ret = re.fullmatch(r'\s*(u8|u16|s16|u32|s32|int)\s*', head['ret'] or '')
        if ret:
            shut = _close(source.replace('{', '(').replace('}', ')'), head.end() - 1)
            body = source[head.end():shut] if shut else ''
            values = re.findall(r'\breturn\b\s*([^;]*);', body)
            need = max((_bits(v) for v in values), default=32)
            start, end = head.start('ret') + ret.start(1), head.start('ret') + ret.end(1)
            for width in WIDTHS:
                if width != ret.group(1) and _BITS[width] >= need:
                    out.append((FAMILY, source[:start] + width + source[end:]))
    return out[:LIMIT]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'header')}  # the registry: no caller wiring (registry.py)
