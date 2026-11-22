"""Bounded legacy-GCC allocation hypotheses; the ordinary judge remains authoritative.

One-shot scopes can change loop-weighted pseudo references without adding a runtime
iteration. Only complete scalar updates, pointer loads or quotient assignments are wrapped,
so control transfers cannot change target.
"""
import re

from . import local_flow
from .equal_value_flow import macros_safe
from .integer_repair_support import IDENT, INTEGER, NUMBER, edit, locals_for, view
from .pattern_repairs import close

COUNTER_HOIST = 'loop_counter_init_hoist'
COUNTER_SINK = 'loop_counter_init_sink'
FAMILIES = ('loop_weight_scope', 'equal_value_increment', COUNTER_HOIST, COUNTER_SINK)
UPDATE_LIMIT = 12
LIMIT = 18
QUOTIENT_LIMIT = 6
QUOTIENT_UPDATE_LIMIT = 8
QUOTIENT_LOAD_LIMIT = 4


def _without_volatile_scratch(part):
    """The function text minus `volatile T pad;` declarations nothing else mentions.

    A volatile scratch only reserves frame (the original declared one the compiler kept in memory); it is never read
    or written, so it can hide no access a one-shot scope could reorder. A volatile that is used stays a refusal.
    """
    text = part.clean[part.opening:part.end]
    for decl in list(re.finditer(rf'\bvolatile\s+(?:unsigned\s+|signed\s+)?(?:char|short|int|long|[su](?:8|16|32))\s+(?P<n>{IDENT})\s*;', text)):
        if len(re.findall(rf'\b{re.escape(decl["n"])}\b', text)) == 1:
            text = text.replace(decl.group(0), ' ')
    return text


def variants(source, name, header='', *, focus_lines=(), depths=(1,2,3)):
    part = view(source, name)
    if not part or '__repair_loop_weight' in source or '__repair_equal_value' in source or re.search(r'\b(?:volatile|asm|__asm__)\b', _without_volatile_scratch(part)):
        return []
    # Unknown macros can hide control transfers, writes or address escapes.
    declarations = {d['name']:d['type'] for d in locals_for(part)}
    load_declarations = set(declarations)
    for decl in re.finditer(rf'(?<=[;{{}}])\s*{INTEGER}\s+(?P<name>{IDENT})\s*=',part.clean[part.opening:part.end]):
        load_declarations.add(decl['name'])
    if not macros_safe(source,header,part.body,load_declarations):return []
    updates = []
    pattern = rf'(?<=[;{{}}])\s*(?:\+\+(?P<pre>{IDENT})|(?P<post>{IDENT})\+\+|(?P<add>{IDENT})\s*\+=\s*(?P<rhs>{IDENT}|1)|(?P<self>{IDENT})\s*=\s*(?P=self)\s*\+\s*(?P<value>{IDENT}|1))\s*;'
    for hit in re.compile(pattern).finditer(part.clean,part.opening,part.end-1):
        variable = hit['pre'] or hit['post'] or hit['add'] or hit['self']
        if variable not in declarations:
            continue
        updates.append(hit)
    out = []
    for hit in updates[-3:]:
        groups = [(hit.start(),hit.end())]
        previous = next((p for p in updates if p.end()==hit.start()),None)
        if previous:
            groups.append((previous.start(),hit.end()))
        for start,end in groups:
            statement = source[start:end]
            for depth in (1,3):
                wrapper = '/*__repair_loop_weight*/'+'do {'*depth+statement+'} while (0);'*depth
                out.append((FAMILIES[0],edit(source,[(start,end,wrapper)])))
    # A straight-line equal-value copy followed by increment: keep its earlier
    # pseudo live. No call, branch, intervening assignment or narrowing allowed.
    pattern = rf'(?<=[;{{}}])\s*({IDENT})\s*=\s*({IDENT})\s*;\s*(?:\+\+\s*\2|\2\s*\+\+|\2\s*\+=\s*1)\s*;'
    for hit in re.compile(pattern).finditer(part.clean,part.opening,part.end-1):
        earlier,current = hit[1],hit[2]
        if earlier==current or earlier not in declarations or declarations.get(current)!=declarations[earlier]:
            continue
        replacement = f'/*__repair_equal_value*/\n{earlier} = {current}; {current} = {earlier} + 1;'
        out.insert(0,(FAMILIES[1],edit(source,[(hit.start(),hit.end(),replacement)])))
    # A load into a real scalar can change reference weights independently of
    # the following pointer chain. Keep it isolated: no calls, macros, labels,
    # indexing, compound expressions or declarations inside the new scope.
    loads = []
    cast = rf'(?:\(\s*(?:{IDENT}\s+)*{IDENT}\s*\*\s*\)\s*)?'
    pattern = rf'(?<=[;{{}}])\s*(?P<dest>{IDENT})\s*=\s*\*\s*{cast}(?P<pointer>{IDENT})\s*;'
    for hit in re.compile(pattern).finditer(part.clean,part.opening,part.end-1):
        prefix = part.clean[part.opening:hit.start()]
        if hit['dest'] not in load_declarations or prefix.count('(')!=prefix.count(')') or prefix.count('[')!=prefix.count(']'):
            continue
        for depth in (1,2,3):
            wrapper = '/*__repair_loop_weight*/'+'do {'*depth+source[hit.start():hit.end()]+'} while (0);'*depth
            loads.append((FAMILIES[0],edit(source,[(hit.start(),hit.end(),wrapper)])))
        if len(loads) >= 6:
            break
    divisions = quotient_scopes(source,part,load_declarations,focus_lines=focus_lines,depths=depths)
    inits = counter_init_scopes(source, name, part, declarations)
    if inits:
        # A counter's constant start is the cheapest weight lever and the only one that needs no loop edit.
        out = inits+out
    if divisions:
        if focus_lines:return divisions[:18]
        # Reserve room for the new operation even in update-heavy functions.
        return (divisions[:QUOTIENT_LIMIT]+list(dict.fromkeys(out))[:QUOTIENT_UPDATE_LIMIT]
                +list(dict.fromkeys(loads))[:QUOTIENT_LOAD_LIMIT])
    # the counters' starts are extra: they are the cheapest lever, and a function with several counters would
    # otherwise lose its later ones (and the in-place depth-1 wrapper, the one that matched) to the update limit
    return list(dict.fromkeys(out))[:UPDATE_LIMIT+len(inits)]+list(dict.fromkeys(loads))[:LIMIT-UPDATE_LIMIT]


