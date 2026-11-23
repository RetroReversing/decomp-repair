"""A pointer local assigned twice in one block, split into one variable per assignment.

m2c reuses a pointer local for two unrelated lookups of the same shape:

    tbl = &sTable[id];  tbl->a = 1;  ...  tbl = &sTable[id];  tbl->b &= ~7;

One name is one pseudo register, with the reference counts and the lifetime of both uses; global.c ranks it by
`floor_log2 (refs) * refs / live length` and its copy preferences (an argument register wanted by one use) apply to the
other as well. The game's two lookups were two variables, one in `$v1` and one in `$a0`. A 795-instruction N64 object
spawner's saved best (3545) had the second lookup's `$a1` preference pulling the first lookup's pointer into `$a1`; with
the second lookup renamed it was 2435 and the two pointers sat where the target has them. The reading of global.c is a
hypothesis; the judge decides.

The shape: a local pointer, declared in a plain one-name declaration at the head of the function body and never
address-taken, that is assigned by two or more statements of one block (the block of the second assignment, no loop or label
around it), with the name mentioned between them. One child per later assignment declares `<name>2` (`<name>3`, ...)
with the same type, assigns it there and renames every later mention of the name inside that block. A mention after the
block closes stops the rewrite (the paths that skip the block would read the new name uninitialised).
"""
import re

from .arm_block_support import IDENT, brace_pairs, local_declaration, mentions, statements
from .integer_repair_support import edit, view

FAMILY = 'local_pointer_web_split'
FAMILIES = (FAMILY,)

LOOPS = re.compile(r'\b(?:for|while|do)\b')


def _enclosing(pairs, at):
    """The (open, close) of the innermost block that holds position `at`."""
    best = None
    for opening, closing in pairs.items():
        if opening < at < closing and (best is None or opening > best[0]):
            best = (opening, closing)
    return best


def _in_loop(clean, pairs, block, function_open):
    """Whether `block` sits in a loop body (or a block that is one) between it and the function."""
    opening = block[0]
    while opening is not None and opening > function_open:
        head = clean[:opening].rstrip()
        if head.endswith(')'):
            depth, at = 0, len(head)
            while at > 0:
                at -= 1
                depth += (head[at] == ')') - (head[at] == '(')
                if depth == 0:
                    break
            if re.search(r'\b(?:for|while)$', clean[:at].rstrip()):
                return True
        elif re.search(r'\bdo$', head):
            return True
        outer = _enclosing(pairs, opening)
        opening = outer[0] if outer else None
    return False


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
    for block in sorted(pairs.items()):
        if block[0] == part.opening:
            continue
        units = statements(clean, block[0] + 1, block[1])
        assigns = {}
        for start, end in units:
            hit = re.fullmatch(rf'(?P<name>{IDENT})\s*=(?!=)\s*(?P<value>[^;{{}}]+);', clean[start:end].strip())
            if hit:
                assigns.setdefault(hit['name'], []).append((start, end, hit))
        for var, sites in assigns.items():
            if len(sites) < 2:
                continue
            declared = local_declaration(clean, part.opening, var)
            if not declared or not declared[1] or re.search(rf'&\s*{re.escape(var)}\b', body):
                continue
            if _in_loop(clean, pairs, block, part.opening):
                continue
            for number, (start, end, hit) in enumerate(sites[1:], 2):
                between = clean[sites[number - 2][1]:start]
                if not mentions(between, var):
                    continue
                if mentions(clean[block[1] + 1:part.end], var):
                    continue
                fresh = f'{var}{number}'
                if re.search(rf'\b{fresh}\b', clean):
                    continue
                edits = []
                for at in mentions(clean[start:block[1]], var):
                    edits.append((start + at, start + at + len(var), fresh))
                type_, stars = declared
                nl = clean.find('\n', part.opening) + 1
                indent = re.match(r'[ \t]*', source[nl:])[0] or '  '
                edits.append((nl, nl, f'{indent}{type_} {stars}{fresh};\n'))
                text = edit(source, edits)
                if text != source and (FAMILY, text) not in out:
                    out.append((FAMILY, text))
    return out


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'order': 80}  # the registry: no caller wiring (registry.py)
