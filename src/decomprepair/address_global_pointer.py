"""A global word m2c declared `s32` that the function only uses as the base of an address, declared `u8 *`.

m2c writes `extern s32 D_80090000;` for a global it only ever adds offsets to and hands on as an address. The sums are
the same bytes' arithmetic either way, but a pointer global is another alias class to GCC: loads of it can pass stores
through other pointers, and the register order follows (a 46-instruction N64 matrix routine, SN GCC 2.8.1 `-O2`:
1180 -> 920 alone, 570 -> 0 as the last step).

Only an `extern` written in the candidate itself is changed, and only when every mention of the global in the function
is the left operand of a `+`. Children (`address_global_pointer`): each such global alone, then all of them.
"""
import re

from .csource import _blank, find

FAMILY = 'address_global_pointer'
FAMILIES = (FAMILY,)
IDENT = r'[A-Za-z_]\w*'
DECLARATION = re.compile(rf'(?m)^[ \t]*extern[ \t]+(?P<kind>M2C_UNK(?:32)?|s32|u32|int)[ \t]+(?P<name>{IDENT})[ \t]*;')
BEFORE = re.compile(r'(?:[(,;{}]|(?<![=!<>+\-*/%&|^])=|\breturn)\s*$')
AFTER = re.compile(r'\s*\+(?![+=])')


def _base_only(body, name):
    mentions = list(re.finditer(rf'(?<![\w.>])\b{name}\b', body))
    return bool(mentions) and all(AFTER.match(body, mention.end()) and BEFORE.search(body[:mention.start()])
                                  for mention in mentions)


def variants(source, name, header=''):
    span = find(source, name)
    if not span:
        return []
    clean = _blank(source)
    body = clean[clean.find('{', span[0], span[1]):span[1]]
    shared = _blank(header or '')
    found = {}
    for declaration in DECLARATION.finditer(clean[:span[0]]):
        symbol = declaration['name']
        if not re.search(rf'\b{symbol}\b', shared) and _base_only(body, symbol):
            found[symbol] = (declaration.start('kind'), declaration.start('name'))
    groups = [[symbol] for symbol in found]
    if len(found) > 1:
        groups.append(list(found))
    result = []
    for group in groups:
        text = source
        for start, end in sorted((found[symbol] for symbol in group), reverse=True):
            text = text[:start] + 'u8 *' + text[end:]
        result.append((FAMILY, text))
    return result


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'header')}
