"""A result set to a constant in a branch, with its default kept in a second, never-read local: explicit returns.

Observed (GCC 2.7.2 SN/KMC `-G0 -mips3 -O2`; one 30-instruction function that calls a helper when a counter matches
and answers whether it did, 215 -> 15 with the rewrite and 0 after the rest of its shape): m2c splits a result that is
a constant on every path into one local per path's origin and returns the one only the branch assigns,

    s32 var_v0; s32 var_v0_entry;
    var_v0_entry = 0;
    if (...) { f(...); var_v0 = 1; }                   /* draft: the else path returns an unset register */
    return var_v0;
    if (...) { f(...); return 1; }                     /* target: `bne` whose delay slot holds `move $v0,$zero` */
    return 0;

The entry local holds the value of the path that skips the branch and nothing reads it; the draft returns the other
variable on both paths, so the compiler loads the constant on the taken path only and the skip path's `move $v0,$zero`
is missing (215). With a `return` of the constant where each is set and the entry local's constant at the end, the
branch is the target's (the library's `flag_returns` does the same for a result that is its own default; this is the
split-variable form it does not see, as m2c writes it).

Children, when the final statement is `return v;`, `v` is a local assigned only integer constants, each assignment
followed by nothing but closing braces before that return, and a second local `e` is assigned one integer constant at
the function's own level and never read: `v = K;` as `return K;`, the final `return v;` as `return <e's constant>;`,
both locals' declarations and the entry assignment gone. Proposals only; the judge decides."""
import re

from .csource import _blank, find
from .pattern_repairs import close

FAMILIES = ('entry_default_constant_returns',)
FAMILY = FAMILIES[0]
IDENT = r'[A-Za-z_]\w*'
NUMBER = r'-?(?:0[xX][0-9a-fA-F]+|\d+)[uUlL]*'
_DECL = r'(?m)^[ \t]*(?:register\s+)?(?:[A-Za-z_]\w*[ \t]+)+\**[ \t]*{}[ \t]*;[ \t]*\n'


def _line(body, name, pattern):
    return re.search(pattern.format(re.escape(name)), body)


def variants(source, name=None):
    span = find(source, name or '')
    if not span:
        return []
    clean = _blank(source)
    opening = clean.find('{', span[0], span[1])
    end = close(clean, opening, '{', '}') if opening >= 0 else None
    if not end:
        return []
    body = clean[opening:end]
    tail = re.search(r'(?m)^([ \t]*)return\s+(' + IDENT + r')\s*;[ \t]*\n?\s*\}\s*$', body)
    if not tail:
        return []
    var = tail[2]
    uses = list(re.finditer(r'(?<![\w.>])' + re.escape(var) + r'\b', body))
    assigns = list(re.finditer(r'(?m)^([ \t]*)' + re.escape(var) + r'\s*=\s*(' + NUMBER + r')\s*;[ \t]*\n', body))
    declared = _line(body, var, _DECL)
    if not assigns or not declared or len(uses) != len(assigns) + 2:
        return []
    for m in assigns:
        if not re.fullmatch(r'(?:\s*\})+\s*', body[m.end():tail.start()]):
            return []
    # the entry local: assigned one constant at the function's own level, declared, never read
    top_level = re.compile(r'(?m)^[ \t]{1,8}(' + IDENT + r')\s*=\s*(' + NUMBER + r')\s*;[ \t]*\n')
    found = []
    for m in top_level.finditer(body[:tail.start()]):
        other = m[1]
        if other == var:
            continue
        mentions = list(re.finditer(r'(?<![\w.>])' + re.escape(other) + r'\b', body))
        decl = _line(body, other, _DECL)
        if decl and len(mentions) == 2 and decl.start() < m.start():
            found.append((m, decl))
    if len(found) != 1:
        return []
    entry, entry_decl = found[0]
    default = entry[2]
    final = f'{tail[1]}return {default};\n}}'
    out = source
    pieces = [(opening + tail.start(), opening + tail.end(), final)]
    pieces += [(opening + m.start(), opening + m.end(), f'{m[1]}return {m[2]};\n') for m in assigns]
    pieces += [(opening + entry.start(), opening + entry.end(), ''), (opening + entry_decl.start(), opening + entry_decl.end(), ''),
               (opening + declared.start(), opening + declared.end(), '')]
    for a, b, text in sorted(pieces, reverse=True):
        out = out[:a] + text + out[b:]
    return [(FAMILY, out)] if out != source else []


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name'), 'archs': ('mips',)}  # the registry: no caller wiring (registry.py)
