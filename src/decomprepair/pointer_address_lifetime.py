"""Stage a fixed global address in a dead pointer across a straight-line call.

Only the address moves. The actual pointer load stays in the original argument,
so a call between the capture and the load may still change the stored pointer.
"""
import itertools
import re

from . import integer_abi, local_flow, pointer_pair_repairs
from .csource import _blank
from .integer_repair_support import IDENT, edit, split_args, view
from .pattern_repairs import close

FAMILY = 'pointer_address_lifetime'
LIMIT = 4
WINDOW = 10

_DIRECTIVE = re.compile(r'(?m)^[ \t]*#([^\n]*)')
_WORD = re.compile(IDENT)
_CALL = re.compile(rf'({IDENT})\s*\(')
_LOAD = re.compile(rf'\(\s*({IDENT})\s*\*\s*\*\s*\)\s*(.*)', re.S)
_ADDRESS = re.compile(rf'({IDENT})\s*\+\s*(0[xX][0-9a-fA-F]+|[0-9]+)')
_ASSIGN = re.compile(rf'({IDENT})\s*=\s*({IDENT})\s*;')
_NONLOCAL = re.compile(r'\b(?:asm|__asm__|setjmp|_setjmp|sigsetjmp|longjmp)\b')


def _views(source, name):
    """Analyze each configuration of up to two #ifdef names, keeping source offsets."""
    clean = _blank(source)
    directives = list(_DIRECTIVE.finditer(clean))
    if any(m[1].rstrip().endswith('\\') for m in directives):
        return []
    conditions = set()
    for directive in directives:
        words = directive[1].split()
        if words and words[0] in ('ifdef', 'ifndef') and len(words) == 2 and _WORD.fullmatch(words[1]):
            conditions.add(words[1])
        elif not words or words[0] not in ('define', 'else', 'endif'):
            return []
    if len(conditions) > 2:
        return []
    result = []
    names = sorted(conditions)
    for values in itertools.product((False, True), repeat=len(names)):
        defines = dict(zip(names, values))
        stack = []
        active = True
        cursor = 0
        chunks = []

        def blank(text):
            return re.sub(r'[^\n]', ' ', text)

        for directive in directives:
            chunk = source[cursor:directive.start()]
            chunks.append(chunk if active else blank(chunk))
            chunks.append(blank(directive[0]))
            cursor = directive.end()
            kind, *args = directive[1].split()
            if kind in ('ifdef', 'ifndef'):
                selected = defines[args[0]] == (kind == 'ifdef')
                stack.append((active, selected, False))
                active = active and selected
            elif kind == 'else' and stack and not stack[-1][2] and not args:
                outer, selected, _ = stack[-1]
                stack[-1] = (outer, selected, True)
                active = outer and not selected
            elif kind == 'endif' and stack and not args:
                active = stack.pop()[0]
            elif kind != 'define':
                return []
        if stack:
            return []
        chunks.append(source[cursor:])
        part = view(''.join(chunks), name)
        if not part or _NONLOCAL.search(part.clean):
            return []
        result.append(part)
    return result


def _unwrap(text):
    text = text.strip()
    while text.startswith('(') and close(text, 0) == len(text):
        text = text[1:-1].strip()
    return text


def _argument(text):
    """Recognize a single typed pointer load from a byte-array base plus a literal."""
    text = _unwrap(text)
    cast = re.match(rf'\(\s*({IDENT})\s*\*\s*\)\s*', text)
    deref = _unwrap(text[cast.end():] if cast else text)
    if not deref.startswith('*'):
        return None
    load = _LOAD.fullmatch(_unwrap(deref[1:]))
    if not load or cast and cast[1] != load[1]:
        return None
    operand = load[2].strip()
    address = _unwrap(operand)
    if address == operand:
        return None  # An unparenthesized addition would be outside the load.
    parts = _ADDRESS.fullmatch(address)
    if parts:
        return load[1], address, parts[1]
    return None


def _straight_predecessors(flow, incoming, sink):
    current = sink
    trail = []
    for _ in range(WINDOW):
        if len(incoming[current]) != 1:
            break
        previous = incoming[current][0]
        node = flow.nodes[previous]
        if node.successors != {current} or node.end > flow.nodes[current].start:
            break
        trail.append(node)
        yield node, trail
        current = previous


