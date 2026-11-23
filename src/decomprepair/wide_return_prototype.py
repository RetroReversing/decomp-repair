"""A callee declared to return a 64-bit integer whose results are only ever kept in 32-bit variables.

    volatile long long func_800828EC(s32);  ...  u32 temp_v0 = func_800828EC(x);

m2c declares a callee it saw writing both `$v0` and `$v1` as `long long` (the second register looked like part of the
result), sometimes `volatile` to keep the call. The game's callee returned one word. A 64-bit result comes back in the
pair `$v0:$v1`, and the low word the caller keeps is the one in `$v1`: every value the call produced is copied out of
`$v1` into a temporary the allocator then ranks with the other pseudos (`pseudo prefers $v1; cause: copy from $v1`), so
the registers of everything compared with or stored from the result are off by one for the whole function (a 417-instruction
input handler: 4846 -> 4786, and with the result in `$v0` the compare operands matched the target's).

Offered for each prototype `[extern] [volatile] long long|s64|u64 f(...);` that the function calls, when every result is
kept in a variable of 32 bits or fewer or dropped, as `s32`, and as `u32` when a result goes to an unsigned variable.
When no variable's type can be read (a result that is stored somewhere the source does not declare) nothing is offered.
A candidate rewrite; the exact judge decides.
"""
import re

from .integer_repair_support import IDENT, edit, view

FAMILY = 'wide_return_prototype'
FAMILIES = (FAMILY,)
_PROTOTYPE = re.compile(
    rf'(?m)^[ \t]*(?:extern[ \t]+)?(?P<type>(?:volatile[ \t]+)?(?:unsigned[ \t]+long[ \t]+long|signed[ \t]+long[ \t]+long|long[ \t]+long|s64|u64))'
    rf'[ \t]+(?P<f>{IDENT})[ \t]*\((?P<args>[^;{{}}]*)\)[ \t]*;')
_WIDE = re.compile(r'\b(?:long\s+long|s64|u64|f64|double|float|f32)\b')
_UNSIGNED = re.compile(r'\b(?:unsigned|u8|u16|u32)\b')


def _declared(source, var):
    """The type text of `var`'s declaration (a local or an extern), or None."""
    hit = re.search(rf'(?m)^[ \t]*(?:extern[ \t]+)?(?P<t>(?:register[ \t]+|volatile[ \t]+|const[ \t]+|unsigned[ \t]+|signed[ \t]+)*'
                    rf'[A-Za-z_]\w*(?:[ \t]+(?:long|int|short|char))*[ \t*]+){re.escape(var)}[ \t]*(?:;|=|,|\[)', source)
    return hit['t'] if hit else None


def variants(source, name):
    part = view(source, name)
    if not part:
        return []
    clean = part.clean
    out = []
    for proto in _PROTOTYPE.finditer(clean[:part.opening]):
        f = proto['f']
        if f == name:
            continue
        calls = list(re.finditer(rf'(?<![\w.>]){re.escape(f)}\s*\(', clean[part.opening:part.end]))
        if not calls:
            continue
        unsigned = False
        ok = True
        for call in calls:
            at = part.opening + call.start()
            before = clean[:at].rstrip()
            if before[-1:] in (';', '{', '}'):
                continue  # the result is dropped
            assign = re.search(rf'({IDENT})\s*=\s*(?:\([^()]*\)\s*)?$', before)
            if not assign:
                continue  # inside a larger expression: compared, masked or passed on as the word it is
            kind = _declared(clean[:part.end], assign[1])
            if kind is None or _WIDE.search(kind):
                ok = False
                break
            unsigned = unsigned or bool(_UNSIGNED.search(kind))
        if not ok:
            continue
        for text in (('u32', 's32') if unsigned else ('s32',)):
            out.append((FAMILY, edit(source, [(proto.start('type'), proto.end('type'), text)])))
    return out


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}
