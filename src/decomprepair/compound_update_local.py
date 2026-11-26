"""A global's or field's compound update (`G.count += n * 12;`) written through a local updated in its own statement.

`D.f += e;` expands to a load into a new pseudo, an add into another pseudo set exactly once, and the store. Before reload
GCC's first scheduler boosts an insn whose destination is a pseudo set once (`sched.c`, `birthing_insn_p` and
`adjust_priority`: the `7f000001` launch priority in the `-dS` notes), so the add, and the chain feeding it, is placed
wherever its store makes it ready, ahead of ordinary insns of the same priority. Written as a local
(`t = D.f; t += e; D.f = t;`), the add sets a pseudo with two sets, which gets no boost, and the other insns of the block
(a value the next call's argument and a later sum both read) keep their place beside the update.

On a 182-instruction SN64 GCC 2.8.1 allocator (`-G0 -mips3 -O2 -mfp64`, sn-n64-281) an update of a header's byte count
(`hdr.used += count * 12;`) sat in the block that also scales `count` by 8 for a call argument and a running end: with the
compound update, the boosted add chain left the shift ahead of it (945); through a local, the shift followed the update
and the function went 945 -> 145, with no do-while fence (the saved best's earlier 270 relied on one). The `sched.c`
reading is from the compiler's source and the `-dS` dumps of both spellings; the judge decides.

compound_update_local
    `LV op= E;` (op one of `+ - | & ^ << >> *`), or `LV = LV + E;` / `LV = LV - E;` with no operator of lower precedence
    at the top level of E, where LV is a global, a member of one (`G.f`, `p->f`), an element (`G[i]`) or a typed
    dereference (`*(T *)(...)`) of an integer type the header or the file declares, and neither LV nor E calls, assigns
    or increments, becomes `t = LV; t op= E; LV = t;` with `t` a new local of LV's type. One child per site with the
    local declared after the function's last leading declaration and one with it first; one child with every site
    respelled, a local each (at most 24 children).
"""
import re

from .arm_block_support import brace_pairs, statements
from .compiler_shape_repairs import fields
from .csource import _blank
from .integer_abi import scalar
from .integer_repair_support import IDENT, edit, view

FAMILY = 'compound_update_local'
FAMILIES = (FAMILY,)
LIMIT = 24
OPS = r'(?:<<|>>|[-+|&^*])'
TYPE = rf'(?:(?:unsigned|signed)\s+)?{IDENT}'
DECLARATION = re.compile(rf'(?:(?:static|register|unsigned|signed|const|struct|union)\s+)*{IDENT}[\s*]+{IDENT}'
                         rf'(?:\s*\[[^;\]]*\])?\s*(?:=[^;]*)?;')
STATEMENT_WORDS = {'return', 'goto', 'break', 'continue', 'case', 'default', 'if', 'else', 'do', 'while', 'for',
                   'switch'}


def _side_effect_free(text):
    """No calls, assignments, increments or comma expressions (a cast's parenthesised type is fine)."""
    if re.search(r'\+\+|--|,|[;{}?]|(?<![=!<>])=(?!=)', text):
        return False
    return all(hit[1] == 'sizeof' for hit in re.finditer(rf'\b({IDENT})\s*\(', text))


def _top_level(text):
    """`text` with every parenthesised or bracketed group blanked, to read its top-level operators."""
    out, depth = [], 0
    for char in text:
        if char in '([':
            depth += 1
        elif char in ')]':
            depth -= 1
            char = ' '
        out.append(char if depth == 0 else ' ')
    return ''.join(out)


KNOWN = {'s8', 'u8', 's16', 'u16', 's32', 'u32', 'char', 'short', 'int', 'long', 'unsigned char', 'unsigned short',
         'unsigned int', 'unsigned long', 'signed char', 'signed short', 'signed int', 'unsigned', 'signed'}


def _integer(spelling, context, arch):
    """The spelling when it is an integer type (the project's own `s32`-style names when no header comes with it)."""
    spelling = ' '.join(spelling.split())
    return spelling if scalar(spelling, context, arch) or spelling in KNOWN else None


def _local(part, ident):
    """`ident` is declared in the function or its parameters: not a global."""
    signature = part.clean[:part.opening].rsplit('(', 1)[-1]
    return bool(re.search(rf'[\w*]\s*\b{re.escape(ident)}\s*(?=[;=,)\[])', signature + ';' + part.body))


def _extern(context, ident):
    """(element type, is an array) of a file-scope object `ident`, when its declarations agree."""
    found = {(' '.join(hit[1].split()), bool(hit[2]))
             for hit in re.finditer(rf'(?m)^\s*(?:extern\s+|static\s+)?({TYPE})\s+{re.escape(ident)}\s*(\[[^\]]*\])?'
                                    rf'\s*(?:=[^;]*)?;', context)}
    return found.pop() if len(found) == 1 else None


