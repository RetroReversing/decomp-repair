"""m2c's expansion of an unsigned integer converted to a double, written back as the conversion.

The compiler converts a `u32` with the signed `cvt.d.w` and adds 4294967296.0 when the word was negative. m2c prints
that expansion over a signed local, with the constant read from the pool (often through a local it hoisted):

    var = (f64) temp;
    if (temp < 0) {
        var += temp_fs1;          /* temp_fs1 = D_80100880; */
    }

Compiled as written the constant is a load of a global and the value an ordinary signed local, so the load's place and
the registers differ. `var = (f64) (u32) temp;` is the game's conversion. On a 204-instruction KMC GCC 2.7.2 -O1
effect spawner the two sites judged 285 -> 15 on its repaired machine draft.

Only when the added value is 4294967296.0 written out, or a `D_` symbol the target loads with `ldc1` (directly or
through a local set from it). All the sites together first, then each alone; the exact judge decides."""
import re

from .csource import _blank, find

FAMILY = 'unsigned_double_bias_fold'
FAMILIES = (FAMILY,)
LIMIT = 8
_EXPANSION = re.compile(
    r'(?<![\w.>])(?P<dst>[A-Za-z_]\w*)\s*=\s*\(\s*(?:f64|double)\s*\)\s*(?P<src>[A-Za-z_]\w*(?:\.\w+)?)\s*;\s*'
    r'if\s*\(\s*(?:\(\s*(?:s32|int)\s*\)\s*)?(?P=src)\s*<\s*0\s*\)\s*'
    r'(?P<brace>\{\s*)?(?P=dst)\s*\+=\s*(?P<bias>4294967296(?:\.0*)?|0x1p32|[A-Za-z_]\w*)\s*;(?(brace)\s*\})')


def _is_bias(clean, bias, asm):
    if bias[0].isdigit():
        return True
    loaded = set(re.findall(r'\bldc1\s+\$\w+\s*,\s*%lo\(\s*([A-Za-z_]\w*)\s*\)', asm or ''))
    if bias in loaded:
        return True
    # (a local m2c hoisted the pool constant into: every assignment to it reads one such symbol)
    values = re.findall(rf'(?<![\w.>]){bias}\s*=(?!=)\s*([^;]+);', clean)
    return bool(values) and all(value.strip() in loaded for value in values)


def variants(source, name, asm=''):
    span = find(source, name)
    if not span:
        return []
    clean = _blank(source)
    edits = [(hit.start(), hit.end(), f'{hit["dst"]} = (f64) (u32) {hit["src"]};')
             for hit in _EXPANSION.finditer(clean, span[0], span[1]) if _is_bias(clean, hit['bias'], asm)]
    groups = [edits] if len(edits) > 1 else []
    groups += [[edit] for edit in edits]
    out = []
    for group in groups[:LIMIT]:
        child = source
        for start, end, text in sorted(group, reverse=True):
            child = child[:start] + text + child[end:]
        out.append((FAMILY, child))
    return out


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'asm'), 'archs': ('mips',)}