def quotient_scopes(source, part, declarations, *, focus_lines=(), depths=(1,2,3)):
    """Wrap an actual quotient statement, retaining every operand and its evaluation.

    A one-shot scope can change legacy GCC's loop-weighted reference counts. It
    must not capture a loop-header clause, an unbraced body or hidden control.
    """
    if re.search(r'\b(?:goto|__attribute__|__declspec|typeof|__typeof__|__extension__)\b|\(\s*{',part.body):
        return []
    assignments=[]
    pattern=rf'(?<=[;{{}}])\s*(?P<dest>{IDENT})\s*=(?!=)(?P<rhs>[^;{{}}]+);'
    for hit in re.compile(pattern).finditer(part.clean,part.opening,part.end-1):
        rhs=hit['rhs']
        if hit['dest'] not in declarations or '/' not in rhs:
            continue
        # No calls, updates, secondary assignments, labels or extensions. Casts,
        # ordinary arithmetic and array/member reads retain their original text.
        if (re.search(r'[=?:,#\\]|\+\+|--|\b'+IDENT+r'\s*\(',rhs)
                or re.search(r'[^\w\s()+*/%<>&|^~!\[\].-]',rhs)):
            continue
        prefix=part.clean[part.opening:hit.start()]
        if prefix.count('(')!=prefix.count(')') or prefix.count('[')!=prefix.count(']'):
            continue
        if rhs.count('(')!=rhs.count(')') or rhs.count('[')!=rhs.count(']'):
            continue
        assignments.append(hit)
    # First and last eligible sites give diversity without an unbounded scan's
    # worth of candidates crowding out the existing update and load hypotheses.
    if focus_lines:
        def distance(hit):
            first=source.count('\n',0,hit.start('dest'))+1;last=source.count('\n',0,hit.end())+1
            return min(0 if first<=n<=last else min(abs(n-first),abs(n-last)) for n in focus_lines)
        selected=[hit for hit in sorted(assignments,key=distance) if distance(hit)==0][:6]
    else:selected=assignments[:1]+assignments[-1:] if len(assignments)>1 else assignments
    result=[]
    pairs=[(h,d) for d in depths for h in selected] if focus_lines else [(h,d) for h in selected for d in depths]
    for hit,depth in pairs:
        if depth not in (1,2,3):continue
        statement=source[hit.start('dest'):hit.end()]
        leading=source[hit.start():hit.start('dest')]
        if '\n' in leading and not leading.strip():
            indent=leading.rsplit('\n',1)[1]
            wrapper=leading+'/*__repair_loop_weight*/'+'do {\n'+indent
            wrapper+=('do {\n'+indent)*(depth-1)+statement+('\n'+indent+'} while (0);')*depth
        else:
            wrapper='/*__repair_loop_weight*/'+'do {'*depth+source[hit.start():hit.end()]+'} while (0);'*depth
        result.append((FAMILIES[0],edit(source,[(hit.start(),hit.end(),wrapper)])))
    return result


