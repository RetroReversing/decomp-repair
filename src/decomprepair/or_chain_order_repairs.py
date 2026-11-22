"""A chain of `|` operands written in another association and order than the game's: the constant first.

m2c prints `(((x * 4) | 0xF6000000) | y)` for a word the game built as `0xF6000000 | y | x * 4` (a display-list
command: the opcode, then the fields from the highest shift down). The three operands are the same set, but gcc 2.7.2
combines them in the order the C parses them: the constant goes into a register of its own and is `or`ed first when it
is the first operand, and the two orders give different registers and a different instruction order downstream. A byte
identical N64 function needed exactly that order for each of its four command words (the other order scored 690 and
3160 instead of 0). `|` is associative and commutative, so every order means the same; this offers the chain flattened
and rewritten with the literal operand first and the others in each order, one chain at a time, for chains of three
or four side-effect-free operands. The judge picks the order.

A narrowly recognized unsigned pack can also stage the first OR and weight
the two shift definitions independently with one-shot scopes. This reproduces
a KMC GCC 2.7.2 allocation that closed a two-register mismatch (10 -> 0).
"""
import itertools
import re

from .integer_repair_support import IDENT, edit, view

FAMILY = 'or_chain_order'
WEIGHTED_FAMILY = 'weighted_or_pack'
FAMILIES = (FAMILY, WEIGHTED_FAMILY)
LIMIT = 10
PER_CHAIN = 6
LITERAL = re.compile(r'\s*(?:0[xX][0-9a-fA-F]+|\d+)[uUlL]*\s*\Z')
PLAIN = re.compile(rf'{IDENT}\Z')
# anything that is not a plain arithmetic operand: calls, assignments, comparisons, logic, the conditional
UNSAFE = re.compile(rf'{IDENT}\s*\(|[^=!<>]=[^=]|\+\+|--|==|!=|<=|>=|&&|\|\||\?|[^<]<[^<]|[^>]>[^>]|\bvolatile\b|[,;{{}}]')


def weighted_pack(source, part, header):
    """Stage a single unsigned pack and change the two shifts' loop weights.

    Each one-shot loop runs exactly once. The shifts, OR and store retain
    their order, and the temporary locals must be dead after the store.
    """
    if '__repair_or_part' in header + source or re.search(r'\bvolatile\b', part.body):
        return []
    pattern = (rf'\bu32\s+(?P<high>{IDENT})\s*=\s*(?P<value>{IDENT})\s*<<\s*16\s*;\s*'
               rf'u32\s+(?P<low>{IDENT})\s*=\s*(?P=value)\s*<<\s*8\s*;\s*'
               rf'do\s*{{\s*(?P<dest>{IDENT}(?:(?:->|\.){IDENT})*)\s*=\s*(?P<expr>[^;{{}}]+);'
               rf'\s*}}\s*while\s*\(\s*0\s*\)\s*;')
    macros = set(re.findall(rf'^\s*#\s*define\s+({IDENT})\b', header + '\n' + source, re.M))
    if {'u32', 'do', 'while'} & macros:
        return []
    for hit in re.finditer(pattern, part.clean, re.M):
        if not part.opening < hit.start() < hit.end() < part.end:
            continue
        high, low, value = hit['high'], hit['low'], hit['value']
        if len({high, low, value}) != 3 or {high, low, value} & macros:
            continue
        if re.search(r'\b(?:volatile|const|static|register)\s*$', part.clean[:hit.start()]):
            continue
        # The source value must itself be an unsigned local, not a volatile
        # read or a wider integer on which ~ has different promotions.
        if len(re.findall(rf'\bu32\s+{re.escape(value)}\b', part.clean)) != 1:
            continue
        if any(len(re.findall(rf'\b{IDENT}\s+(?:\*\s*)*{re.escape(n)}\b', part.clean)) != 1
               for n in (high, low, value)):
            continue
        if re.search(rf'\bvolatile\s+u32\s+{re.escape(value)}\b', part.clean):
            continue
        if re.search(r'\btypedef\b[^;]*\bvolatile\b[^;]*\bu32\s*;', header + '\n' + source):
            continue
        if any(re.search(rf'\b{re.escape(n)}\b', part.clean[hit.end():part.end]) for n in (high, low)):
            continue
        pieces = _split(hit['expr'])
        if not pieces:
            continue
        operands = [re.sub(r'\s+', '', item) for piece in pieces for item in _flatten(piece)]
        # The second form is the semantics-preserving OR identity offered by
        # this module; the original literal-first chain is its saved parent.
        literal = r'(0[xX][0-9a-fA-F]{1,8}[uU]?)'
        match = None
        if len(operands) == 4 and operands[1:] == [high, low, value]:
            match = re.fullmatch(literal, operands[0])
        elif len(operands) == 4 and operands[0] == high and operands[2:] == [low, value]:
            match = re.fullmatch(rf'~{low}&{literal}', operands[1])
        if not match:
            continue
        constant = match[1]
        shift_high = f'{high} = {value} << 16;'
        shift_low = f'{low} = {value} << 8;'
        def wrap(statement, depth):
            return 'do { ' * depth + statement + ' } while (0);' * depth
        staged = (f'u32 {high}, {low}, __repair_or_part; '
                  f'{wrap(shift_high, 3)} {wrap(shift_low, 3)} '
                  f'do {{ __repair_or_part = {low} | {constant}; '
                  f'do {{ {high} |= __repair_or_part; }} while (0); '
                  f'{hit["dest"]} = {high} | {value}; }} while (0);')
        return [(WEIGHTED_FAMILY, edit(source, [(hit.start(), hit.end(), staged)]))]
    return []


