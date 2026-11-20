"""Bounded reordering of independent, ordinary field loads into float locals."""
import re

from .call_lifetime_repairs import block_path
from .integer_repair_support import IDENT, edit, view

FAMILY = 'floating_initializer_order'
LIMIT = 8
FLOAT = r'(?:float|double|f32|f64)'
FIELD = rf'(?:{IDENT}\s*->\s*{IDENT})'
LOAD = re.compile(rf'(?:(?P<type>{FLOAT})\s+)?(?P<name>{IDENT})\s*=\s*(?P<expr>{FIELD})\s*;')
DECL = re.compile(rf'{FLOAT}\s+(?P<name>{IDENT})\s*;')
DECLARATOR = re.compile(rf'(?P<name>{IDENT})\s*=\s*(?P<expr>{FIELD})')
GROUPED = re.compile(rf'\b(?P<type>{FLOAT})\s+(?P<items>{IDENT}\s*=\s*{FIELD}(?:\s*,\s*{IDENT}\s*=\s*{FIELD})+)\s*;')


def variants(source, name, header=''):
    part = view(source, name)
    if not part or re.search(r'\b(?:asm|__asm__|goto|volatile)\b', part.clean):
        return []
    from .csource import _blank, find
    from .pointer_pair_repairs import qualified_types

    context = _blank(header) + '\n' + part.clean
    signature = part.clean[find(source,name)[0]:part.opening]
    qualified = qualified_types(context)
    macros = set(re.findall(r'^\s*#\s*define\s+('+IDENT+r')',context,re.M))
    if re.search(r'\b__LINE__\b', context):
        return []
    bases = {m[2] for m in re.finditer(rf'\b(?:struct\s+)?({IDENT})\s*\*\s*({IDENT})\s*(?=[,)])',signature)
             if m[1] not in qualified and m[1] not in macros}
    locals_ = {m['name']:m.end() for m in DECL.finditer(part.clean,part.opening+1,part.end-1)
               if block_path(part,m.start()) == [part.opening]}
    def is_top_level(start):
        return (part.clean[part.opening+1:start].rstrip()[-1:] in ('', ';')
                and block_path(part,start) == [part.opening])

    def ordinary_load(hit):
        return (re.match(IDENT,hit['expr'])[0] in bases
                and not set(re.findall(IDENT,hit[0])) & (qualified | macros))

    groups = []
    for hit in LOAD.finditer(part.clean,part.opening+1,part.end-1):
        start = hit.start()
        if (not is_top_level(start) or not ordinary_load(hit)
                or (not hit['type'] and locals_.get(hit['name'],part.end) >= start)):
            continue
        if groups and not source[groups[-1][-1].end():start].strip():
            groups[-1].append(hit)
        else:
            groups.append([hit])
    # One declaration shares its type specifier. Reorder the declarators
    # only, retaining both the common specifier and the declaration boundary.
    for statement in GROUPED.finditer(part.clean,part.opening+1,part.end-1):
        if not is_top_level(statement.start()) or statement['type'] in qualified | macros:
            continue
        group = list(DECLARATOR.finditer(part.clean,*statement.span('items')))
        if all(ordinary_load(hit) for hit in group):
            groups.append(group)
    groups.sort(key=lambda group: group[0].start())
    candidates = []
    for group in groups:
        if len(group)<2 or len({hit['name'] for hit in group}) != len(group):
            continue
        if {hit['name'] for hit in group} & {re.match(IDENT,hit['expr'])[0] for hit in group}:
            continue
        # Bring each load forward once. Preserve statement content, output
        # stores, and intervening whitespace to keep debug-line controls useful.
        orders = [[hit, *group[:i], *group[i+1:]] for i,hit in enumerate(group[1:5], 1)]
        for i in range(1,min(5,len(group))):
            order = list(group)
            order[i-1],order[i] = order[i],order[i-1]
            orders.append(order)
        for order in orders:
            changed = edit(source, [(old.start(),old.end(),source[new.start():new.end()])
                                    for old,new in zip(group,order) if old is not new])
            if changed not in candidates:
                candidates.append(changed)
            if len(candidates) >= LIMIT:
                return [(FAMILY,candidate) for candidate in candidates]
    return [(FAMILY,candidate) for candidate in candidates]
