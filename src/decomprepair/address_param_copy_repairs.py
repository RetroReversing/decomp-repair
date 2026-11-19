"""A parameter whose address a call took, read once into a local before its later uses.

Once `&arg0` has gone to a call, gcc must reload `arg0` from its stack slot at every use. A game's C that copied it
first loads it once, into a saved register:

    temp_v0 = g(&arg0, ...);
    if (temp_v0 == 0) {
        h(arg0);              ->      copy = arg0;
        ...                           h(copy);
        k(arg0);                      ...
    }                                 k(copy);

An N64 function was 91.2% with m2c's two reloads; with the copy, 96.3%, and with the call it was left (one argument
the game never set, which target_call_arity then drops) exact. Offered when the later uses are two or more in one
block; the judge decides.
"""
import re

from .csource import _blank, find
from .pattern_repairs import close

FAMILY = 'address_param_copy'
FAMILIES = (FAMILY,)

IDENT = r'[A-Za-z_]\w*'


def _block_of(clean, at, opening, end):
    """The innermost `{...}` (as start, end) holding position `at`."""
    depth = 0
    for i in range(at, opening - 1, -1):
        ch = clean[i]
        if ch == '}':
            depth += 1
        elif ch == '{':
            if depth == 0:
                return i, close(clean, i, '{', '}')
            depth -= 1
    return opening, end


def variants(source, name):
    span = find(source, name)
    if not span:
        return []
    clean = _blank(source)
    opening = clean.find('{', span[0], span[1])
    end = close(clean, opening, '{', '}') if opening >= 0 else None
    if not end:
        return []
    signature = clean[span[0]:opening]
    params = dict((m[2], m[1].strip()) for m in re.finditer(r'(?:^|[(,])\s*((?:unsigned\s+|signed\s+)?' + IDENT
                                                               + r'(?:\s*\*+)?)\s*\**\s*(' + IDENT + r')\s*(?=[,)])',
                                                               signature[signature.rfind('('):]))
    result = []
    for param, kind in params.items():
        taken = re.search(r'&\s*' + param + r'\b', clean[opening:end])
        if not taken:
            continue
        after = clean.find(';', opening + taken.end()) + 1
        uses = [opening + 0 + m.start() for m in re.finditer(r'(?<![\w.&>])' + param + r'\b(?!\s*=(?!=))',
                                                               clean[opening:end]) if opening + m.start() >= after]
        if len(uses) < 2 or re.search(r'(?<![\w.>])' + param + r'\s*(?:[-+*/%&|^]|<<|>>)?=(?!=)', clean[after:end]) \
                or re.search(r'&\s*' + param + r'\b', clean[after:end]):
            continue
        block = _block_of(clean, uses[0], opening, end)
        if any(not (block[0] < u < block[1]) for u in uses):
            continue
        # the statement holding the first later use starts after the previous `;`, `{` or `}`
        start = max(clean.rfind(';', block[0], uses[0]), clean.rfind('{', block[0], uses[0] + 1),
                    clean.rfind('}', block[0], uses[0])) + 1
        line_start = source.rfind('\n', 0, uses[0]) + 1
        if clean[start:line_start].strip():
            continue  # (the use isn't at the start of its own line's statement)
        indent = re.match(r'[ \t]*', source[line_start:])[0]
        local = '__repair_' + param
        text = source
        for u in reversed(uses):
            text = text[:u] + local + text[u + len(param):]
        text = text[:line_start] + f'{indent}{local} = {param};\n' + text[line_start:]
        body = text.find('{', span[0]) + 1
        text = text[:body] + f'\n    {kind} {local};' + text[body:]
        result.append((FAMILY, text))
    return result
