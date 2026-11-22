"""Reuse a dead word local for zero-only tests, retaining declarations used by debug-era allocation."""
import re

from . import local_flow
from .csource import _blank, find
from .integer_repair_support import edit, refs
from .pointer_pair_repairs import context, initialized

FAMILIES=('word_zero_test_reuse', 'kmc_pointer_zero_identity')
WORD={'s32','u32','int','unsigned int','signed int'}


def pointer_zero_identity(source, name, arch, header=''):
    """Keep an initialized pointer live through a zero initializer for GCC scheduling.

    On KMC GCC the combiner folds x & ~x to zero after CSE, allowing a zero
    register copy to survive. Limit it to an adjacent initialized pointer and
    word local on 32-bit MIPS, where the u32 pointer conversion is supported.
    """
    if arch != 'mips' or not re.search(r'\bu32\b', source + header):return []
    span=find(source,name)
    if not span:return []
    clean=_blank(source)
    part=clean[span[0]:span[1]]
    pattern=(r'\b(?:char|s8|u8|void)\s*\*\s*(?P<pointer>[A-Za-z_]\w*)\s*=\s*'
             r'[A-Za-z_]\w*\s*;\s*(?:s32|u32|int|unsigned int)\s+[A-Za-z_]\w*\s*=\s*(?P<zero>0)\s*;')
    result=[]
    for hit in re.finditer(pattern,part):
        pointer=hit['pointer']
        expression=f'(u32){pointer} & ~(u32){pointer}'
        result.append((FAMILIES[1],edit(source,[(span[0]+hit.start('zero'),span[0]+hit.end('zero'),expression)])))
        if len(result)==4:break
    return result


def variants(source,name,arch,header=''):
    if arch not in {'mips','ppc','x86','arm','thumb'}:return []
    part,_,_=context(source,name,header)
    if part is None:return []
    flow=local_flow.analyze(source,name)
    if not flow:return []
    out=pointer_zero_identity(source,name,arch,header)
    # Reaching a use through a different predecessor would need a separate assignment.
    predecessors={i:set() for i in range(len(flow.nodes))}
    for i,node in enumerate(flow.nodes):
        for successor in node.successors:predecessors[successor].add(i)
    for old in flow.locals:
        if old['type'] not in WORD or not initialized(flow,old['name']):continue
        for index,node in enumerate(flow.nodes):
            text=flow.part.clean[node.start:node.end]
            assignment=re.fullmatch(rf'\s*({re.escape(old["name"])})\s*=(?!=).*;\s*',text,re.S)
            if not assignment:continue
            region=set();pending=list(node.successors);uses=[];use_nodes=set();valid=True
            while pending and len(region)<128:
                current=pending.pop()
                if current in region:continue
                following=flow.nodes[current]
                if old['name'] in following.defines:continue
                region.add(current)
                if old['name'] in following.uses:
                    condition=flow.part.clean[following.start:following.end]
                    if not re.fullmatch(rf'\s*{re.escape(old["name"])}\s*(?:==|!=)\s*0\s*',condition):valid=False;break
                    use_nodes.add(current)
                    uses.extend(h for h in refs(flow.part,old) if following.start<=h.start()<following.end)
                pending.extend(following.successors)
            if pending or not valid or not uses:continue
            # Retain only paths leading to an old-value read. Back edges after its next
            # definition do not belong to this phase; external entries to a selected use do.
            active=set();pending=list(use_nodes)
            while pending:
                current=pending.pop()
                if current in active:continue
                active.add(current);pending.extend(predecessors[current]&region-active)
            if any(predecessors[i]-active-{index} for i in active):continue
            region=active
            for target in flow.locals:
                if target['name']==old['name'] or target['type'] not in WORD:continue
                if target.end()>node.start or any(target['name'] in flow.nodes[i].live|flow.nodes[i].defines|flow.nodes[i].uses for i in region|{index}):continue
                edits=[(node.start+assignment.start(1),node.start+assignment.end(1),target['name'])]
                edits += [(h.start(),h.end(),target['name']) for h in uses]
                out.append((FAMILIES[0],edit(source,edits)))
                if len(out)==6:return out
    return out