def _sites(part, header, hidden, qualified, macros):
    pointers = [d for d in pointer_pair_repairs.declarations(part) if d['name'] not in hidden]
    context = header + '\n' + part.clean[:part.opening]
    # Only single-level pointer objects whose alignment is compatible with an
    # existing pointer-sized load on the supported O32 target.
    donors = [d for d in pointers if (typ := d['type'].rstrip('*').strip()) == 'void'
              or integer_abi.scalar(typ, context, 'mips') in {(32, True), (32, False)}]
    donors = [d for d in donors if d['type'].count('*') == 1
              and not qualified.intersection(_WORD.findall(d['type']))]
    if not donors:
        return []
    try:
        flow = local_flow.Flow(part, donors)
    except (ValueError, RecursionError):
        return []
    addresses = set(re.findall(rf'\bextern\s+(?:(?:signed|unsigned)\s+)?char\s+({IDENT})\s*\[\s*\]\s*;',
                               context)) - macros
    loads = set(re.findall(rf'\bextern\s+(?:struct\s+)?{IDENT}\s*\*\s*({IDENT})\s*;', context)) - macros
    # A visible global's name must not designate a different object in the body.
    active = part.clean[part.clean.rfind(';', 0, part.opening)+1:part.end]
    shadowed = set(re.findall(rf'\b{IDENT}(?:\s+\**\s*|\s*\*+\s*)({IDENT})\s*(?=[;,=)\[])', active))
    addresses -= shadowed
    loads -= shadowed
    incoming = [[] for _ in flow.nodes]
    for i, node in enumerate(flow.nodes):
        for successor in node.successors:
            incoming[successor].append(i)
    result = []
    for i, sink in enumerate(flow.nodes):
        call = _CALL.match(part.clean, sink.start, sink.end)
        if not call or call[1] in macros or call[1] in shadowed:
            continue
        stop = close(part.clean, call.end()-1)
        if stop is None or part.clean[stop:sink.end].strip() != ';':
            continue
        for a, b in split_args(part.clean[call.end():stop-1]):
            a, b = a+call.end(), b+call.end()
            while a < b and part.clean[a].isspace():
                a += 1
            while b > a and part.clean[b-1].isspace():
                b -= 1
            arg = _argument(part.clean[a:b])
            if not arg or arg[2] not in addresses or arg[0] in qualified:
                continue
            for anchor, trail in _straight_predecessors(flow, incoming, i):
                assignment = _ASSIGN.fullmatch(part.clean[anchor.start:anchor.end])
                prefix = part.clean[:anchor.start].rstrip()
                if not assignment or assignment[2] not in loads or prefix[-1:] not in ';{}':
                    continue
                # Keep this a call-spanning allocation repair, and never insert a
                # statement as the second half of an unbraced arm.
                if not any(_CALL.match(part.clean, n.start, n.end) for n in trail):
                    continue
                line = part.clean.rfind('\n', 0, anchor.start)+1
                indent = part.clean[line:anchor.start]
                if indent.strip():
                    continue
                for donor in donors:
                    var = donor['name']
                    if donor.end() > anchor.start or var in sink.live or any(
                            var in n.live or var in n.defines for n in trail):
                        continue
                    # Only reuse a pointer with a separate, later address-taking
                    # assignment and a real use. Other arms may skip that phase.
                    if not any(n.start > sink.end and var in n.defines and re.match(
                            rf'{var}\s*=\s*&', part.clean[n.start:n.end]) for n in flow.nodes):
                        continue
                    if not any(n.start > sink.end and var in n.uses for n in flow.nodes):
                        continue
                    typ, address, _ = arg
                    result.append(((anchor.start, anchor.start, f'{var} = (void *)({address});\n{indent}'),
                                   (a, b, f'*({typ} **){var}')))
                    if len(result) >= LIMIT:
                        return result
    return result


def variants(source, name, header=''):
    """Propose edits that have the same liveness proof in every supported branch."""
    header = _blank(header)
    clean = _blank(source)
    combined = header + '\n' + clean
    if re.search(r'\\\r?\n', combined):
        return []
    directives = [m[1] for m in _DIRECTIVE.finditer(combined)]
    for match in re.finditer(r'(?m)^[ \t]*#[ \t]*include\b([^\n]*)', header):
        # Other headers can hide macro invocations from the liveness reader.
        if match[1].strip() not in ('<stdint.h>', '<stdarg.h>'):
            return []
    definitions = [d for d in directives if re.match(r'\s*define\b', d)]
    if any(re.search(r'##|[;{}]|\b(?:goto|return|break|continue|case|default|asm|__asm__|longjmp)\b', d)
           for d in definitions):
        return []
    macros = {m[1] for d in definitions if (m := re.match(rf'\s*define\s+({IDENT})', d))}
    hidden = set(_WORD.findall(' '.join(definitions)))
    # A macro argument can hide an address-of (and therefore an escape) even
    # when the macro definition does not name the local that it captures.
    for call in _CALL.finditer(clean):
        if call[1] in macros:
            end = close(clean, call.end()-1)
            if end is None:
                return []
            hidden.update(_WORD.findall(clean[call.end():end-1]))
    qualified = macros | pointer_pair_repairs.qualified_types(
        re.sub(r'\b(?:const|_Atomic)\b', 'volatile', header+'\n'+_blank(source)))
    views = _views(source, name)
    if not views:
        return []
    candidates = _sites(views[0], header, hidden, qualified, macros)
    for part in views[1:]:
        available = set(_sites(part, header, hidden, qualified, macros))
        candidates = [c for c in candidates if c in available]
    return [(FAMILY, edit(source, changes)) for changes in candidates]
