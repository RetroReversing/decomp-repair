"""A local read from a global, the global updated from it, and the copy into the local made after the store.

m2c writes a counter handed out from a global (`id = gNext; gNext = (id + 1) & 0x7FFFFFFF;`) with the local named for the
register the value ended in. In KMC GCC 2.7.2 (`-G0 -mips3 -mgp32 -mfp32 -O2`) cse folds the read into the local's one
assignment (`lw $a0, gNext`), where the target had read it into a temporary (`lw $v0, gNext`), updated the global from the
temporary and copied it into the local after the store, so that the loop around it started with one more instruction and
each register of the loop was the one the compiler picks when the local's own register is not tied to the load: 110 -> 0
on a 384-instruction function (isolated judge). Hypothesis, from the cse dump: with the copy after the store cse cannot
rewrite `V = T` as `V = <the memory>`, because the store changed that memory, so the read stays in its own register and the
copy stays (written the other way round it folded the temporary away: 110).

For a plain `V = G;` directly followed by `G = <expression of V>;` (G a name this function does not declare, V a local that
the function assigns elsewhere too), the child reads `T = G;`, updates the global from `T` and copies `V = T;` after the
store. Proposals only; the compiler and the byte judge decide."""
import re

from .csource import _blank, find
from .integer_repair_support import IDENT, edit
from .pattern_repairs import close

FAMILY = 'global_read_store_copy'
FAMILIES = (FAMILY,)
PAIR = re.compile(rf'(?m)^(?P<indent>[ \t]*)(?P<v>{IDENT})[ \t]*=[ \t]*(?P<g>{IDENT})[ \t]*;[ \t]*\n'
                  rf'(?P=indent)(?P=g)[ \t]*=[ \t]*(?P<expr>[^;\n]*\b(?P=v)\b[^;\n]*);[ \t]*\n')
INTEGER = r'(?:(?:unsigned|signed)\s+)?(?:char|short|int|long)|[su](?:8|16|32)'


def variants(source, name):
    span = find(source, name)
    if not span:
        return []
    clean = _blank(source)
    opening = clean.find('{', span[0], span[1])
    if opening < 0:
        return []
    end = close(clean, opening, '{', '}') or span[1]
    if re.search(r'\b(?:asm|__asm__)\b|^\s*#', clean[opening:end], re.M):
        return []
    result = []
    for pair in PAIR.finditer(clean, opening, end):
        var, glob = pair['v'], pair['g']
        decl = re.search(rf'(?m)^([ \t]*)({INTEGER})[ \t]+{re.escape(var)}[ \t]*;[ \t]*\n', clean[opening:end])
        if not decl or re.search(rf'(?m)^[ \t]*[\w ]+[ \t*]+{re.escape(glob)}\b[^;(]*;', clean[opening:end]):
            continue  # (the local must be declared here, the global must not be)
        sets = len(re.findall(rf'(?<![\w.>]){re.escape(var)}\s*=(?!=)', clean[opening:end]))
        if sets < 2 or re.search(rf'(?<![\w.>])&\s*{re.escape(var)}\b', clean[opening:end]):
            continue
        temp = f'{var}_read'
        if re.search(rf'\b{re.escape(temp)}\b', source):
            continue
        indent = pair['indent']
        expr = re.sub(rf'(?<![\w.>]){re.escape(var)}\b', temp, pair['expr'])
        text = f'{indent}{temp} = {glob};\n{indent}{glob} = {expr};\n{indent}{var} = {temp};\n'
        declare = (opening + decl.end(), opening + decl.end(), f'{decl[1]}{decl[2]} {temp};\n')
        result.append((FAMILY, edit(source, [(pair.start(), pair.end(), text), declare])))
    return result


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}
