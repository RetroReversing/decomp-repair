"""m2c's shift pair of a value just stored in a halfword, written as the halfword read back.

The game stored a value in a 16-bit field and read the field again:

    vp[0] = x * 2;  ...  D_A = vp[0] >> 2;  D_B = vp[0] >> 2;

gcc forwards the stored register to the read and extends its low half where it lies (`sll 17; sra 18`), so m2c names
neither the field nor the read: it names the product and writes the extension as a shift pair of the argument:

    temp_v0 = x * 2;  F = temp_v0;  ...
    temp_a0 = (s32) (x << 0x11) >> 0x12;  D_A = (s16) temp_a0;  D_B = (s16) temp_a0;

`(x << (16 + k)) >> (16 + n)` is `(s16) (x << k) >> n`, so when `x << k` (or `x * 2**k`) was stored in a halfword
lvalue `F` earlier in the same run of statements, the pair is `F >> n`. A view setup on SN GCC 2.8.1 (`-G0 -mips3 -O2
-mfp64`, 35 instructions, two such pairs) went 910 -> 60 with the read-back written at each use and 0 with the product
locals also written into their stores. The read-back alone, behind the local that held the pair, stayed at 910, and
the product locals alone gave 850, so the combined child is offered first.

Only lvalues whose address the text shows apart are followed: a halfword global declared in the source, or a halfword
field of a global at a constant offset. Between the store and the read there may be only plain assignments: no call,
no braces, no write to `F` or to `x`, and no store through anything but another global or global field.
"""
import re

from .csource import _blank, find
from .pattern_repairs import close

FAMILY = 'stored_narrow_readback'
FAMILIES = (FAMILY,)

IDENT = r'[A-Za-z_]\w*'
NUMBER = r'(?:0x[0-9A-Fa-f]+|\d+)'
DECLARATION = re.compile(r'(?:s8|u8|s16|u16|s32|u32|int|short|char)\s+\**' + IDENT)
SHIFT_PAIR = re.compile(r'(?:\(\s*(?:s32|int)\s*\)\s*)?\(\s*(?P<var>' + IDENT + r')\s*<<\s*(?P<up>' + NUMBER
                        + r')\s*\)\s*>>\s*(?P<down>' + NUMBER + r')(?![\w.])')
FIELD = re.compile(r'M2C_FIELD\s*\(\s*&\s*(?P<symbol>' + IDENT + r')\s*,\s*(?P<type>s16|u16)\s*\*\s*,\s*(?P<offset>'
                   + NUMBER + r')\s*\)')
ASSIGN = re.compile(r'(?s)(?P<left>.+?)(?<![=!<>+\-*/&|^%])=(?!=)\s*(?P<right>.+)')
PRODUCT = re.compile(r'(?P<var>' + IDENT + r')\s*(?P<op>\*|<<)\s*(?P<by>' + NUMBER + r')')


def _number(text):
    return int(text, 0)


def _product(text):
    """(variable, k) for `v * 2**k` or `v << k`, else None."""
    found = PRODUCT.fullmatch(text.strip())
    if not found:
        return None
    by = _number(found['by'])
    if found['op'] == '<<':
        return (found['var'], by) if by < 16 else None
    if by < 2 or by & (by - 1) or by > 0x8000:
        return None
    return found['var'], by.bit_length() - 1


def _place(text, halfwords):
    """A key for an lvalue whose address the text shows apart, and the signedness of a halfword one."""
    text = text.strip()
    field = FIELD.fullmatch(text)
    if field:
        return (field['symbol'], _number(field['offset'])), field['type']
    if re.fullmatch(IDENT, text):
        return (text, None), halfwords.get(text)
    return None, None


def _statements(clean, start, end):
    """The (start, end) of each `...;` in the body, end past the semicolon, comments and spaces skipped."""
    found = []
    for match in re.finditer(r'[^;{}]*[;{}]', clean[start:end]):
        text = match[0]
        begin = start + match.start() + len(text) - len(text.lstrip())
        found.append((begin, start + match.end()))
    return found


def _reads(source, clean, opening, end, halfwords, local_names):
    """Each shift pair with the stored halfword it extends: (start, end, replacement, key)."""
    rows = []
    stored = {}   # (variable, k) -> (key, lvalue text, type)
    held = {}     # local -> (variable, k) it holds
    for begin, stop in _statements(clean, opening + 1, end - 1):
        code = clean[begin:stop]
        if code[-1] != ';' or re.search(r'\b(?:if|else|for|while|do|switch|case|goto|return|break|continue)\b|:|\+\+|--', code):
            stored.clear()
            held.clear()
            continue
        pairs = list(SHIFT_PAIR.finditer(code))
        for pair in pairs:
            up = _number(pair['up'])
            down = _number(pair['down'])
            known = stored.get((pair['var'], up - 16))
            if known and 16 <= down < 32:
                read = known[1] if known[2] == 's16' else f'(s16) {known[1]}'
                amount = down - 16
                rows.append((begin + pair.start(), begin + pair.end(), f'{read} >> {amount}' if amount else read,
                             known[0]))
        if _calls(code):
            stored.clear()
            held.clear()
            continue
        found = ASSIGN.fullmatch(code[:-1].strip())
        if not found and DECLARATION.fullmatch(code[:-1].strip()):
            continue
        if not found or re.search(r'(?<![=!<>])=(?!=)', found['right']):
            # a bare expression, or a chain of assignments whose inner writes are not followed
            stored.clear()
            continue
        left = found['left'].strip()
        right = found['right'].strip()
        declared = re.fullmatch(r'(?:s16|u16|s32|u32|int|short)\s+(' + IDENT + r')', left)
        name = declared[1] if declared else left
        key, kind = _place(left, halfwords)
        product = _product(right) or held.get(right)
        if re.fullmatch(IDENT, name) and name in local_names:
            for value, (other, _, _) in list(stored.items()):
                if value[0] == name:
                    del stored[value]
            held.pop(name, None)
            for other, value in list(held.items()):
                if value[0] == name:
                    del held[other]
            if product and product[0] != name:
                held[name] = product
            continue
        if key is None:
            # a store through a pointer, an index or a member may be anything
            stored.clear()
            continue
        for value, (other, _, _) in list(stored.items()):
            if other == key or value[0] == key[0] or other[0] == key[0] and (key[1] is None or other[1] is None):
                del stored[value]
        if kind and product and product not in stored:
            stored[product] = (key, left, kind)
    return rows