def _split(text):
    """The depth-zero `|` operands of `text`, or None when an operator other than a plain `|` is a top-level `|=`."""
    parts, depth, start = [], 0, 0
    for i, ch in enumerate(text):
        depth += ch in '(['
        depth -= ch in ')]'
        if ch == '|' and depth == 0:
            if text[i + 1:i + 2] in ('|', '=') or text[i - 1:i] == '|':
                return None
            parts.append(text[start:i])
            start = i + 1
    parts.append(text[start:])
    return parts


def _flatten(operand):
    """One operand's own or-chain when it is a parenthesised chain, else the operand."""
    inner = operand.strip()
    while inner.startswith('(') and _close(inner, 0) == len(inner) - 1:
        pieces = _split(inner[1:-1])
        if pieces is None or len(pieces) == 1:
            inner = inner[1:-1].strip()
            if not inner.startswith('('):
                break
            continue
        return [part for piece in pieces for part in _flatten(piece)]
    return [inner]


def _close(text, start):
    depth = 0
    for i in range(start, len(text)):
        depth += text[i] == '('
        depth -= text[i] == ')'
        if depth == 0:
            return i
    return -1


def _chains(clean, start, end):
    """(first, last) offsets of each maximal or-chain expression in the span: the text between its delimiters."""
    found = []
    depth_stack = []
    begin = start
    i = start
    while i < end:
        ch = clean[i]
        if ch in '([':
            depth_stack.append(begin)
            begin = i + 1
        elif ch in ')]':
            if depth_stack:
                span = clean[begin:i]
                if '|' in span.replace('||', ''):
                    found.append((begin, i))
                begin = depth_stack.pop()
        elif ch in ';{}=,' and not depth_stack:
            span = clean[begin:i]
            if '|' in span.replace('||', ''):
                found.append((begin, i))
            begin = i + 1
        i += 1
    return found