COUNTER_INIT_LIMIT = 24


def counter_init_scopes(source, name, part, declarations):
    """Weight a loop counter's constant start, in place or ahead of the guard that holds it.

    GCC 2.x hands temporaries registers in order of floor_log2(refs) * refs / live length, a reference inside a loop
    counting once per loop it sits in. A counter that is only set, stepped and compared has few references, so it is
    ranked below the induction pointer it drives and gets the later register. `do { k = 0; } while (0);` is one more
    loop around the start (weight 2 instead of 1), at no runtime or instruction cost, and a start written before the
    `if (n > 0) { do { ... } while (...); }` that guards the loop (instead of inside it) also lengthens the counter's
    range by the guard. A KMC 2.7.2 function (an edge-linking loop, 35 -> 0): the counter needed ten references and a
    longer range to land between the loaded halfword (it kept the first temporary) and the induction pointer.
    Only `name = <literal>;` of a declared integer local that is stepped later (`++`, `+= <literal>`, `= name + <literal>`) is wrapped
    (a byte offset that advances by a structure's size is a counter as much as an index that advances by one).
    """
    groups, bare, sunk = [], [], []
    flow = None
    checked_flow = False
    pattern = rf'(?<=[;{{}}])(?P<lead>\s*)(?P<var>{IDENT})\s*=\s*(?P<value>{NUMBER})\s*;'
    for hit in re.compile(pattern).finditer(part.clean, part.opening, part.end-1):
        variable = hit['var']
        if variable not in declarations:
            continue
        stepped = re.search(rf'\b{re.escape(variable)}\s*(?:\+\+|\+=\s*{NUMBER}\b|=\s*{re.escape(variable)}\s*\+\s*{NUMBER}\b)|\+\+\s*{re.escape(variable)}\b',
                            part.clean[hit.end():part.end])
        if not stepped:
            continue
        prefix = part.clean[part.opening:hit.start()]
        if prefix.count('(') != prefix.count(')') or prefix.count('[') != prefix.count(']'):
            continue
        statement = source[hit.start('var'):hit.end()]
        sunk.extend(_sunk_starts(source, part, hit))
        spans = [(hit.start('var'), hit.end(), None)]
        guard = _enclosing_guard(part, hit.start())
        if guard:
            # Moved out only when nothing of the guard's block comes before the start, so no read of the counter
            # can see the other value, and the counter is declared (and so exists) before the guard.
            declared = re.search(rf'\b(?:{INTEGER})\s+{re.escape(variable)}\s*[;=,]', part.clean[part.opening:guard[0]])
            between = part.clean[guard[1]+1:hit.start()]
            if declared and not re.search(rf'\b{re.escape(variable)}\b', part.clean[guard[0]:guard[1]+1]) \
                    and not re.search(rf'\b{re.escape(variable)}\b', between) \
                    and not re.search(r'\b(?:goto|return|break|continue)\b|\bwhile\b|\bdo\b|\bfor\b', between):
                spans.append((hit.start('var'), hit.end(), guard[0]))
                if not checked_flow:
                    flow = local_flow.analyze(source, name, declarations=locals_for(part),
                                              allow_unrelated_volatile=True)
                    checked_flow = True
                if len(bare) < 3 and _can_hoist(part, flow, guard, variable):
                    moved = guard[0]
                    indent = source[source.rfind('\n', 0, moved)+1:moved]
                    indent = indent[:len(indent)-len(indent.lstrip())]
                    bare.append((COUNTER_HOIST, edit(source, [(moved, moved, statement+'\n'+indent),
                                                             (hit.start('var'), hit.end(), '')])))
        per_hit = []
        # the start moved ahead of the guard first: it is the variant that also lengthens the counter's range
        for start, end, moved in reversed(spans):
            for depth in (3, 2, 1):
                wrapper = '/*__repair_loop_weight*/'+'do {'*depth+' '+statement+' '+'} while (0);'*depth
                if moved is None:
                    per_hit.append((FAMILIES[0], edit(source, [(start, end, wrapper)])))
                else:
                    indent = source[source.rfind('\n', 0, moved)+1:moved]
                    indent = indent[:len(indent)-len(indent.lstrip())]
                    per_hit.append((FAMILIES[0], edit(source, [(moved, moved, wrapper+'\n'+indent), (start, end, '')])))
        groups.append(per_hit)
    # round robin over the starts, so one counter's depths cannot crowd another counter out
    out = []
    for rank in range(max((len(g) for g in groups), default=0)):
        out.extend(g[rank] for g in groups if rank < len(g))
    return list(dict.fromkeys(out))[:COUNTER_INIT_LIMIT] + list(dict.fromkeys(bare)) + list(dict.fromkeys(sunk))[:6]


