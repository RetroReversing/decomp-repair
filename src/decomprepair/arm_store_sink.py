"""A store before a branch pushed into both of its ways out, and the leave block's store order swapped.

m2c (and the first draft) write a list insertion as one store, then the branch:

    entry->next = cur;
    if (prev == NULL) { head = entry; goto next; }
    prev->next = entry;
    goto next;

and `{ head = entry; entry->next = NULL; continue; }` for the empty list. In GCC 2.x the two blocks that store `head`
and jump to the same label are cross-jumped into one when their tails match, so the target's two separate copies
(`lui/sw head; j; addiu` twice) never appear, and the delay slot of the jump is filled from the store before it. A
KMC gcc 2.7.2 near miss (320) needed both changes together and neither helped alone (550 and 320):

    if (prev == NULL) { entry->next = cur; head = entry; goto next; }     /* the store in each way out */
    entry->next = cur; prev->next = entry; goto next;
    ...
    if (cur == NULL) { entry->next = NULL; head = entry; continue; }      /* field store before the scalar's */

The pointer store (`MEM_IN_STRUCT_P`) and the scalar global's store do not alias, so the scheduler may order them
either way, and which way the source wrote them decides whether the tails match when jump.c looks for them.

Two rewrites, offered alone and together (the combination is the child that was exact):
  * sink: a simple store `P->f = Q;`, then `if (C) { A }` whose block ends in `goto`/`continue`/`break`/`return`,
    then statements `R` ending the same way and closing the block: the store goes to the start of `A` and before
    `R`. `C` must read nothing through a pointer, an index or a call, so it can't see the store.
  * swap: `G = X;` (G an extern scalar global) directly followed by a store through a pointer or an index and then
    a leave statement: the two stores trade places when neither reads what the other writes.
"""
import re

from .csource import _blank, find

FAMILY_SINK = 'arm_store_sink'
FAMILY_SWAP = 'leave_store_swap'
FAMILY_BOTH = 'arm_store_sink_swap'
FAMILIES = (FAMILY_SINK, FAMILY_SWAP, FAMILY_BOTH)
ID = r'[A-Za-z_]\w*'
LEAVE = re.compile(r'\s*(?:goto\s+\w+|continue|break|return\b[^;]*)\s*;\s*')
STORE = re.compile(r'(?P<ind>\s*)(?P<lhs>[^=;{}()!<]+?)\s*(?<![<>!])=(?!=)\s*(?P<rhs>[^;{}]+);\s*')
SIMPLE_COND = re.compile(r'[\w\s!=<>()&|]+')


def _python_body(source, name):
    span = find(source, name)
    if not span:
        return None
    clean = _blank(source)
    opening = clean.find('{', span[0], span[1])
    if opening < 0:
        return None
    depth = 0
    for i in range(opening, span[1]):
        depth += (clean[i] == '{') - (clean[i] == '}')
        if depth == 0:
            return opening, i + 1, clean
    return None


_body = _python_body
try:  # the typed kernel (native_build.py), when it is built: same answers, the loop in C
    from . import _scan
except ImportError:
    _scan = None
if _scan is not None:
    def _body(source, name):
        span = find(source, name)
        if not span:
            return None
        clean = _blank(source)
        opening = clean.find('{', span[0], span[1])
        if opening < 0:
            return None
        found = _scan.close_every(clean, opening, '{', '}', True, None)
        if found is NotImplemented or span[1] > len(clean):
            return _python_body(source, name)
        return (opening, found, clean) if found is not None and found <= span[1] else None


def _indent(line):
    return len(line) - len(line.lstrip())


def _pointer_store(lhs):
    return '->' in lhs or '[' in lhs or lhs.lstrip().startswith('*')


def _reads(expr, lhs):
    """True when `expr` mentions the base name of `lhs` (a conservative dependence test)."""
    base = re.match(rf'\s*\*?\s*\(?\s*({ID})', lhs)
    return bool(base and re.search(rf'\b{base[1]}\b', expr))


def _sinks(text):
    """[(store_line, if_line, close_line, end_line)] for each store that can go into both ways out."""
    found = []
    for i in range(len(text) - 2):
        store = STORE.fullmatch(text[i])
        branch = re.fullmatch(r'(\s*)if\s*\((.*)\)\s*\{\s*', text[i + 1])
        if not store or not branch or not _pointer_store(store['lhs']) or _indent(text[i + 1]) != _indent(text[i]):
            continue
        cond = branch[2]
        if not SIMPLE_COND.fullmatch(cond) or re.search(r'\w\s*\(', cond) or any(c in cond for c in '[*'):
            continue
        if _reads(cond, store['lhs']):
            continue
        ind = _indent(text[i])
        close = next((j for j in range(i + 2, len(text)) if text[j].strip() == '}' and _indent(text[j]) == ind), None)
        if close is None or not LEAVE.fullmatch(text[close - 1].strip() + ' ') or close - 1 <= i + 1:
            continue
        end = next((j for j in range(close + 1, len(text))
                    if text[j].strip() and _indent(text[j]) < ind), None)
        if end is None or end - 1 <= close or not LEAVE.fullmatch(text[end - 1].strip() + ' '):
            continue
        rest = text[close + 1:end]
        if any(re.fullmatch(r'\s*\w+:\s*;?\s*', r) or _indent(r) != ind and r.strip() for r in rest):
            continue
        found.append((i, i + 1, close, end))
    return found


def _swaps(text, globals_):
    """[line] of `G = X;` whose next line is a store through a pointer and whose line after is a leave."""
    found = []
    for i in range(len(text) - 2):
        first, second = STORE.fullmatch(text[i]), STORE.fullmatch(text[i + 1])
        if not first or not second or first['lhs'].strip() not in globals_ or not _pointer_store(second['lhs']):
            continue
        if not LEAVE.fullmatch(text[i + 2].strip() + ' ') or _indent(text[i]) != _indent(text[i + 1]):
            continue
        if re.search(r'->|\[|\*', first['rhs']) or re.search(rf'\b{re.escape(first["lhs"].strip())}\b', second['rhs']):
            continue
        found.append(i)
    return found


def variants(source, name):
    part = _body(source, name)
    if not part:
        return []
    opening, end, clean = part
    globals_ = {m['g'] for m in re.finditer(rf'(?m)^[ \t]*extern\s+[\w ]+?[\s*]+(?P<g>{ID})\s*;', clean[:opening])}
    head, body, tail = source[:opening + 1], source[opening + 1:end - 1], source[end - 1:]
    lines = body.split('\n')
    text = [re.sub(r'//.*|/\*.*?\*/', '', line) for line in clean[opening + 1:end - 1].split('\n')]
    sinks, swaps = _sinks(text), _swaps(text, globals_)

    def build(use_sinks, use_swaps):
        out = list(lines)
        for i in use_swaps:
            out[i], out[i + 1] = out[i + 1], out[i]
        # work from the bottom so earlier line numbers stay valid
        for store, branch, close, stop in sorted(use_sinks, reverse=True):
            line = lines[store]
            arm = lines[branch + 1]
            out.insert(close + 1, line)
            out.insert(branch + 1, arm[:_indent(arm)] + line.lstrip())
            out[store] = None
        return head + '\n'.join(x for x in out if x is not None) + tail

    result = []
    if sinks:
        result.append((FAMILY_SINK, build(sinks[:1], [])))
    if swaps:
        result.append((FAMILY_SWAP, build([], swaps)))
    if sinks and swaps:
        result.append((FAMILY_BOTH, build(sinks[:1], swaps)))
    return result