def variants(source, name, header=''):
    part = view(source, name)
    if not part or re.search(r'\b(?:asm|__asm__|goto)\b', part.body):
        return []
    clean = part.clean
    # The OR identity below duplicates a read. Only a unique unsigned local
    # or parameter is safe: a volatile, macro, field access, or shadow is not.
    unsigned = {}
    for decl in re.finditer(rf'\b(?P<type>u32|unsigned\s+int|unsigned)\s+(?P<name>{IDENT})\b', clean):
        variable = decl['name']
        unsigned[variable] = unsigned.get(variable, 0) + 1
    macros = set(re.findall(rf'^\s*#\s*define\s+({IDENT})\b', header + '\n' + source, re.M))
    volatile_u32 = re.search(r'\btypedef\b[^;]*\bvolatile\b[^;]*\bu32\s*;', header + '\n' + source)
    spans = _chains(clean, part.opening + 1, part.end - 1)
    # keep the outermost chains: a span inside another one belongs to the larger chain
    spans = [s for s in spans if len(_split(clean[s[0]:s[1]]) or []) > 1]
    spans = [s for s in spans if not any(o != s and o[0] <= s[0] and s[1] <= o[1] for o in spans)]
    result = weighted_pack(source, part, header)
    for first, last in sorted(spans):
        text = clean[first:last]
        if UNSAFE.search(text):
            continue
        pieces = _split(text)
        if not pieces:
            continue
        operands = [p for piece in pieces for p in _flatten(piece)]
        if not 3 <= len(operands) <= 4 or any(not o for o in operands):
            continue
        literals = [o for o in operands if LITERAL.match(o)]
        if len(literals) != 1:
            continue
        rest = [o for o in operands if o is not literals[0]]
        original = ' | '.join(o.strip() for o in operands)
        orders = [list(order) for order in itertools.permutations(rest)]
        count = 0
        for order in orders:
            chain = ' | '.join(o.strip() for o in [literals[0]] + order)
            if chain == original or chain == text.strip():
                continue
            source_text = source[first:last]
            lead = source_text[:len(source_text) - len(source_text.lstrip())]
            trail = source_text[len(source_text.rstrip()):]
            result.append((FAMILY, edit(source, [(first, last, lead + chain + trail)])))
            count += 1
            if count == PER_CHAIN:
                break
        # GCC can coalesce an OR result into a different input register when
        # the literal is hidden until combine: x | (~x & K) == x | K.
        # Preserve every other operand's order and offer one duplicated local
        # at a time. In particular, never duplicate a field or volatile read.
        # A hex literal of at most 32 bits (without a long suffix) has the
        # same unsigned-int width as the selected u32 on the target. A wider
        # literal could change the width at which ~chosen is evaluated.
        identity_literal = re.fullmatch(r'0[xX][0-9a-fA-F]{1,8}[uU]?', literals[0].strip())
        if identity_literal and not re.search(r'\bvolatile\b', part.body):
            insertion = len(result) - count + min(count, 2)
            for chosen in rest:
                chosen = chosen.strip()
                if not PLAIN.fullmatch(chosen) or unsigned.get(chosen) != 1 or chosen in macros:
                    continue
                if volatile_u32 and re.search(rf'\bu32\s+{re.escape(chosen)}\b', clean):
                    continue
                declarations = re.findall(rf'\b{IDENT}\s+(?:\*\s*)*{re.escape(chosen)}\b', clean)
                if len(declarations) != 1:
                    continue
                if re.search(rf'\bvolatile\s+(?:u32|unsigned(?:\s+int)?)\s+{re.escape(chosen)}\b', clean):
                    continue
                replaced = [f'((~{chosen} & {literals[0].strip()}) | {chosen})' if o.strip() == chosen
                            else o.strip() for o in rest]
                if sum(o.strip() == chosen for o in rest) != 1:
                    continue
                source_text = source[first:last]
                lead = source_text[:len(source_text) - len(source_text.lstrip())]
                trail = source_text[len(source_text.rstrip()):]
                result.insert(insertion, (FAMILY, edit(source, [(first, last, lead + ' | '.join(replaced) + trail)])))
                insertion += 1
        if len(result) >= LIMIT:
            break
    return result[:LIMIT]
