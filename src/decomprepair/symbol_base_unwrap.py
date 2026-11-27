"""symbol_base_unwrap: a local pointer set once to a global's address and only ever dereferenced, written as the global.

A search (or `symbol_address_local`) sometimes leaves

    void **__base_gActor;
    __base_gActor = &gActor;
    *__base_gActor = NULL;  ...  if ((*__base_gActor) != NULL) { f(*__base_gActor); }

which keeps the address in a register and every access `0($sN)`. When the target addresses the global with
`lui`/`%lo` at each use, the pointer is scaffolding: writing `gActor` for every `*P` gives the plain C back and lets
the families that read a global by name (`global_pointer_local`) see it. A KMC-compiled N64 collision routine
(`gcc-2.7.2-kmc -O2`, 2,267 instructions) went 15070 -> 14705 with it, then 13685 with the global read into a local
in the one block that uses it (`global_pointer_local`).

Preconditions: the local is declared in the function as a plain pointer, assigned exactly once, from `&SYM`, and every
other occurrence is a dereference `*P` (not `P[i]`, `P->f`, `P + k` or `P` passed on). The child replaces each `*P`
with `SYM` (parenthesised forms `(*P)` too), and drops the declaration and the assignment.

The assignment may stand inside braces or one-shot loops that hold nothing else (`do { P = &SYM; } while (0);`,
`{ P = &SYM; }`), as a search or its stripped form leaves it; the empty wrapper goes with it. A KMC/SN-compiled N64
routine's counted loop read its bound through such a pointer, which held the symbol's address in a saved register
where the target keeps only the `lui` half: 570 -> 60 with this, 0 after `pointer_local_reuse`."""
import re

from .csource import _blank, find

FAMILY = 'symbol_base_unwrap'
FAMILIES = (FAMILY,)

IDENT = r'[A-Za-z_]\w*'
# `P = &SYM;` at the start of a line, perhaps behind the openers of wrappers
SETTING = re.compile(rf'(?m)^[ \t]*(?P<open>(?:(?:do\b\s*)?\{{\s*)*)(?P<p>{IDENT})\s*=\s*&\s*(?P<sym>{IDENT})\s*;')


def _setting_end(body, setting):
    """Where the setting statement ends once every wrapper it opened is closed around it alone, or None."""
    end = setting.end()
    for opener in reversed(re.findall(r'(?:do\b\s*)?\{', setting['open'])):
        closer = r'\s*\}\s*while\s*\(\s*0\s*\)\s*;' if opener.startswith('do') else r'\s*\}'
        found = re.compile(closer).match(body, end)
        if not found:
            return None
        end = found.end()
    return re.compile(r'[ \t]*\n?').match(body, end).end()


def variants(source, name):
    span = find(source, name)
    if not span:
        return []
    clean = _blank(source)
    opening = clean.find('{', span[0], span[1])
    if opening < 0:
        return []
    body = clean[opening:span[1]]
    out = []
    for setting in SETTING.finditer(body):
        p, sym = setting['p'], setting['sym']
        end = _setting_end(body, setting)
        if end is None:
            continue
        declaration = re.search(rf'(?m)^[ \t]*(?:const\s+|volatile\s+)*{IDENT}\s*\*+\s*(?:const\s+)?{p}\s*;[ \t]*\n?',
                                body)
        if not declaration or p == sym:
            continue
        mentions = [m for m in re.finditer(rf'(?<![\w.>]){p}\b', body)]
        others = [m for m in mentions
                  if not (declaration.start() <= m.start() < declaration.end()
                          or setting.start() <= m.start() < end)]
        if not others:
            continue
        derefs = []
        for m in others:
            before = body[:m.start()].rstrip()
            after = body[m.end():].lstrip()
            if not before.endswith('*') or after.startswith(('[', '->', '++', '--')):
                derefs = None
                break
            star = len(before) - 1
            # `a * P` would be a product, not a dereference: the token before the `*` must not end an operand
            prev = body[:star].rstrip()[-1:]
            if prev and (prev.isalnum() or prev in '_)]'):
                derefs = None
                break
            derefs.append((star, m.end()))
        if not derefs:
            continue
        text = source
        edits = [(opening + a, opening + b, sym) for a, b in derefs]
        edits += [(opening + setting.start(), opening + end, ''),
                  (opening + declaration.start(), opening + declaration.end(), '')]
        for a, b, new in sorted(edits, reverse=True):
            text = text[:a] + new + text[b:]
        text = re.sub(rf'\(\s*{re.escape(sym)}\s*\)(?=\s*(?:!=|==|\)|;|,))', sym, text)
        out.append((FAMILY, text))
    return out[:4]


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'order': 96}  # the registry: no caller wiring (registry.py)
