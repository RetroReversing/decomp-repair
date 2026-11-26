"""A loop body's reused names split by web: a block pointer reassigned per record, a constant holder shared with a count.

Two m2c-shaped reuses inside one loop body, which the game wrote as separate variables:

    for (i = k = 0; i < count; i++) {          for (i = k = 0; i < count; i++) {
        Vtx *v = &T[k++ + base];                   Vtx *v = &T[k++ + base];
        v->ob[0] = ...;                            Vtx *v2;
        v = &T[k++ + base];                        Vtx *v3;
        v->ob[0] = ...;  nv = 0x80;                s32 nv2;
        v->cn[3] = nv;                             v->ob[0] = ...;
        v = &T[k++ + base];                        v2 = &T[k++ + base];
        v->ob[0] = ...;  nv = 0;                   v2->ob[0] = ...;  nv2 = 0x80;
        v->cn[3] = nv;                             v2->cn[3] = nv2;
    }                                              v3 = &T[k++ + base];
    nv = k;                                        v3->ob[0] = ...;  nv2 = 0;
                                                   v3->cn[3] = nv2;
                                               }
                                               nv = k;

A pointer declared in the body and reassigned there is one pseudo for every record, so the first scheduler cannot start
the next record's address while the previous record's stores are still going (the anti-dependences on one register) and
the records share one register where the target has one each. A function-level local that the body only loads with
literals before reading (`nv = 0x80; v->cn[3] = nv;`, the shape `store_constant_web` writes to keep a constant from
being hoisted) and that the code after the loop sets afresh is two webs in one pseudo: the long-lived count's register
and priority are given to the in-loop constant too. One local of its own for the body's web keeps the constant in the
loop (set twice there, loop.c's `n_times_set` stops the move) in a register of its own. Reading the allocator and loop.c
this way is a hypothesis; the judge decides.

On an SN64 GCC 2.8.1 vertex builder (544 instructions) the two splits are each worse alone (1350 -> 1395, 1350 -> 2850
with the other later edits) and together 1955, from which `store_constant_web`, `statement_slide` and `dead_scratch_reuse`
reach 530 (the 0x80 kept in `$v0` inside the loop, the count copied after it, the vertex pointers in the target's
registers). So the combined child is offered beside the two single ones.

The shapes, in the block that is a `for`/`while`/`do` body (no `goto` or labels in the function):
- pointer: a declaration `T *v = expr;` among the block's leading declarations, never address-taken, assigned again only by
  plain top-level statements of the block (`v = expr;`); each later assignment starts a variable of its own (`v2`, `v3`),
  declared after the original, renamed from its own left-hand side up to the next assignment (whose right-hand side still
  reads the earlier web);
- holder: a local declared plainly at the head of the function, never address-taken and not named in the loop's header,
  that the block assigns only by top-level `x = <integer literal>;` statements (at least two), the first of which comes
  before any other mention in the block, and whose first mention after the loop (if any) is a plain assignment that does
  not read it. It gets `<x>2`, declared at the head of the block, for every mention in the block.
"""
import re

from .arm_block_support import IDENT, brace_pairs, mentions, statements
from .integer_repair_support import edit, view

FAMILY = 'loop_body_web_split'
FAMILIES = (FAMILY,)

LITERAL = r'-?(?:0[xX][0-9a-fA-F]+|\d+)[uUlL]*'
DECLARATION = re.compile(r'(?P<type>(?:(?:unsigned|signed|const|volatile|struct|union)\s+)*' + IDENT +
                         r')\s*(?P<stars>\*+)\s*(?P<name>' + IDENT + r')\s*=(?!=)\s*(?P<value>[^;{}]+);')
HEAD = re.compile(r'(?P<type>(?:(?:unsigned|signed|const|volatile|struct|union)\s+)*' + IDENT + r')\s+'
                  r'(?P<decls>\**\s*' + IDENT + r'[^;{}]*);')
PLAIN_DECLARATION = re.compile(r'(?:(?:unsigned|signed|const|volatile|struct|union)\s+)*' + IDENT +
                               r'\s*\**\s*' + IDENT + r'\s*(?:=[^;{}]*)?;')


