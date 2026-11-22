"""Keep the measured global-pointer snapshots across a field store and call."""
import re

from .csource import _blank
from .integer_repair_support import IDENT, NUMBER, edit, integer, view
from .mips import normalized_integer_lines
from .pattern_repairs import close

FAMILY = 'measured_field_base_lifetimes'
FAMILIES = (FAMILY,)

READ = re.compile(rf'(?<![\w.>])(?P<mode>{IDENT})\s*=\s*M2C_FIELD\(\s*(?P<global>{IDENT})\s*,\s*u8\s*\*\s*,\s*'
                  rf'(?P<offset>{NUMBER})\s*\)\s*;')
STORE_CALL = re.compile(
    rf'(?<![\w.>])M2C_FIELD\(\s*(?P<global>{IDENT})\s*,\s*u8\s*\*\s*,\s*(?P<dest>{NUMBER})\s*\)\s*=\s*'
    rf'\(u8\)\s*M2C_FIELD\(\s*(?P<arg>{IDENT})\s*,\s*u16\s*\*\s*,\s*(?P<src>{NUMBER})\s*\)\s*;\s*'
    rf'(?P<callee>{IDENT})\s*\(\s*(?P=arg)\s*,\s*(?P=global)\s*\)\s*;'
)


def variants(source, name, header, rows):
    part = view(source, name)
    if not part:
        return []
    end = close(part.clean, part.opening, '{', '}')
    if not end:
        return []
    body = part.clean[part.opening + 1:end - 1]
    if re.search(r'/\*|//|(?m:^\s*#)', source[part.opening + 1:end - 1]):
        return []
    target, candidate = ('\n'.join(normalized_integer_lines(row[side] for row in rows if row[side]))
                         for side in (1, 2))
    context = _blank(header + '\n' + source)
    macros = set(re.findall(r'(?m)^\s*#\s*(?:define|undef)\s+(' + IDENT + r')', context))
    if macros & {'u8', 'u16', 'M2C_FIELD'} != {'M2C_FIELD'} or re.search(
            r'(?m)^\s*#\s*undef\s+M2C_FIELD\b', context):
        return []
    for typ, expected in [('s8', r'(?:signed\s+)?char'), ('u8', r'unsigned\s+char'),
                          ('u16', r'unsigned\s+short(?:\s+int)?')]:
        aliases = re.findall(r'\btypedef\s+([^;{}]+?)\s+' + typ + r'\s*;', context)
        if len(aliases) != 1 or not re.fullmatch(expected, aliases[0].strip()):
            return []
    macro = re.findall(r'(?m)^\s*#\s*define\s+M2C_FIELD\(expr,\s*type_ptr,\s*offset\)\s+([^\n]+)', context)
    if len(macro) != 1 or re.sub(r'\s+', '', macro[0]) != '(*(type_ptr)((s8*)(expr)+(offset)))':
        return []
    if (re.search(r'\b(?:__repair_firstbase|__repair_storebase)\b', context)
            or re.search(r'\b(?:volatile|asm|__asm__)\b', body)
            or (macros - {'M2C_FIELD'}) & set(re.findall(IDENT, body))):
        return []
    offset = part.opening + 1
    changes = []
    reads = list(READ.finditer(body))
    for read in reads:
        g = read['global']
        if (not re.search(r'\bu8\s+' + re.escape(read['mode']) + r'\s*;', body)
                or body[:read.start()].rstrip()[-1:] not in (';', '{', '}')):
            continue
        if (g in macros or re.search(r'\b' + re.escape(g) + r'\b', part.clean[:part.opening].split('(')[-1])
                or re.search(r'\b(?:void|char|int|s32|u32)\s*\*\s*' + re.escape(g) + r'\b', body)
                or not re.search(r'\bextern\s+void\s*\*\s*' + re.escape(g) + r'\s*;', context)):
            continue
        store = re.search(rf'M2C_FIELD\(\s*(?P<global>{re.escape(g)})\s*,\s*u8\s*\*\s*,\s*'
                          rf'(?P<dest>{NUMBER})\s*\)\s*=\s*[^;{{}}]+;', body[read.end():])
        if not store:
            continue
        start, stop = read.end() + store.start(), read.end() + store.end()
        between = body[read.end():start]
        if not re.fullmatch(r'\s*' + IDENT + r'\s*=\s*[^;{}]+;\s*if\s*\(\s*'
                            + re.escape(read['mode']) + r'\s*==\s*0\s*\)\s*\{\s*', between):
            continue
        if re.search(r'\+\+|--|(?<![=!<>])=(?!=)', between[between.find('=') + 1:]):
            continue
        if any(c not in {'M2C_FIELD', 'if'} for c in re.findall(r'\b(' + IDENT + r')\s*\(', between)):
            continue
        call = re.match(r'\s*(?P<callee>' + IDENT + r')\s*\((?P<args>[^;{}]+),\s*(?P<global>'
                        + re.escape(g) + r')\s*\)\s*;', body[stop:])
        if not call or call['callee'] in macros:
            continue
        if any(c != 'M2C_FIELD' for c in re.findall(r'\b(' + IDENT + r')\s*\(', call['args'])):
            continue
        # The store's own assignment is the only permitted write.
        if re.search(r'\+\+|--|(?<![=!<>])=(?!=)', call['args'] + store[0].split('=', 1)[1]):
            continue
        dest = integer(store['dest'])
        gpat, cpat = re.escape(g), re.escape(call['callee'])
        if not re.search(rf'lui \$a2, %hi\({gpat}\)\nlw \$a2, %lo\({gpat}\)\(\$a2\).*?'
                         rf'sb \$v0, {dest}\(\$a2\).*?jal {cpat}', target, re.S):
            continue
        if not re.search(rf'sb \$v0, {dest}\(\$a2\)\nlui \$a2, %hi\({gpat}\)', candidate):
            continue
        # Only the observed use of the pre-store pointer is captured.
        changes.append([
            (offset, offset, '\n    void *__repair_firstbase;'),
            (offset + read.start(), offset + read.start(), f'__repair_firstbase = {g};\n    '),
            (offset + read.start('global'), offset + read.end('global'), '__repair_firstbase'),
            (offset + read.end() + store.start('global'), offset + read.end() + store.end('global'), '__repair_firstbase'),
            (offset + stop + call.start('global'), offset + stop + call.end('global'), '__repair_firstbase'),
        ])
        break
    second = []
    for hit in STORE_CALL.finditer(body):
        g, callee, arg = hit['global'], hit['callee'], hit['arg']
        if body[:hit.start()].rstrip()[-1:] not in (';', '{', '}'):
            continue
        if ({g, callee, arg} & macros
                or re.search(r'\b' + re.escape(g) + r'\b', part.clean[:part.opening].split('(')[-1])
                or re.search(r'\b(?:void|char|int|s32|u32)\s*\*\s*' + re.escape(g) + r'\b', body)
                or not re.search(r'\bextern\s+void\s*\*\s*' + re.escape(g) + r'\s*;', context)):
            continue
        src, dest = integer(hit['src']), integer(hit['dest'])
        if not re.search(rf'lhu \$v0, {src}\(\$a0\)\njal {re.escape(callee)}\nsb \$v0, {dest}\(\$a1\)', target):
            continue
        if not re.search(rf'sb \$v0, {dest}\(\$a1\)\nlui \$a1, %hi\({re.escape(g)}\)', candidate):
            continue
        # There are two occurrences of the global in this match.
        last = list(re.finditer(r'\b' + re.escape(g) + r'\b', hit[0]))[-1]
        second = [
            (offset, offset, '\n    void *__repair_storebase;'),
            (offset + hit.start(), offset + hit.start(), f'__repair_storebase = {g};\n        '),
            (offset + hit.start('global'), offset + hit.end('global'), '__repair_storebase'),
            (offset + hit.start() + last.start(), offset + hit.start() + last.end(), '__repair_storebase'),
        ]
        break
    out = [(FAMILY, edit(source, change)) for change in changes]
    if second:
        out.append((FAMILY, edit(source, second)))
        if changes:
            out.append((FAMILY, edit(source, changes[0] + second)))
    return out
