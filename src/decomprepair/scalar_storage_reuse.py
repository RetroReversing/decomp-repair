"""Share proven-disjoint integer storage, preserving the replaced local's conversions.

Compiler lines rank hypotheses only. CFG liveness and dominating definitions establish
eligibility; the ordinary judge alone establishes a match. No register is prescribed.
"""
import hashlib
import re

from . import integer_abi, local_flow, repair_localisation
from .allocator_call_guards import dominators
from .call_lifetime_repairs import block_path
from .integer_repair_support import edit, refs

FAMILY = 'scalar_storage_reuse'
FAMILIES = (FAMILY,)
LIMIT = 12


def contains(wide, narrow):
    if wide is None or narrow is None:return False
    a, signed_a = wide
    b, signed_b = narrow
    return a >= b if signed_a == signed_b else signed_a and a > b


def initialized(flow, decl, dom):
    name = decl['name']
    definitions = [i for i,n in enumerate(flow.nodes) if name in n.defines
                   and not n.start <= decl.start() < n.end]
    return bool(definitions) and all(name not in n.uses or any(j != i and j in dom.get(i,set()) for j in definitions)
                                     for i,n in enumerate(flow.nodes))


def variants(source, name, header='', arch=None, locations=None):
    flow = local_flow.analyze(source,name)
    if not flow or arch not in integer_abi.ARCHES:return []
    part = flow.part
    context = header+'\n'+source
    from .equal_value_flow import macros_safe
    if not macros_safe(source,header,part.body,{d['name']:d['type'] for d in flow.locals}):return []
    # Macro aliases, type-observing expressions and source-dependent expansion need
    # a richer parser. Keep ordinary unrelated macros opaque, but never rewrite them.
    macros = re.findall(r'(?m)^\s*#\s*define(?:[^\n\\]|\\[^\n]|\\\n)*',context)
    if re.search(r'\b(?:__LINE__|__COUNTER__|__FILE__|typeof|__typeof__|_Generic)\b',context):return []
    declarations = [d for d in flow.locals if block_path(part,d.start()) == [part.opening]]
    dom = dominators(flow)
    references = {d['name']: refs(part, d) for d in declarations}
    declarations = [d for d in declarations if references[d['name']] and initialized(flow,d,dom)
                    and not any(re.search(r'\b'+re.escape(d['name'])+r'\b',m) for m in macros)]
    relevant = repair_localisation.lines(source,locations)
    registers=((locations or {}).get('mapping') or {}).get('scalar_registers',{}) if (
        isinstance(locations,dict) and locations.get('source_sha256')==hashlib.sha256(source.encode()).hexdigest()) else {}
    def target_register(decl):
        nodes=[n for n in flow.nodes if n.defines=={decl['name']} and not n.start <= decl.start() < n.end]
        values={registers.get(str(source.count('\n',0,n.start)+1)) for n in nodes}
        values.discard(None)
        return next(iter(values)) if len(values)==1 else None
    widths = {typ: integer_abi.scalar(typ, context, arch) for typ in {d['type'] for d in declarations}}
    use_lines = {d['name']: {source.count('\n', 0, hit.start()) + 1 for hit in references[d['name']]}
                 for d in declarations}
    use_counts = {d['name']: sum(d['name'] in node.uses for node in flow.nodes) for d in declarations}
    target_registers = {d['name']: target_register(d) for d in declarations} if registers else {}
    choices = []
    for donor in declarations:
        donor_name = donor['name']
        wide = widths[donor['type']]
        if not wide or wide[0] != 32:continue
        for old in declarations:
            narrow = widths[old['type']]
            if (donor is old or not contains(wide,narrow) or (wide != narrow and not wide[1])
                    or not local_flow.disjoint(flow,donor,old)):continue
            variable = old['name']
            # Keeping the declaration avoids an unrelated debug-line/declaration-order
            # mutation. It becomes unused; the compiler remains free to allocate storage.
            uses = references[variable]
            definitions=[n for n in flow.nodes if variable in n.defines and not n.start <= old.start() < n.end]
            if len(definitions)!=1:continue
            # Prefer a value phase over changing branch selectors/loop conditions.
            # Reusing selectors is a separate family; it can crowd this bounded lane.
            if any(not part.clean[n.start:n.end].rstrip().endswith(';') for n in flow.nodes if variable in n.uses):continue
            if any(re.search(r'\b(?:sizeof|_Alignof)\s*\(?\s*'+re.escape(variable)+r'\b',part.clean[n.start:n.end])
                   for n in flow.nodes):continue
            changes = []
            covered = set()
            safe = True
            for hit in uses:
                node = flow.at(hit.start())
                if node is None:safe=False;break
                text = part.clean[node.start:node.end]
                writes = re.search(r'\b'+re.escape(variable)+r'\s*(?:\+\+|--|(?:<<|>>|[+*/%&|^\-])?=(?!=))|(?:\+\+|--)\s*\b'+re.escape(variable)+r'\b',text)
                if not writes:continue
                assignment = re.fullmatch(r'\s*'+re.escape(variable)+r'\s*=(?!=)\s*(?P<rhs>[^;{}]+);\s*',text)
                if not assignment or variable in node.uses:safe=False;break
                start,end=node.start+assignment.start('rhs'),node.start+assignment.end('rhs')
                rhs=source[start:end].rstrip()
                # A narrow value must be normalized at the original assignment, not
                # merely at a later call: promotions and subsequent uses depend on it.
                replacement = rhs if wide == narrow else f'({old["type"]})({rhs})'
                changes.append((start,end,replacement))
                changes.append((hit.start(),hit.end(),donor['name']))
                covered.update(h.start() for h in uses if node.start <= h.start() < node.end)
            if not safe:continue
            changes += [(h.start(),h.end(),donor['name']) for h in uses if h.start() not in covered]
            candidate=edit(source,list(dict.fromkeys(changes)))
            if candidate==source:continue
            touched = use_lines[variable] | use_lines[donor_name]
            # Fresh compiler associations guide the shortlist without removing broad
            # exploration when mappings are absent/stale or allocation moved elsewhere.
            register = target_registers.get(donor_name)
            affinity = register is not None and register == target_registers.get(variable)
            rank=(not affinity,not bool(touched & relevant), wide == narrow,
                  -use_counts[donor_name],donor.start(),old.start())
            choices.append((rank,candidate))
    return [(FAMILY,s) for s in dict.fromkeys(s for _,s in sorted(choices,key=lambda p:p[0]))][:LIMIT]
