"""A pointer field read inside an `if`, read before the test as the game did.

m2c puts each load where its value is first used. The game read a structure's pointer field before testing another
field (`lw $a1, 0x6C($a0)` next to `lw $v1, 0x60($a0)`, then the branch): an N64 function was 87.3% with the read
inside the `if` and exact with it in a local before the test. Offered for a pointer field of a parameter read in an
`if`'s block whose base the function never assigns, and for one read in the condition after a store the condition
makes (m2c's `(c) || (p->n = v, …, M2C_FIELD(M2C_FIELD(arg0, void **, 0x20), …))`): gcc 2.7.2 won't move that load
above the store, where the game read it first (96.0% -> exact).
"""
import re

from .csource import _blank, find
from .pattern_repairs import close

FAMILY = 'field_load_hoist'
FAMILIES = (FAMILY,)

I = r'[A-Za-z_]\w*'


def variants(source, name):
    span = find(source, name)
    if not span:
        return []
    clean = _blank(source)
    opening = clean.find('{', span[0], span[1])
    end = close(clean, opening, '{', '}') if opening >= 0 else None
    if not end or '__repair_hoisted' in clean:
        return []
    params = set(re.findall(r'(' + I + r')\s*(?=[,)])', clean[clean.rfind('(', span[0], opening):opening]))
    result = []
    for cond in re.finditer(r'(?m)^(?P<ind>[ \t]*)if \(', clean[opening:end]):
        start = opening + cond.start()
        cond_end = close(clean, opening + cond.end() - 1)
        block = clean.find('{', cond_end) if cond_end else -1
        if block < 0 or clean[cond_end:block].strip():
            continue
        block_end = close(clean, block, '{', '}')
        cond_open = opening + cond.end() - 1
        regions = [(block, block_end)]
        if re.search(r'(?<![=!<>])=(?!=)', clean[cond_open:cond_end]):  # the condition stores before it reads
            regions.insert(0, (cond_open, cond_end))
        loads = [(at, m) for at, stop in regions
                 for m in re.finditer(r'M2C_FIELD\(\s*(?P<base>' + I + r')\s*,\s*(?P<type>[\w ]+\*\s*\*)\s*,\s*(?P<off>0x[0-9a-fA-F]+|\d+)\s*\)',
                                      clean[at:stop])]
        for at, load in loads:
            if at != block and not re.search(r'(?<![=!<>])=(?!=)', clean[cond_open:at + load.start()]):
                continue  # (in the condition, only a load after its store)
            base = load['base']
            if base not in params or re.search(r'(?<![=!<>])\b' + base + r'\s*=(?!=)', clean[opening:end]):
                continue
            pointee = load['type'].strip()[:-1].strip()
            expr = source[at + load.start():at + load.end()]
            ind = cond['ind']
            text = (source[:start] + f'{ind}__repair_hoisted = {expr};\n' + source[start:at + load.start()]
                    + '__repair_hoisted' + source[at + load.end():])
            text = text[:opening + 1] + f'\n    {pointee} __repair_hoisted;\n' + text[opening + 1:]
            result.append((FAMILY, text))
            break
        if len(result) >= 3:
            break
    return result
