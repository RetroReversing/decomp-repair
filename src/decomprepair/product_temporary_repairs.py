"""Stage a repeated scaled index in a block-local temporary at its later use.

m2c names a record offset once (`arg0 = idx * 0x1a0;`) and writes the same product again where the loop advances
(`handle = *(s32 *)(D_8010D734 + idx * 0x1a0);`). In a 312-byte N64 voice-list walk (KMC GCC 2.7.2) the target kept
that second product in its own register: written as `{ s32 t = idx * 0x1a0; handle = *(s32 *)(D_8010D734 + t); }`
the function matched from 623 (after its call-site constants were inlined, a neutral step). A product in a fresh
block-local pseudo is local to its block, so local-alloc ties it instead of cse reusing the earlier offset's register.
"""
import re

from .integer_repair_support import edit, view

FAMILY = 'product_temporary'
FAMILIES = (FAMILY,)
_PRODUCT = r'(\w+)\s*\*\s*(0[xX][0-9a-fA-F]+|[0-9]+)\b'


def variants(source, name, limit=4):
    part = view(source, name)
    if not part:
        return []
    clean, base = part.clean, part.opening + 1
    body = clean[base:part.end]
    named = {(m[2], m[3].lower()) for m in re.finditer(rf'(?m)^[ \t]*(?:[\w ]+\s)?(\w+)\s*=\s*{_PRODUCT}\s*;', body)}
    result, used = [], set()
    for line in re.finditer(r'(?m)^([ \t]*)([^\n;{}]*;)[ \t]*$', body):
        statement = line[2]
        if re.match(r'\s*(?:return|if|while|for|do|goto|case|default)\b', statement):
            continue
        for product in re.finditer(_PRODUCT, statement):
            key = (product[1], product[2].lower())
            # only a product the function already named elsewhere, and never that naming assignment itself
            if key not in named or re.match(rf'\s*(?:[\w ]+\s)?\w+\s*=\s*{re.escape(product[0])}\s*;', statement):
                continue
            if key in used or not re.search(r'[+\[]\s*$', statement[:product.start()]):
                continue
            used.add(key)
            start = base + line.start(2)
            stop = base + line.end(2)
            original = source[start:stop]
            inner = original[:product.start()] + '__product' + original[product.end():]
            replacement = '{ s32 __product = ' + product[0] + '; ' + inner + ' }'
            result.append((FAMILY, edit(source, [(start, stop, replacement)])))
            break
        if len(result) >= limit:
            break
    return result
