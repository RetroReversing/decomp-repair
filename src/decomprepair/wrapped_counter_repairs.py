"""A wrap-around counter tested before its step, as the game wrote it, where m2c tested after.

gcc 2.7.2 fills a branch's delay slot with the counter's step, so the target tests the old value and steps in the slot:

    bgtz  $s0, next         # old value
    addiu $s0, $s0, -1      # delay slot: the step
    move  $s0, $s1          # not taken: wrap to the limit

m2c read the step as coming first and wrote `v -= 1; if (v <= 0) { v = 0x77; }`, where the game had
`if (v > 0) { v -= 1; } else { v = 0x77; }` (the same constant, on the old value). An N64 function's two search loops,
one each way, were 63.4%; tested first, with the limit `0x77` held in a local as the target keeps it in `$s1`
(80.6% without the local), and the existing `goto_backward_loop` after it: exact. Offered with and without the
local, for a constant the function names more than once.
"""
import re

from .csource import _blank, find
from .pattern_repairs import close

FAMILY = 'wrapped_counter_step'
FAMILIES = (FAMILY,)

IDENT = r'[A-Za-z_]\w*'
NUMBER = r'0[xX][0-9a-fA-F]+|\d+'
STEP = re.compile(
    r'(?m)^(?P<indent>[ \t]*)(?P<v>' + IDENT + r')\s*(?P<op>[-+])=\s*1\s*;[ \t]*\n'
    r'[ \t]*if\s*\(\s*(?P=v)\s*(?P<cmp><=|>=|<|>)\s*(?P<bound>' + NUMBER + r')[uU]?\s*\)\s*\{[ \t]*\n'
    r'[ \t]*(?P=v)\s*=\s*(?P<wrap>' + NUMBER + r')[uU]?\s*;[ \t]*\n[ \t]*\}[ \t]*\n')
OPPOSITE = {'<=': '>', '>=': '<', '<': '>=', '>': '<='}


def variants(source, name):
    span = find(source, name)
    if not span:
        return []
    clean = _blank(source)
    opening = clean.find('{', span[0], span[1])
    end = close(clean, opening, '{', '}') if opening >= 0 else None
    if not end:
        return []
    hits = [h for h in STEP.finditer(clean, opening + 1, end)
            # decrement wraps up from the low bound, increment down from the high one
            if (h['op'] == '-' and h['cmp'] in ('<=', '<')) or (h['op'] == '+' and h['cmp'] in ('>=', '>'))]
    if not hits:
        return []
    text = source
    for h in reversed(hits):
        ind, v = h['indent'], h['v']
        step = f'{v} {h["op"]}= 1;'
        rewritten = (f'{ind}if ({v} {OPPOSITE[h["cmp"]]} {h["bound"]}) {{\n{ind}    {step}\n{ind}}} else {{\n'
                     f'{ind}    {v} = {h["wrap"]};\n{ind}}}\n')
        text = text[:h.start()] + rewritten + text[h.end():]
    result = [(FAMILY, text)]
    # the limit held in a local: a constant among the bounds and wraps that the function names more than once
    body = _blank(text)
    span2 = find(text, name)
    open2 = body.find('{', span2[0], span2[1])
    end2 = close(body, open2, '{', '}')
    for constant in dict.fromkeys(x for h in hits for x in (h['bound'], h['wrap'])):
        if int(constant, 0) <= 1:
            continue
        uses = list(re.finditer(r'(?<![\w.])' + re.escape(constant) + r'(?![\w.])', body[open2:end2]))
        if len(uses) < 2:
            continue
        local = text
        for m in reversed(uses):
            at = open2 + m.start()
            local = local[:at] + '__repair_limit' + local[at + len(constant):]
        decl_end = _declarations_end(_blank(local), open2)
        local = (local[:open2 + 1] + '\n    s32 __repair_limit;' + local[open2 + 1:decl_end] + '    __repair_limit = '
                 + constant + ';\n' + local[decl_end:])
        result.append((FAMILY, local))
    return result[:3]


def _declarations_end(clean, opening):
    """Where the function's first statement starts (after its declarations and the blank line after them)."""
    pos = opening + 1
    decl = re.compile(r'[ \t]*(?:(?:unsigned|signed|const|volatile|register|struct)\s+)*' + IDENT
                      + r'(?:\s+\**\s*|\s*\*+\s*)' + IDENT + r'\s*(?:\[[^]]*\])?\s*(?:=[^;]*)?;[ \t]*\n')
    while True:
        m = re.compile(r'[ \t]*\n').match(clean, pos) or decl.match(clean, pos)
        if not m or m.end() == pos:
            return pos
        pos = m.end()