def _calls(code):
    """Whether the statement calls something: a name or a dereferenced pointer followed by `(`."""
    return bool(re.search(IDENT + r'\s*\(|\(\s*\*[^()]*\)\s*\(', FIELD.sub('F', code)))


def _locals(text):
    return [m[1] for m in re.finditer(r'(?m)^[ \t]*(?:s16|u16|s32|u32|int|short)\s+(' + IDENT + r')\s*;[ \t]*\n', text)]


def _declaration(text, local):
    return re.search(r'(?m)^[ \t]*(?:s16|u16|s32|u32|int|short)\s+' + local + r'\s*;[ \t]*\n', text)


def _through_local(text, name):
    """`t = F >> n; A = (s16) t; B = (s16) t;` as `A = F >> n; B = F >> n;` for every such local."""
    for local in _locals(text):
        span = find(text, name)
        clean = _blank(text)
        word = r'(?<![\w.>])' + local + r'\b'
        mentions = list(re.finditer(word, clean[span[0]:span[1]]))
        sets = list(re.finditer(word + r'\s*=(?!=)\s*(?P<value>(?:\(s16\) )?M2C_FIELD\([^;]*;|(?:\(s16\) )?'
                                + IDENT + r'(?: >> \d+)?;)', clean[span[0]:span[1]]))
        uses = list(re.finditer(r'(?<![=!<>])=\s*(?P<use>(?:\(\s*s16\s*\)\s*)?' + word + r')\s*;', clean[span[0]:span[1]]))
        if len(sets) != 1 or not uses or len(mentions) != 2 + len(uses) or '>>' not in sets[0]['value']:
            continue
        value = text[span[0] + sets[0].start('value'):span[0] + sets[0].end('value') - 1]
        edits = [(span[0] + use.start('use'), span[0] + use.end('use'), value) for use in uses]
        line = text.rfind('\n', 0, span[0] + sets[0].start()) + 1
        edits.append((line, span[0] + sets[0].end() + 1, ''))
        declared = _declaration(text, local)
        edits.append((declared.start(), declared.end(), ''))
        for a, b, new in sorted(edits, reverse=True):
            text = text[:a] + new + text[b:]
    return text


def _inline_products(text, name):
    """A local that only carries `v * 2**k` into stores, written into those stores."""
    for local in _locals(text):
        span = find(text, name)
        clean = _blank(text)
        body = clean[span[0]:span[1]]
        word = r'(?<![\w.>])' + local + r'\b'
        sets = list(re.finditer(r'(?m)^[ \t]*' + word + r'\s*=(?!=)\s*(?P<value>[^;]*);[ \t]*\n', body))
        if len(sets) != 1:
            continue
        product = _product(sets[0]['value'])
        if not product:
            continue
        uses = list(re.finditer(r'(?<![=!<>])=\s*(?P<use>' + word + r')\s*;', body))
        if not uses or len(re.findall(word, body)) != 2 + len(uses):
            continue
        if re.search(r'(?<![\w.>])' + product[0] + r'\s*(?:[+\-*/&|^]|<<|>>)?=(?!=)', body[sets[0].end():]):
            continue
        value = sets[0]['value'].strip()
        edits = [(span[0] + use.start('use'), span[0] + use.end('use'), value) for use in uses]
        edits.append((span[0] + sets[0].start(), span[0] + sets[0].end(), ''))
        declared = _declaration(text, local)
        edits.append((declared.start(), declared.end(), ''))
        for a, b, new in sorted(edits, reverse=True):
            text = text[:a] + new + text[b:]
    return text


def variants(source, name):
    span = find(source, name)
    if not span:
        return []
    clean = _blank(source)
    opening = clean.find('{', span[0], span[1])
    end = close(clean, opening, '{', '}') if opening >= 0 else None
    if not end:
        return []
    halfwords = {m[2]: m[1] for m in re.finditer(r'\bextern\s+(s16|u16)\s+(' + IDENT + r')\s*;', clean)}
    body = clean[opening:end]
    local_names = set(re.findall(r'(?:\b(?:s8|u8|s16|u16|s32|u32|int|short|char)\s+)(' + IDENT + r')\s*(?=[;=,)])',
                                 clean[span[0]:end]))
    if '>>' not in body or '<<' not in body:
        return []
    rows = _reads(source, clean, opening, end, halfwords, local_names)
    if not rows:
        return []
    plain = source
    for a, b, new, _ in sorted(rows, reverse=True):
        plain = plain[:a] + new + plain[b:]
    through = _through_local(plain, name)
    result = []
    for text in (_inline_products(through, name), through, _inline_products(plain, name), plain):
        if text != source and text not in [seen for _, seen in result]:
            result.append((FAMILY, text))
    return result


REPAIR = {
    'families': FAMILIES,
    'variants': variants,
    'needs': ('source', 'name'),
}
