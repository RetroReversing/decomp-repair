"""Try definitely initialized floats as identical-arm guards to alter their live ranges."""
import re

from .allocator_call_guards import dominators
from .integer_repair_support import IDENT, edit, view
from .local_flow import Flow
from .pattern_repairs import close

FAMILY = 'initialized_identical_float_guard'
NESTED = 'initialized_nested_float_guard'
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
    for decl in re.finditer(r'\b(?P<type>f64|double|f32|float)\s+(?P<name>'+IDENT+r')\s*;', part.clean[part.opening+1:part.end]):
        start = part.opening + 1 + decl.start()
        # Top-level local, not a field, shadow or escaped object.
        prefix = part.clean[part.opening+1:start]
        if (prefix.count('{') != prefix.count('}') or re.search(r'\bvolatile\s*$', prefix)
                or decl['name'] in macros
                or re.search(r'&\s*\(*\s*'+re.escape(decl['name'])+r'\b', part.body)
                or len(re.findall(r'\b'+IDENT+r'\s+\**\s*'+re.escape(decl['name'])+r'\s*(?=[;=,\[])', part.body)) != 1
                or re.search(r'\b'+re.escape(decl['name'])+r'\b', signature)):
            continue
        # Match objects supplied to Flow must use absolute source positions.
        declarations.append(re.compile(r'\b(?P<type>f64|double|f32|float)\s+(?P<name>'+IDENT+r')\s*;').match(part.clean, start))
    if not declarations:
        return []
    try:
        flow = Flow(part, declarations)
        dom = dominators(flow)
    except (ValueError, RecursionError):
        return []
    result = []
    for hit in re.finditer(r'\bif\s*\(\s*(?P<guard>'+IDENT+r')\s*\)\s*{', part.body):
        guard = hit['guard']
        if guard in macros or (guard not in floats and guard not in {d['name'] for d in declarations}):
            continue
        if guard in floats and re.search(r'\b(?:f32|float|f64|double|int)\s+\**\s*'+re.escape(guard)+r'\b', part.body):
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
        initialized = []
        for decl in declarations:
            variable = decl['name']
            definitions = [i for i in dom[index] if i != index and re.fullmatch(
                r'\s*'+re.escape(variable)+r'\s*=(?!=)[^;]+;\s*', part.clean[flow.nodes[i].start:flow.nodes[i].end])
                and not re.search(r'\b'+re.escape(variable)+r'\b', part.clean[flow.nodes[i].start:flow.nodes[i].end].split('=', 1)[1])]
            if definitions:
                initialized.append(decl)
        if guard in floats:
            for decl in initialized:
                if decl['type'] in {'f64', 'double'}:
                    result.append((FAMILY, edit(source, [(pos, pos + len(guard), decl['name'])])))
        elif guard in {d['name'] for d in initialized}:
            # Duplicate only a straight-line arm: adding blocks must not duplicate labels,
            # move declarations, or change the destination of a control transfer.
            if not re.search(r'[{}:]|\b(?:goto|break|continue|return|case|static|typedef|struct|union)\b'
                             r'|\b(?:int|char|short|long|float|double|[su](?:8|16|32)|f32|f64)\s+\**\s*'+IDENT+r'\b', left):
                arm = source[first+1:end-1]
                for decl in initialized:
                    if decl['type'] not in {'f32', 'float'} or decl['name'] == guard:
                        continue
                    nested = f" if ({decl['name']}) {{{arm}}} else {{{arm}}} "
                    result.append((NESTED, edit(source, [(first+1, end-1, nested)])))
                    result.append((NESTED, edit(source, [(second+1, stop-1, nested)])))
        if len(result) >= LIMIT:
            return result[:LIMIT]
    return result
