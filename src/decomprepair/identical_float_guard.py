"""Try a definitely initialized double as an identical-arm guard to alter its live range."""
import re

from .allocator_call_guards import dominators
from .integer_repair_support import IDENT, edit, view
from .local_flow import Flow
from .pattern_repairs import close

FAMILY = 'initialized_identical_float_guard'
LIMIT = 12


def variants(source, name, header='', arch=None):
    if arch != 'mips':
        return []
    part = view(source, name)
    if (not part or re.search(r'\b(?:asm|__asm__|setjmp|longjmp)\b', part.clean)
            or re.search(r'#\s*pragma\s+STDC\s+FENV_ACCESS\s+ON', header + '\n' + source)):
        return []
    # Reject preprocessor aliases for types and variable names used by this repair.
    macros = set(re.findall(r'^\s*#\s*define\s+('+IDENT+r')\b', header + '\n' + source, re.M))
    if {'f64', 'double', 'f32', 'float'} & macros:
        return []
    signature = part.clean[part.clean.rfind(name, 0, part.opening):part.opening]
    if re.search(r'\bvolatile\b', signature):
        return []
    floats = set(re.findall(r'\b(?:f32|float)\s+('+IDENT+r')\s*(?=[,)])', signature))
    declarations = []
    for decl in re.finditer(r'\b(?P<type>f64|double)\s+(?P<name>'+IDENT+r')\s*;', part.clean[part.opening+1:part.end]):
        start = part.opening + 1 + decl.start()
        # Top-level local, not a field, shadow or escaped object.
        prefix = part.clean[part.opening+1:start]
        if (prefix.count('{') != prefix.count('}') or decl['name'] in macros
                or re.search(r'&\s*\(*\s*'+re.escape(decl['name'])+r'\b', part.body)
                or len(re.findall(r'\b'+IDENT+r'\s+\**\s*'+re.escape(decl['name'])+r'\s*(?=[;=,\[])', part.body)) != 1
                or re.search(r'\b'+re.escape(decl['name'])+r'\b', signature)):
            continue
        # Match objects supplied to Flow must use absolute source positions.
        declarations.append(re.compile(r'\b(?P<type>f64|double)\s+(?P<name>'+IDENT+r')\s*;').match(part.clean, start))
    if not declarations:
        return []
    try:
        flow = Flow(part, declarations)
        dom = dominators(flow)
    except (ValueError, RecursionError):
        return []
    result = []
    for hit in re.finditer(r'\bif\s*\(\s*(?P<guard>'+IDENT+r')\s*\)\s*{', part.body):
        if (hit['guard'] not in floats or hit['guard'] in macros
                or re.search(r'\b(?:f32|float|f64|double|int)\s+\**\s*'+re.escape(hit['guard'])+r'\b', part.body)):
            continue
        first = part.opening + 1 + hit.end() - 1
        end = close(part.clean, first, '{', '}')
        other = re.match(r'\s*else\s*{', part.clean[end:]) if end else None
        if not other:
            continue
        second = end + other.end() - 1
        stop = close(part.clean, second, '{', '}')
        if not stop:
            continue
        left = re.sub(r'\s+', ' ', part.clean[first+1:end-1]).strip()
        right = re.sub(r'\s+', ' ', part.clean[second+1:stop-1]).strip()
        if not left or left != right:
            continue
        pos = part.opening + 1 + hit.start('guard')
        index = next((i for i, n in enumerate(flow.nodes) if n.start <= pos < n.end), None)
        if index is None or index not in dom:
            continue
        for decl in declarations:
            variable = decl['name']
            definitions = [i for i in dom[index] if i != index and re.fullmatch(
                r'\s*'+re.escape(variable)+r'\s*=(?!=)[^;]+;\s*', part.clean[flow.nodes[i].start:flow.nodes[i].end])
                and not re.search(r'\b'+re.escape(variable)+r'\b', part.clean[flow.nodes[i].start:flow.nodes[i].end].split('=', 1)[1])]
            if definitions:
                result.append((FAMILY, edit(source, [(pos, pos + len(hit['guard']), variable)])))
                if len(result) >= LIMIT:
                    return result
    return result
