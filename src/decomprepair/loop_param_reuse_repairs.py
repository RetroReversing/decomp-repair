"""Two rewrites for a loop that reuses a parameter as its offset variable (an N64 voice-list walk, KMC GCC 2.7.2).

The target kept three things the m2c-style source hid, and each alone left the score unchanged or worse:

* `reused_param_alias`: the loop assigns its table offset to a parameter (`arg1 = idx * 0x1a0;`) that the code before
  the loop had read (`high = (arg1 & 0xFFFF) >> 7; low = arg1 & 0x7F;`). The original kept the parameter's value and
  used another name for the offset, so loop.c hoists the two invariant expressions out of the calls and the pseudo
  that held the parameter dies before the loop. The offset goes to a parameter the body never mentions (`arg0`),
  and the locals that read the parameter are inlined at their uses (`single_use_inline` refuses while the parameter
  changes, so the pair is one child).
* `dead_call_arg_temp`: `result = (u8) idx;` ahead of `f(0x84, result, ...); f(0x85, result, ...);` where `result` is
  only overwritten again (`result = 0;`) before it is read. The original passed `idx` itself, and the call-argument
  conversion then keeps the `andi` that a stored copy lets combine fold (the mask on `idx` stays unknown to combine
  because `idx` has two sets).

Both are candidate rewrites, not equivalence proofs: the compiler and the exact judge decide.
"""
import re

from .integer_repair_support import edit, view
from .local_inline_repairs import _plain

FAMILY_ALIAS = 'reused_param_alias'
FAMILY_TEMP = 'dead_call_arg_temp'
FAMILIES = (FAMILY_ALIAS, FAMILY_TEMP)
_LOOP_HEAD = re.compile(r'(?m)^[ \t]*\w+\s*:(?!:)|\b(?:while|for|do)\b')


def _parameters(clean, opening, name):
    head = clean[:opening]
    m = list(re.finditer(rf'\b{re.escape(name)}\s*\(([^{{}};]*)\)\s*$', head))
    if not m:
        return []
    names, depth, start, text = [], 0, 0, m[-1][1]
    for index, char in enumerate(text + ','):
        depth += char == '('
        depth -= char == ')'
        if char == ',' and depth == 0:
            piece = text[start:index].strip()
            start = index + 1
            if not piece or piece == 'void':
                continue
            # a function pointer's name is the one in `(*name)(...)`; any other parameter's is its last word
            pointer = re.search(r'\(\s*\*\s*(\w+)\s*\)\s*\(', piece)
            last = re.search(r'(\w+)\s*(?:\[[^\]]*\])?\s*$', piece)
            if pointer or last:
                names.append((pointer or last)[1])
    return names


def alias_variants(source, name):
    part = view(source, name)
    if not part:
        return []
    clean, base = part.clean, part.opening + 1
    params = _parameters(clean, part.opening, name)
    body = clean[base:part.end - 1]
    unused = [p for p in params if not re.search(rf'\b{p}\b', body)]
    result = []
    for param in params:
        if param in unused or not unused:
            continue
        assign = re.search(rf'(?<![\w.>])({param})\s*=(?!=)', body)
        if not assign:
            continue
        reads = [m.start() for m in re.finditer(rf'(?<![\w.>])\b{param}\b(?!\s*=(?!=))', body[:assign.start()])]
        heads = [m.start() for m in _LOOP_HEAD.finditer(body[:assign.start()])]
        # every read of the parameter happens before the loop head that precedes its reuse
        if not reads or not heads or max(reads) > max(heads):
            continue
        # and nothing before the first assignment reads it through an address or a pointer to it
        if re.search(rf'&\s*{param}\b', body):
            continue
        spans = [(base + assign.start() + m.start(), base + assign.start() + m.end(), unused[0])
                 for m in re.finditer(rf'(?<![\w.>])\b{param}\b', body[assign.start():])]
        text = edit(source, [(a, b, c) for a, b, c in spans])
        result.append((FAMILY_ALIAS, text))
        # the locals that read the parameter, inlined at every use (one child): loop.c then
        # hoists them out of the calls, and the pseudo holding the parameter dies before the loop
        pre = body[:assign.start()]
        group = []
        for decl in re.finditer(r'(?m)^[ \t]*(\w+)\s*=\s*([^;{}=]+);[ \t]*\n', pre):
            local, expression = decl[1], decl[2].strip()
            if not re.search(rf'\b{param}\b', expression) or not _plain(expression):
                continue
            rest = body[decl.end():]
            if re.search(rf'(?<![\w.>*]){local}\s*(?:[-+*/|&^]|<<|>>)?=(?!=)|&\s*{local}\b', body[:decl.start()] + rest) \
                    or not re.search(rf'\b{local}\b', rest):
                continue
            uses = [(base + decl.end() + u.start(), base + decl.end() + u.end(), '(' + expression + ')')
                    for u in re.finditer(rf'\b{local}\b', rest)]
            group.append((base + decl.start(), base + decl.end(), ''))
            group += uses
        if group:
            result.append((FAMILY_ALIAS, edit(source, spans + group)))
    return result


def temp_variants(source, name):
    part = view(source, name)
    if not part:
        return []
    clean, base = part.clean, part.opening + 1
    body = clean[base:part.end - 1]
    result = []
    for local in dict.fromkeys(re.findall(r'(?m)^[ \t]*(\w+)\s*=\s*[^;{}=]+;', body)):
        stores = list(re.finditer(rf'(?m)^[ \t]*{local}\s*=\s*([^;{{}}=]+);[ \t]*\n', body))
        literal = [m for m in stores if re.fullmatch(r'-?(?:0[xX][0-9a-fA-F]+|[0-9]+)', m[1].strip())]
        copies = [m for m in stores if m not in literal and re.fullmatch(r'[\w\s()*]+', m[1])]
        if not literal or not copies:
            continue
        edits, ok = [], True
        for index, m in enumerate(copies):
            following = [s.start() for s in stores if s.start() > m.start()]
            stop = min(following) if following else len(body)
            region = body[m.end():stop]
            uses = list(re.finditer(rf'\b{local}\b', region))
            if not uses:
                ok = False
                break
            for use in uses:
                around = region[:use.start()].rstrip()[-1:], region[use.end():].lstrip()[:1]
                if around[0] not in '(,' or around[1] not in '),':
                    ok = False
                    break
                edits.append((base + m.end() + use.start(), base + m.end() + use.end(), '(' + m[1].strip() + ')'))
            if not ok:
                break
            edits.append((base + m.start(), base + m.end(), ''))
        if ok and edits:
            result.append((FAMILY_TEMP, edit(source, edits)))
    return result


def variants(source, name, limit=8):
    return (alias_variants(source, name) + temp_variants(source, name))[:limit]