def _fresh(clean, var, number, taken):
    """`<var><number>`, or `<var>_<number>` when that name is already in the text (a macro's parameter, say)."""
    for fresh in (f'{var}{number}', f'{var}_{number}', f'{var}_{number}_'):
        if fresh not in taken and not re.search(rf'\b{fresh}\b', clean):
            taken.add(fresh)
            return fresh
    return None


def _head_declaration(clean, part, var):
    """(type, stars) of `var` from a plain declaration among the statements that open the function body (arrays and
    initialised names beside it allowed, `var` itself a scalar or pointer without an initialiser); None otherwise."""
    for start, end in statements(clean, part.opening + 1, part.end - 1):
        text = clean[start:end].strip()
        found = HEAD.fullmatch(text)
        if not found:
            return None
        for declarator in found['decls'].split(','):
            hit = re.fullmatch(r'\s*(\**)\s*(' + IDENT + r')\s*', declarator)
            if hit and hit[2] == var:
                return found['type'].strip(), hit[1]
    return None


def _loop_head(clean, opening):
    """(start of the loop statement, header text) when the block opening at `opening` is a loop body, else None."""
    head = clean[:opening].rstrip()
    if re.search(r'\bdo$', head):
        return len(head) - 2, ''
    if not head.endswith(')'):
        return None
    depth, at = 0, len(head)
    while at > 0:
        at -= 1
        depth += (head[at] == ')') - (head[at] == '(')
        if depth == 0:
            break
    keyword = re.search(r'\b(for|while)$', clean[:at].rstrip())
    if not keyword:
        return None
    return keyword.start(), clean[at:len(head)]


def _loop_end(clean, closing, start):
    """The end of the loop statement whose body closes at `closing` (past a `do`'s `while (...);`), and its condition."""
    if not clean[start:start + 2] == 'do':
        return closing + 1, ''
    tail = re.match(r'\s*while\s*\(', clean[closing + 1:])
    if not tail:
        return None
    at, depth = closing + 1 + tail.end(), 1
    while at < len(clean) and depth:
        depth += (clean[at] == '(') - (clean[at] == ')')
        at += 1
    semi = re.match(r'\s*;', clean[at:])
    return (at + semi.end(), clean[closing + 1:at]) if semi else None


def _assigns(text, var):
    """Every write of `var` in `text`: plain and compound assignments, increments and decrements."""
    name = re.escape(var)
    return len(re.findall(rf'(?<![\w.>]){name}\s*(?:[-+*/%&|^]|<<|>>)?=(?!=)', text)
               + re.findall(rf'(?<![\w.>]){name}\s*(?:\+\+|--)', text)
               + re.findall(rf'(?:\+\+|--)\s*{name}\b', text))


def _pointer_edits(source, clean, block, units, body):
    """Edits that give each later assignment of a block-declared pointer a variable of its own, one list per pointer."""
    out = []
    declarations = []
    for start, end in units:
        if not PLAIN_DECLARATION.fullmatch(clean[start:end].strip()):
            break
        declarations.append((start, end))
    for start, end in declarations:
        hit = DECLARATION.fullmatch(clean[start:end].strip())
        if not hit:
            continue
        var = hit['name']
        if re.search(rf'&\s*{re.escape(var)}\b', body):
            continue
        sites = []
        for unit_start, unit_end in units:
            if unit_start <= start:
                continue
            text = clean[unit_start:unit_end]
            plain = re.fullmatch(rf'{re.escape(var)}\s*=(?!=)\s*([^;{{}}]+);', text.strip())
            if plain and not mentions(plain[1], var):
                sites.append((unit_start, unit_end))
            elif _assigns(text, var):
                sites = None
                break
        if not sites:
            continue
        edits, names, taken = [], [], set()
        for number, (site_start, site_end) in enumerate(sites, 2):
            fresh = _fresh(clean, var, number, taken)
            if not fresh:
                edits = None
                break
            names.append(fresh)
            stop = sites[number - 1][0] if number - 1 < len(sites) else block[1]
            lhs = site_start + clean[site_start:site_end].index(var)
            edits.append((lhs, lhs + len(var), fresh))
            for at in mentions(clean[site_end:stop], var):
                edits.append((site_end + at, site_end + at + len(var), fresh))
        if not edits:
            continue
        indent = re.match(r'[ \t]*', source[source.rfind('\n', 0, start) + 1:])[0]
        added = ''.join(f'\n{indent}{hit["type"]} {hit["stars"]}{fresh};' for fresh in names)
        edits.append((end, end, added))
        out.append(edits)
    return out


