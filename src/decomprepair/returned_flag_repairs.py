"""A result flag m2c carries to one `return v;`, returned where it's decided instead.

m2c turns a function's several `return 0;` / `return 1;` into one variable:

    var_v0 = 0;
    if (a) {
        var_v0 = 0;
        if (b) {
            var_v0 = 1;
            p->x = -p->x;
        }
    }
    return var_v0;

gcc 2.7.2 then keeps the flag in another register and copies it to `$v0` at the end; an N64 function was 80.7% so
and exact as `if (a) { if (b) { p->x = -p->x; return 1; } } return 0;`. A constant assigned in a block that ends
the function's work (only closing braces stand between the block and the `return`) is returned at the block's end;
when what's left assigns one constant, the final return returns it.
"""
import re

from .csource import _blank, find
from .pattern_repairs import close

FAMILY = 'returned_flag'
FAMILIES = (FAMILY,)

IDENT = r'[A-Za-z_]\w*'
NUMBER = r'-?(?:0[xX][0-9a-fA-F]+|\d+)[uU]?'


def variants(source, name):
    span = find(source, name)
    if not span:
        return []
    clean = _blank(source)
    opening = clean.find('{', span[0], span[1])
    end = close(clean, opening, '{', '}') if opening >= 0 else None
    if not end:
        return []
    final = re.search(r'\n([ \t]*)return\s+(' + IDENT + r')\s*;\s*\}\s*$', clean[opening:end])
    if not final:
        return []
    var = final[2]
    final_at = opening + final.start() + 1
    body = clean[opening:end]
    mentions = [m for m in re.finditer(r'(?<![\w.>])' + var + r'\b', body)]
    stores = list(re.finditer(r'(?m)^[ \t]*' + var + r'\s*=\s*(' + NUMBER + r')\s*;[ \t]*\n', body))
    declared = re.search(r'(?m)^[ \t]*[\w ]+?\s+' + var + r'\s*;[ \t]*\n', body)
    # the variable is declared, stored only with constants, and read only by the final return
    if not declared or not stores or len(mentions) != len(stores) + 2:
        return []
    edits, kept = [], []
    for store in stores:
        at = opening + store.start()
        block = clean.rfind('{', opening, at)
        # the innermost block the store is in, and what follows its closing brace up to the final return
        depth, scan = 0, at
        while scan > opening:
            scan -= 1
            if clean[scan] == '}':
                depth += 1
            elif clean[scan] == '{':
                if depth == 0:
                    break
                depth -= 1
        block = scan
        block_end = close(clean, block, '{', '}')
        if block == opening or not block_end:
            kept.append(store)
            continue
        rest = clean[opening + store.end():block_end - 1]
        tail = clean[block_end:final_at]
        if re.search(r'\b' + var + r'\b', rest) or tail.strip('} \t\n') or re.search(r'\belse\b', tail):
            kept.append(store)
            continue
        indent = re.match(r'[ \t]*', store.group(0))[0]
        edits.append((at, opening + store.end(), ''))
        brace_line = clean.rfind('\n', 0, block_end - 1) + 1
        edits.append((brace_line, brace_line, f'{indent}return {store[1]};\n'))
    if not edits:
        return []
    values = {s[1] for s in kept}
    if len(values) != 1:
        return []  # (what's left must return one constant)
    value = values.pop()
    for store in kept:
        edits.append((opening + store.start(), opening + store.end(), ''))
    edits.append((opening + declared.start(), opening + declared.end(), ''))
    returned = re.compile(r'return\s+' + var + r'\s*;').search(clean, final_at)
    edits.append((returned.start(), returned.end(), f'return {value};'))
    text = source
    for a, b, insert in sorted(edits, reverse=True):
        text = text[:a] + insert + text[b:]
    return [(FAMILY, text)] if text != source else []
