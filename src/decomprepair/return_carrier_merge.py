"""m2c's returned carrier and the values copied into it, written as one variable.

A function that tests a call's result, replaces it with a code in some arms and returns whichever it ends with comes
back from m2c as three variables joined by copies into the returned one:

    temp = f();
    if (temp == 0) { var_a0 = 3; goto block_9; }
    ...
    if ((temp == 4) || (var_v0 = temp, (temp == 0xA))) {
        var_a0 = 2;
    block_9:
        var_v0 = var_a0;
    }
    return var_v0;

The source had one variable (`result = f(); if (result == 0) result = 3; ... return result;`), and the compiler keeps it
in one register where the draft's three take two. On a 116-instruction N64 controller-pak routine (`sn-n64-281 -O2`) the
merge took 425 to 285 after the shared store tail was written out, and the loop counters' merge then matched it.

The shape: the final `return R;` of a local whose only assignments are copies `R = X;` of other locals (a copy inside a
condition, `(R = X, test)`, is taken when that `if` body ends with another copy into `R`). The merge is offered only when
no member is assigned a different value while another is still read later (the flow graph decides), none is updated in
place (`++`, `+=`) and all have one type. The returned name and each source name are tried as the survivor.
A candidate rewrite; the exact judge decides.
"""
import re

from . import local_flow
from .integer_repair_support import IDENT, edit, locals_for, view
from .pattern_repairs import close

FAMILY = 'return_carrier_merge'
FAMILIES = (FAMILY,)
LIMIT = 3

_RETURN = re.compile(rf'\breturn\s+({IDENT})\s*;\s*}}\s*$')


def _mentions(clean, start, end, name):
    return [hit for hit in re.finditer(rf'\b{name}\b', clean[:end]) if hit.start() >= start
            and not re.search(r'(?:\.|->)\s*$', clean[max(start, hit.start() - 4):hit.start()])]


def _guarded_comma(clean, at, carrier):
    """Whether the copy at `at` sits in an `if` condition whose braced body ends with a copy into the carrier."""
    for head in reversed(list(re.finditer(r'\bif\s*\(', clean[:at]))):
        stop = close(clean, head.end() - 1)
        if stop is None or stop <= at:
            continue
        brace = re.compile(r'\s*{').match(clean, stop)
        end = brace and close(clean, brace.end() - 1, '{', '}')
        if not end:
            return False
        return re.search(rf'\b{carrier}\s*=\s*{IDENT}\s*;\s*}}$', clean[brace.end() - 1:end]) is not None
    return False


def _interferes(flow, clean, group, copies):
    """Whether two members hold different values at once, with each copy's source exempt at that copy."""
    for start, source in copies:
        for node in flow.nodes:
            if node.start <= start < node.end:
                node.defines.add(copies.carrier)
                if len(_mentions(clean, node.start, node.end, copies.carrier)) == 1:
                    node.uses.discard(copies.carrier)
    changed = True
    for node in flow.nodes:
        node.live = set()
    while changed:
        changed = False
        for node in reversed(flow.nodes):
            outgoing = set().union(*(flow.nodes[n].live for n in node.successors))
            live = node.uses | (outgoing - node.defines)
            if live != node.live:
                node.live, changed = live, True
    declared = [d.start() for d in flow.locals]
    for node in flow.nodes:
        if any(node.start <= at < node.end for at in declared):
            continue
        outgoing = set().union(*(flow.nodes[n].live for n in node.successors))
        for name in node.defines & group:
            same = {source for start, source in copies if name == copies.carrier and node.start <= start < node.end}
            if (outgoing & group) - same - {name}:
                return True
    return False


class _Copies(list):
    carrier = ''


def variants(source, name):
    part = view(source, name)
    if not part:
        return []
    clean, start, end = part.clean, part.opening + 1, part.end
    returned = _RETURN.search(clean[:end])
    if not returned:
        return []
    carrier = returned[1]
    declared = {d['name']: d for d in locals_for(part)}
    if carrier not in declared:
        return []
    copies = _Copies()
    copies.carrier = carrier
    for hit in _mentions(clean, start, end, carrier):
        if hit.start() == declared[carrier].start('name') or clean[:hit.start()].rstrip().endswith('return'):
            continue
        copy = re.compile(rf'{carrier}\s*=(?!=)\s*({IDENT})\s*([;,])').match(clean, hit.start())
        if not copy or copy[1] not in declared or copy[1] == carrier:
            return []
        before = clean[:hit.start()].rstrip()
        if copy[2] == ',' and not (before.endswith('(') and _guarded_comma(clean, hit.start(), carrier)):
            return []
        if copy[2] == ';' and before[-1:] not in (';', '{', '}', ':'):
            return []
        copies.append((hit.start(), copy[1]))
    if not copies:
        return []
    sources = list(dict.fromkeys(value for _, value in copies))
    group = {carrier, *sources}
    if len({' '.join(declared[member]['type'].split()) for member in group}) != 1:
        return []
    body = clean[start:end]
    for member in group:
        if re.search(rf'(?:\+\+|--)\s*{member}\b|\b{member}\s*(?:\+\+|--|(?:<<|>>|[-+*/%&|^])=)', body):
            return []
    flow = local_flow.analyze(source, name)
    if flow is None or not group <= flow.names or _interferes(flow, clean, group, copies):
        return []
    result = []
    for survivor in [*sources, carrier][:LIMIT]:
        text = _merge(source, part, group, survivor, declared)
        if text and (FAMILY, text) not in result:
            result.append((FAMILY, text))
    return result


def _merge(source, part, group, survivor, declared):
    clean, start, end = part.clean, part.opening + 1, part.end
    edits = []
    for member in group - {survivor}:
        declaration = declared[member]
        line = source.rfind('\n', 0, declaration.start()) + 1
        stop = source.find('\n', declaration.end())
        alone = not source[line:declaration.start()].strip() and not source[declaration.end():stop].strip()
        span = (line, stop + 1) if alone else declaration.span()
        edits.append((*span, ''))
        edits += [(hit.start(), hit.end(), survivor) for hit in _mentions(clean, start, end, member)
                  if not span[0] <= hit.start() < span[1]]
    text = edit(source, edits)
    part = view(text, _function(source, part))
    if not part:
        return None
    # the copies are now `x = x`: out of conditions, and out of the statement list (a label keeps an empty statement)
    text = re.sub(rf'\(\s*{survivor}\s*=\s*{survivor}\s*,\s*(\([^()]*\))\s*\)', r'\1', text)
    text = re.sub(rf'(:[ \t]*\n)([ \t]*){survivor}\s*=\s*{survivor}\s*;', r'\1\2;', text)
    return re.sub(rf'\n[ \t]*{survivor}\s*=\s*{survivor}\s*;(?=[ \t]*\n)', '', text)


def _function(source, part):
    head = re.findall(rf'({IDENT})\s*\([^{{}};]*\)\s*$', part.clean[:part.opening])
    return head[-1] if head else ''


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}
