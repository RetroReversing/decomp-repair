"""A block's own temporary (`u32 ix = e;`) written as a function-level local the block does not otherwise use.

m2c, and anyone rewriting from it, gives every inner loop's working values their own block-scoped names: the loaded
code `u32 cd = T[k];`, the scatter index `u32 ix = ...`, the bit being reversed `u32 mm = i | hb;`. A programmer who
wrote the decoder with a handful of function-level variables (`a`, `i`, `j`, `c`, ...) reused one of them for each of
those. GCC 2.7.2 allocates one pseudo per source variable: the short block temporary is a small, high-priority pseudo
that global.c colours first, taking the lowest free register, while the original's long-lived variable ranks lower,
conflicts with more, and takes a higher register, and so do the givs and pointers its loop sets up after it. On a
681-instruction bit-stream decoder (KMC GCC 2.7.2) the target showed each inner-loop temporary in exactly the register
of a long-lived variable; written as that variable, one at a time by hand: 1240 -> 1210 (a table read into the
distance entry's variable), -> 1175 (the reversed bit), -> 1130 (a scatter index into the bit reader's variable), and
later 900 -> 865 (a loaded code held in the bit reader's variable). This family's own children from the 1240 source:
1240 -> 850 in one step (the last pass's loaded code written as the distance entry's variable), then a greedy chain of
its children 850 -> 815 -> 785 -> 770 -> 760, each checked against a clean transcription on generated bit streams.

A child for each pair (temporary, survivor), each temporary's most-used survivors first, round-robin over the
temporaries up to the cap: the temporary declared with an initializer at the head of a block, the
survivor a function-level local of the same type that the block never mentions, whose next mention after the block (if
any) is a plain assignment, and that every loop around the block sets before reading. The declaration becomes an
assignment; other initialised declarations after it in that block are split into a declaration and an assignment so
the order of evaluation stays. Names a function-like macro mentions, volatiles and address-taken locals are left alone.
A candidate rewrite; the exact judge decides which survivor, if any.
"""
import re

from .integer_repair_support import edit, view

FAMILY = 'block_temp_role_merge'
FAMILIES = (FAMILY,)
LIMIT = 48
_TYPE = r'(?:unsigned\s+(?:int|short|char)|signed\s+(?:int|short|char)|[us](?:8|16|32)|int|short|char)'
_INIT = re.compile(rf'(?m)^([ \t]*)({_TYPE})\s+([A-Za-z_]\w*)\s*=\s*([^;]+);')
_DECL = re.compile(rf'\s*({_TYPE}(?:\s*\*+)?|[A-Za-z_]\w*\s*\*+)\s*([A-Za-z_]\w*)\s*(=\s*([^;]+))?;')
_LOOP = re.compile(r'\b(?:for|while)\s*\(|\bdo\s*\{')


def _close(clean, at, left='{', right='}'):
    depth = 0
    for i in range(at, len(clean)):
        depth += (clean[i] == left) - (clean[i] == right)
        if depth == 0:
            return i
    return None


def _open_of(clean, at, lo):
    depth = 0
    for i in range(at - 1, lo - 1, -1):
        if clean[i] == '}':
            depth += 1
        elif clean[i] == '{':
            if depth == 0:
                return i
            depth -= 1
    return None


def _loops(clean, lo, hi):
    out = []
    for loop in _LOOP.finditer(clean, lo, hi):
        at = loop.end() - 1
        if clean[at] == '(':
            shut = _close(clean, at, '(', ')')
            brace = re.compile(r'\s*\{').match(clean, shut + 1) if shut is not None else None
            if not brace:
                continue
            at = brace.end() - 1
        end = _close(clean, at)
        if end is not None:
            out.append((at, end))
    return out


def _first_is_assignment(text, var):
    mention = re.search(rf'\b{var}\b', text)
    return mention is None or re.match(rf'{var}\s*=[^=]', text[mention.start():]) is not None


def _function_locals(clean, opening):
    """(type, name) of the declarations at the top of the function body."""
    out, at = [], opening + 1
    while True:
        decl = _DECL.match(clean, at)
        if not decl or decl[3]:
            break
        out.append((re.sub(r'\s+', ' ', decl[1]).strip(), decl[2]))
        at = decl.end()
    return out


def variants(source, name):
    part = view(source, name)
    if not part:
        return []
    clean, lo, hi = part.clean, part.opening + 1, part.end - 1
    if re.search(r'\bvolatile\b', clean[lo:hi]):
        return []
    macro_names = set()
    for body in re.findall(r'(?m)^\s*#\s*define\s+\w+\(([^\n]*(?:\\\n[^\n]*)*)', source):
        macro_names |= set(re.findall(r'[A-Za-z_]\w*', body))
    survivors = [(t, n) for t, n in _function_locals(clean, part.opening)
                 if n not in macro_names and not re.search(rf'&\s*{n}\b', clean[lo:hi])]
    loops = _loops(clean, lo, hi)
    uses = {n: len(re.findall(rf'\b{n}\b', clean[lo:hi])) for _, n in survivors}
    survivors.sort(key=lambda item: -uses[item[1]])  # the long-lived, much-used variables first: the likely roles
    per_temp = []
    for temp in _INIT.finditer(clean, lo, hi):
        children = []
        per_temp.append(children)
        opening = _open_of(clean, temp.start(), lo)
        if opening is None or opening <= part.opening:
            continue  # a function-level declaration: not a block temporary
        head = clean[opening + 1:temp.start()]
        if re.sub(r'(?m)^[ \t]*[^;]*;', '', head).strip():
            continue  # the declaration is not in the block's leading declarations
        closing = _close(clean, opening)
        var = temp[3]
        if closing is None or var in macro_names or re.search(rf'&\s*{var}\b', clean[opening:closing]):
            continue
        ttype = re.sub(r'\s+', ' ', temp[2])
        later_decls = []
        at = temp.end()
        while True:
            decl = _DECL.match(clean, at)
            if not decl:
                break
            later_decls.append(decl)
            at = decl.end()
        for stype, survivor in survivors:
            if stype != ttype or survivor == var:
                continue
            if re.search(rf'\b{survivor}\b', clean[opening:closing]):
                continue
            if not _first_is_assignment(clean[closing:hi], survivor):
                continue
            around = [body for body in loops if body[0] < opening and closing < body[1]]
            if any(not _first_is_assignment(clean[body[0]:body[1]], survivor) for body in around):
                continue
            indent = temp[1]
            moved = ''.join(f'{indent}{d.group(0).strip().split("=")[0].rstrip()};\n' for d in later_decls if d[3])
            assigns = re.sub(rf'\b{var}\b', survivor,
                             ''.join(f'{indent}{d[2]} = {source[d.start(4):d.end(4)].strip()};\n' for d in later_decls if d[3]))
            plain = ''.join(f'{indent}{d.group(0).strip()}\n' for d in later_decls if not d[3])
            replacement = plain + moved + f'{indent}{survivor} = {source[temp.start(4):temp.end(4)].strip()};\n' + assigns
            start = temp.start()
            end = later_decls[-1].end() if later_decls else temp.end()
            end = end + 1 if source[end:end + 1] == '\n' else end
            body = source[end:closing]
            renamed = re.sub(rf'\b{var}\b', survivor, body)
            children.append((FAMILY, edit(source, [(start, closing, replacement + renamed)])))
    out, rank = [], 0
    while len(out) < LIMIT and any(rank < len(children) for children in per_temp):
        out.extend(children[rank] for children in per_temp if rank < len(children))
        rank += 1
    return out[:LIMIT]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}  # the registry: no caller wiring (registry.py)
