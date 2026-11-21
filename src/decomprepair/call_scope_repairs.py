"""Single-call one-shot scopes: no duplicated calls, moved effects or swallowed loop control."""
import re

from . import local_flow
from .integer_repair_support import IDENT, edit, view
from .pattern_repairs import close

FAMILIES = ('call_one_shot_scope', 'call_one_shot_scope_shift')
SHIFT = FAMILIES[1]
LIMIT = 24


def variants(source, name, header=''):
    part = view(source,name)
    flow = local_flow.analyze(source,name)
    if not part or not flow:
        return []
    macros = set(re.findall(r'^\s*#\s*define\s+(\w+)',source+'\n'+header,re.M))
    if '__LINE__' in source+'\n'+header:
        return []
    floats = set(re.findall(r'\b(?:f32|f64|float|double)\s+('+IDENT+r')\s*;',part.body))
    candidates, wrapped, calls = [], [], []
    for node in flow.nodes:
        text = part.clean[node.start:node.end]
        hit = re.match(rf'\s*({IDENT})\s*\(',text)
        if not hit or hit[1] in macros | {'if','while','for','switch','sizeof','return','do'}:
            continue
        opening = node.start+hit.end()-1
        end = close(part.clean,opening)
        if not end or not re.fullmatch(r'\s*;',part.clean[end:node.end]):
            continue
        if set(re.findall(IDENT,text)) & macros or re.search(r'[{}]|\b(?:break|continue|goto)\b',text):
            continue
        # Do not nest another synthetic loop around an already single-call wrapper.
        prefix = part.clean[:node.start]
        head = re.search(r'\bdo\s*{\s*$',prefix)
        tail = re.match(r'\s*}\s*while\s*\(\s*0\s*\)\s*;',part.clean[node.end:])
        if head and tail:
            wrapped.append((head.start(),node.end+tail.end(),node))
            calls.append(node)
            continue
        calls.append(node)
        original = source[node.start:node.end]
        candidate = edit(source,[(node.start,node.end,'do { '+original+' } while (0);')])
        candidates.append((not bool(floats & set(re.findall(IDENT,text))),node.start,candidate))
    return [(FAMILIES[0],c) for _,_,c in sorted(candidates)[:LIMIT]]+shifted(source,wrapped,calls)


def shifted(source, wrapped, calls):
    """Move an existing one-shot wrapper to the call statement just before or after it.

    The wrapper's loop notes are a scheduling barrier: what may float across a call depends on which call it
    fences. An N64 init function matched only once the wrapper moved from `f(D_x);` to the call before it,
    letting the loop-hoisted constants rise past `f`, while the first call kept the base-relative stores
    the wrapper was there for. Adding or removing a wrapper alone made it worse; moving it is one step."""
    result = []
    order = sorted({node.start: node for node in calls}.values(), key=lambda node: node.start)
    inside = {node.start for _,_,node in wrapped}
    for start,end,node in wrapped:
        index = [n.start for n in order].index(node.start)
        for other in (order[index-1] if index else None, order[index+1] if index+1 < len(order) else None):
            if other is None or other.start in inside:
                continue
            original = source[other.start:other.end]
            result.append((SHIFT,edit(source,[(start,end,source[node.start:node.end]),
                                              (other.start,other.end,'do { '+original+' } while (0);')])))
    return result[:LIMIT]
