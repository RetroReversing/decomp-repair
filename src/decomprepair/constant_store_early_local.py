"""A literal stored after a float-to-integer conversion, held in a local set before the conversion's float arithmetic.

`(u32) f` is a branch diamond in GCC 2.7.2's MIPS output (`c.le.s` against 2^31, then one `trunc.w.s` arm or the other).
A store of a literal that follows it makes its `li` after the join, where the first scheduler cannot lift it above the
branches; the target often has that `li` in the delay slot of the diamond's `bc1t` (a register of its own for the whole
diamond), which is a literal held in a local set before the float arithmetic:

    temp_fv = (2.0f * height) - 44.0f;                 temp_k = 0x20;
    var_v1 = (u32) temp_fv;                  ->        temp_fv = (2.0f * height) - 44.0f;
    *((s16 *) (rec + 0x22)) = (s16) var_v1;            var_v1 = (u32) temp_fv;
    *((s16 *) (rec + 0x20)) = 0x20;                    *((s16 *) (rec + 0x20)) = temp_k;  *((s16 *) (rec + 0x22)) = ...;

One child per such store: the literal's local set before the statement that computes the float, the store where it was
and, in a second child, the store moved ahead of the one store of the converted value (the target stores `0x20` before
`0x22`). On a 1133-instruction effect spawner the two edits together were 6120 -> 5630 (the order alone: 6115 -> 6120).
Only a literal that is not zero (zero is `$zero`, no `li`), at most six statements after the conversion and with no call
between (a call ends the block the scheduler works in anyway).
"""
import re

from .csource import _blank, find
from .pattern_repairs import close

FAMILY = 'constant_store_early_local'
FAMILIES = (FAMILY,)
LIMIT = 6
WINDOW = 6

IDENT = r'[A-Za-z_]\w*'
CONVERSION = re.compile(r'^[ \t]*(?P<dest>' + IDENT + r')\s*=\s*\((?:u32|s32|u16|s16|u8|s8)\)\s*(?P<source>' + IDENT + r')\s*;[ \t]*$')
LITERAL_STORE = re.compile(
    r'^(?P<head>[ \t]*\*\s*\(\(\s*(?P<type>[su](?:8|16|32))\s*\*\s*\)\s*\(\(\(\s*char\s*\*\s*\)\s*[^;=]*?\)\s*\+\s*'
    r'(?:0[xX][0-9a-fA-F]+|\d+)\s*\)\s*\)\s*=\s*)(?P<value>0[xX][0-9a-fA-F]+|[1-9]\d*)[uU]?(?P<tail>\s*;[ \t]*)$')
CALL = re.compile(r'(?<![\w)])(?!(?:if|while|for|switch|return|sizeof)\b)' + IDENT + r'\s*\(')
FLOAT_DECL = re.compile(r'\b(?:f32|f64|float|double)\s+(' + IDENT + r')\s*;')


def variants(source, name):
    span = find(source, name)
    if not span:
        return []
    clean = _blank(source)
    opening = clean.find('{', span[0], span[1])
    end = close(clean, opening, '{', '}') if opening >= 0 else None
    if not end or '#' in clean[opening:end]:
        return []
    floats = set(FLOAT_DECL.findall(clean[opening:end]))
    lines = source.split('\n')
    cleaned = clean.split('\n')
    first, last = source.count('\n', 0, opening), source.count('\n', 0, end - 1)
    result = []
    for index in range(first + 1, last):
        hit = CONVERSION.match(cleaned[index])
        if not hit or hit['source'] not in floats:
            continue
        computed = next((k for k in range(index, max(first, index - 8), -1)
                         if re.match(r'^[ \t]*' + re.escape(hit['source']) + r'\s*=(?!=)', cleaned[k])), None)
        if computed is None:
            continue
        for later in range(index + 1, min(last, index + 1 + WINDOW)):
            if CALL.search(cleaned[later]) or '{' in cleaned[later] or '}' in cleaned[later]:
                break
            store = LITERAL_STORE.match(lines[later])
            if not store or int(store['value'], 0) > 0x7FFF:
                continue
            local = f'cst_{int(store["value"], 0):x}'
            if re.search(r'\b' + local + r'\b', source):
                continue
            indent = re.match(r'[ \t]*', lines[computed])[0]
            edited = list(lines)
            edited[later] = store['head'] + local + store['tail']
            edited[computed] = f'{indent}{local} = {store["value"]};\n' + lines[computed]
            edited[first] = lines[first] + f'\n  s32 {local};'
            result.append((FAMILY, '\n'.join(edited)))
            before = later - 1
            if before > index and re.search(r'\b' + re.escape(hit['dest']) + r'\b', lines[before]) \
                    and not CALL.search(cleaned[before]):
                swapped = list(edited)
                swapped[before], swapped[later] = edited[later], edited[before]
                result.append((FAMILY, '\n'.join(swapped)))
            break
        if len(result) >= LIMIT:
            break
    return result[:LIMIT]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}