SINK_STATEMENTS = 12


def _sunk_starts(source, part, hit):
    """A counter's constant start written ahead of unrelated statements, moved down to the one that first needs it.

    m2c places `i = 0;` where the decompiler saw the register set, often before several calls and stores the loop
    never touches. GCC 2.x ranks temporaries by floor_log2(refs) * refs / live length, so those statements are live
    length the counter does not have in the original: a counter that should outrank the loop's other temporary (and so
    take the earlier saved register) ranks below it. Sinking the start to just before the statement that first mentions
    the counter (the `if` that guards the loop, or the loop) shortens the range and raises the priority, at no runtime
    cost. Only plain statements are crossed, none mentioning the counter, and never when its address is taken. Both
    the full sink and one statement short of it are offered (the scheduler may want the start one call earlier).
    """
    variable = hit['var']
    text = part.clean[part.opening:part.end]
    if re.search(rf'&\s*{re.escape(variable)}\b', text):
        return []
    prefix = part.clean[part.opening:hit.start()]
    if prefix.count('(') != prefix.count(')') or prefix.count('[') != prefix.count(']'):
        return []
    crossed, before = [], hit.end()
    for stop in _plain_statement_ends(part.clean, hit.end(), part.end - 1, SINK_STATEMENTS):
        if re.search(rf'\b{re.escape(variable)}\b', part.clean[before:stop]):
            break
        crossed.append(stop)
        before = stop
    if not crossed:
        return []
    # what follows the last crossed statement must be what needs the counter (the loop or its guard, or a plain
    # statement that reads it); otherwise nothing is gained
    if not re.search(rf'\b{re.escape(variable)}\b', part.clean[crossed[-1]:part.end - 1]):
        return []
    statement = source[hit.start('var'):hit.end()]
    indent = source[hit.start():hit.start('var')].rsplit('\n', 1)[-1]
    out = []
    for stop in dict.fromkeys([crossed[-1], crossed[-2] if len(crossed) > 1 else crossed[-1]]):
        out.append((COUNTER_SINK, edit(source, [(hit.start(), hit.end(), ''), (stop, stop, '\n' + indent + statement)])))
    return out


_CONTROL = re.compile(r'\s*(?:if|else|do|while|for|switch|case|default|goto|return|break|continue)\b|\s*\w+\s*:(?!:)')


def _plain_statement_ends(clean, position, end, limit):
    """Ends of the plain (no braces, no control, no label) statements that follow `position`."""
    stops = []
    while len(stops) < limit:
        if not clean[position:end].strip() or clean[position:end].lstrip().startswith(('{', '}')) or _CONTROL.match(clean, position):
            break
        depth, stop = 0, position
        while stop < end:
            depth += (clean[stop] in '([{') - (clean[stop] in ')]}')
            stop += 1
            if depth == 0 and clean[stop-1] == ';':
                break
        else:
            break
        stops.append(stop)
        position = stop
    return stops


def _can_hoist(part, flow, guard, variable):
    if flow is None or variable not in flow.names:
        return False
    start, brace = guard
    if not part.clean[part.opening:start].rstrip().endswith((';', '{', '}')):
        return False
    condition = next((node for node in flow.nodes if start < node.start < brace), None)
    if condition is None or variable in condition.live:
        return False
    end = close(part.clean, brace, '{', '}')
    return end is not None and not any(
        brace < flow.nodes[flow.labels[label]].start < end
        and not start <= flow.nodes[index].start < end
        for index, label in flow.gotos)


def _enclosing_guard(part, position):
    """(start of the `if`, its opening brace) of the innermost `if (...) {` block holding `position`, if any."""
    clean = part.clean
    best = None
    for hit in re.finditer(r'\bif\s*\(', clean[part.opening:position]):
        start = part.opening+hit.start()
        opening = clean.find('{', start)
        if opening < 0 or opening > position:
            continue
        paren = close(clean, clean.find('(', start), '(', ')')
        if not paren or clean[paren:opening].strip():
            continue
        end = close(clean, opening, '{', '}')
        if end and end > position:
            best = (start, opening)
    return best