def _holder_edits(source, clean, part, block, units, header, after):
    """Edits that give a function-level constant holder's in-loop web a local of its own, one list per holder."""
    out = []
    body = clean[block[0] + 1:block[1]]
    seen = set()
    for unit_start, unit_end in units:
        for hit in re.finditer(rf'(?<![\w.>])({IDENT})\s*=(?!=)\s*{LITERAL}\s*;', clean[unit_start:unit_end]):
            var = hit[1]
            if var in seen:
                continue
            seen.add(var)
            declared = _head_declaration(clean, part, var)
            if not declared or re.search(rf'&\s*{re.escape(var)}\b', clean[part.opening:part.end]):
                continue
            if mentions(header, var):
                continue
            writes, first = 0, None
            ok = True
            for start, end in units:
                text = clean[start:end]
                if not mentions(text, var):
                    continue
                plain = re.fullmatch(rf'{re.escape(var)}\s*=(?!=)\s*{LITERAL}\s*;', text.strip())
                if first is None:
                    first = bool(plain)
                if plain:
                    writes += 1
                elif _assigns(text, var):
                    ok = False
                    break
            if not ok or not first or writes < 2:
                continue
            later = mentions(clean[after:part.end], var)
            if later:
                at = after + later[0]
                line = re.match(rf'{re.escape(var)}\s*=(?!=)\s*([^;{{}}]+);', clean[at:])
                if not line or mentions(line[1], var):
                    continue
            elif not mentions(clean[part.opening:block[0]], var):
                continue  # named nowhere but the loop: nothing shares its pseudo
            fresh = _fresh(clean, var, 2, set())
            if not fresh:
                continue
            type_, stars = declared
            edits = [(block[0] + 1 + at, block[0] + 1 + at + len(var), fresh) for at in mentions(body, var)]
            nl = clean.find('\n', block[0]) + 1
            indent = re.match(r'[ \t]*', source[nl:])[0] or '    '
            edits.append((nl, nl, f'{indent}{type_} {stars}{fresh};\n'))
            out.append(edits)
    return out


def variants(source, name):
    part = view(source, name)
    if not part:
        return []
    clean = part.clean
    body = clean[part.opening:part.end]
    pairs = brace_pairs(clean, part.opening, part.end)
    if not pairs or re.search(r'\bgoto\b', body) or any(
            hit[1] not in ('case', 'default') for hit in re.finditer(r'(?m)^[ \t]*(' + IDENT + r')[ \t]*:(?![:>])', body)):
        return []
    out = []

    def offer(edits):
        text = edit(source, edits)
        if text != source and (FAMILY, text) not in out:
            out.append((FAMILY, text))

    for block in sorted(pairs.items()):
        if block[0] == part.opening:
            continue
        loop = _loop_head(clean, block[0])
        if not loop:
            continue
        ended = _loop_end(clean, block[1], loop[0])
        if not ended:
            continue
        after, condition = ended
        units = statements(clean, block[0] + 1, block[1])
        pointers = _pointer_edits(source, clean, block, units, clean[block[0] + 1:block[1]])
        holders = _holder_edits(source, clean, part, block, units, loop[1] + condition, after)
        for edits in pointers + holders:
            offer(edits)
        if pointers and holders:
            # The splits only paid off together: one child with all of them.
            offer([item for edits in pointers + holders for item in edits])
    return out


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'order': 80}  # the registry: no caller wiring (registry.py)