def _type(part, lvalue, header, arch):
    """The integer type of an lvalue that names memory (never a local variable), or None."""
    context = _blank(header or '') + '\n' + part.clean[:part.opening]
    text = ' '.join(lvalue.split())
    if text.startswith('*'):
        cast = re.match(rf'\*\s*\(\s*\(?\s*({TYPE})\s*\*\s*\)', text)
        return _integer(cast[1], context, arch) if cast else None
    member = re.fullmatch(rf'({IDENT})\s*(\.|->)\s*({IDENT})', text)
    if member:
        if member[2] == '.':
            if _local(part, member[1]):
                return None
            records = {hit[1] for hit in re.finditer(rf'(?m)^\s*(?:extern\s+)?({IDENT})\s+{re.escape(member[1])}\s*;',
                                                     context)}
        else:
            signature = part.clean[:part.opening].rsplit('(', 1)[-1]
            records = {hit[1] for hit in re.finditer(rf'\b({IDENT})\s*\*\s*{re.escape(member[1])}\s*(?=[;=,)])',
                                                     signature + ';' + part.body)}
        if len(records) != 1:
            return None
        record = records.pop()
        types = {t for name, t, field, _ in fields(context) if name == record and field == member[3]}
        return _integer(types.pop(), context, arch) if len(types) == 1 else None
    element = re.fullmatch(rf'({IDENT})\s*\[([^\[\]]+)\]', text)
    if element:
        declared = None if _local(part, element[1]) else _extern(context, element[1])
        return _integer(declared[0], context, arch) if declared and declared[1] else None
    if re.fullmatch(IDENT, text) and not _local(part, text):
        declared = _extern(context, text)
        return _integer(declared[0], context, arch) if declared and not declared[1] else None
    return None


def _sites(part, header, arch):
    clean = part.clean
    pairs = brace_pairs(clean, part.opening, part.end)
    if not pairs:
        return []
    sites = []
    for block_open, block_close in sorted(pairs.items()):
        for start, end in statements(clean, block_open + 1, block_close):
            text = clean[start:end].strip()
            word = re.match(IDENT, text)
            if word and word[0] in STATEMENT_WORDS:
                continue
            hit = re.fullmatch(rf'(?P<lv>[^;{{}}=]+?)\s*(?P<op>{OPS})=\s*(?P<e>[^;{{}}]+?)\s*;', text, re.S)
            if not hit:
                hit = re.fullmatch(r'(?P<lv>[^;{}=]+?)\s*=(?!=)\s*(?P<lv2>[^;{}=]+?)\s*(?P<op>[-+])\s*'
                                   r'(?P<e>[^;{}]+?)\s*;', text, re.S)
                if not hit or ' '.join(hit['lv'].split()) != ' '.join(hit['lv2'].split()):
                    continue
                # `LV = LV + a | b` is `(LV + a) | b`: only a term or a product goes into `t += E`.
                if re.search(r'[-+|&^<>]', _top_level(hit['e'])):
                    continue
            lv, e = hit['lv'].strip(), hit['e'].strip()
            if not (_side_effect_free(lv) and _side_effect_free(e)):
                continue
            typ = _type(part, lv, header, arch)
            if typ:
                sites.append((start, end, lv, hit['op'], e, typ))
    return sites


def _declaration_places(part, source):
    """Insertion offsets after the function's last leading declaration and before its first, with their indentation."""
    clean = part.clean
    last = None
    for start, end in statements(clean, part.opening + 1, part.end - 1):
        text = clean[start:end].strip()
        word = re.match(IDENT, text)
        if not word or word[0] in STATEMENT_WORDS or not DECLARATION.fullmatch(text):
            break
        last = end
    first_line = clean.find('\n', part.opening) + 1
    indent = re.match(r'[ \t]*', source[first_line:])[0] or '    '
    places = []
    if last is not None:
        line_end = clean.find('\n', last)
        places.append(line_end + 1 if line_end >= 0 else last)
    places.append(first_line)
    return places, indent


def variants(source, name, header='', arch='mips'):
    part = view(source, name)
    if not part or not part.body.strip():
        return []
    sites = _sites(part, header, arch)
    if not sites:
        return []
    names = []
    for number in range(1, len(sites) + 1):
        fresh = f'upd{number}'
        if re.search(rf'\b{fresh}\b', part.clean) or re.search(rf'\b{fresh}\b', header or ''):
            return []
        names.append(fresh)
    places, indent = _declaration_places(part, source)

    def steps(site, local):
        start, end, lv, op, e, _ = site
        line = source.rfind('\n', 0, start) + 1
        own = re.match(r'[ \t]*', source[line:start])[0] if not source[line:start].strip() else indent
        return (start, end, f'{local} = {lv};\n{own}{local} {op}= {e};\n{own}{lv} = {local};')

    out = []
    for number, site in enumerate(sites):
        for place in places:
            result = edit(source, [steps(site, names[number]), (place, place, f'{indent}{site[5]} {names[number]};\n')])
            if result != source and (FAMILY, result) not in out:
                out.append((FAMILY, result))
    if len(sites) > 1:
        edits = [steps(site, names[number]) for number, site in enumerate(sites)]
        edits += [(places[0], places[0], f'{indent}{site[5]} {names[number]};\n') for number, site in enumerate(sites)]
        result = edit(source, edits)
        if result != source and (FAMILY, result) not in out:
            out.append((FAMILY, result))
    return out[:LIMIT]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name', 'header', 'arch'),
          'order': 89}  # the registry: no caller wiring (registry.py)
