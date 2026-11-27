"""A `goto` to the tail of another switch arm, written as the statements it would run.

    case 2: ... else { goto block_75; } ... break;          default: ... else { block_75: done = 0; } break;

m2c joins the arms of a state machine that finish the same way with `goto`: the labelled statements sit in one arm's last
block and the other arms jump into it. Where nothing follows the label's block but the arm's `break;` (the `else` arms
the label skips are not run either), and nothing follows the `goto`'s block but the arm's `break;`, the jump is the same
program as the statements written where it is: the game's arms each finished by themselves, and the compiler's
cross-jumping merged the identical tails again. The jump table's arms differ otherwise: the label's arm owns
a pseudo-register web that the `goto` makes live across the whole switch (the continue flag of a 417-instruction input
handler had 14 references and ranked below its three masks; the target's order was the other one).

Offered once for the function (every such `goto` in one child, and the labels it leaves unused removed): a label whose
statements run to the end of their block, with the block followed only by skipped `else` arms and `break;`, and `goto`s
whose block is followed only by closing braces, skipped `else` arms and `break;`. Labels with labels or `goto`s of their
own inside are left alone. A third child copies a label's run that falls into an arm that only leaves (`L: D = v;
default: return;`) over each `goto L;` that ends an arm, followed by that `return;`/`break;` (`_falls_into_exit`).
A second child does the same for a label at its arm's own level (`case A: v = x; L: f(v);
r = 0; break;`): its run up to the arm's `break;` is copied over each `goto L;` that ends another arm (`_arm_level`).
A candidate rewrite; the exact judge decides.
"""
import re

from .integer_repair_support import IDENT, edit, view
from .pattern_repairs import close

FAMILY = 'goto_arm_tail_inline'
FAMILIES = (FAMILY,)
_LABEL = re.compile(rf'(?m)(?:^|(?<=[;{{}}]))\s*(?P<l>{IDENT})\s*:(?!:)')
_GOTO = re.compile(rf'\bgoto\s+(?P<l>{IDENT})\s*;')


def _python_end_of_block(clean, at, limit):
    depth = 0
    for pos in range(at, limit):
        if clean[pos] == '{':
            depth += 1
        elif clean[pos] == '}':
            if depth == 0:
                return pos
            depth -= 1
    return None


_end_of_block = _python_end_of_block
try:  # the typed kernel (native_build.py), when it is built: same answers, the loop in C
    from . import _scan
except ImportError:
    _scan = None
if _scan is not None:
    def _end_of_block(clean, at, limit):
        found = _scan.enclosing_end(clean, at, limit, None)
        return _python_end_of_block(clean, at, limit) if found is NotImplemented else found


def _only_exit_follows(clean, at, limit):
    """Whether, from `at`, nothing but closing braces, `else` arms that are skipped and `break;` follow."""
    while at < limit:
        rest = re.compile(r'\s*').match(clean, at).end()
        if clean.startswith('}', rest):
            at = rest + 1
        elif re.compile(r'else\b').match(clean, rest):
            after = rest + 4
            pre = re.compile(r'\s*if\s*\(').match(clean, after)
            if pre:
                after = close(clean, pre.end() - 1)
            block = re.compile(r'\s*\{').match(clean, after)
            if not block or not after:
                return False
            at = close(clean, block.end() - 1, '{', '}')
            if not at:
                return False
        else:
            return bool(re.compile(r'break\s*;').match(clean, rest))
    return False


def variants(source, name):
    part = view(source, name)
    if not part:
        return []
    clean = part.clean
    edits = []
    gone = {}
    inlined = {}
    for label in _LABEL.finditer(clean, part.opening + 1, part.end):
        text = label['l']
        if text in ('default', 'case') or not re.search(rf'\bgoto\s+{text}\s*;', clean[part.opening:part.end]):
            continue
        end = _end_of_block(clean, label.end(), part.end)
        if end is None:
            continue
        statements = source[label.end():end].strip()
        if not statements or re.search(rf'\bgoto\b|^\s*{IDENT}\s*:(?!:)', clean[label.end():end], re.M) or '{' in statements:
            continue
        if not _only_exit_follows(clean, end + 1, part.end):
            continue
        inlined[text] = (label, statements)
    for hit in _GOTO.finditer(clean, part.opening + 1, part.end):
        if hit['l'] not in inlined:
            continue
        label, statements = inlined[hit['l']]
        if hit.start() > label.start() and hit.start() < _end_of_block(clean, label.end(), part.end):
            continue
        end = _end_of_block(clean, hit.end(), part.end)
        if end is None or not _only_exit_follows(clean, end, part.end):
            continue
        edits.append((hit.start(), hit.end(), statements))
        gone[hit['l']] = gone.get(hit['l'], 0) + 1
    results = []
    if edits:
        for text, count in gone.items():
            if len(re.findall(rf'\bgoto\s+{text}\s*;', clean[part.opening:part.end])) == count:
                label = inlined[text][0]
                edits.append((label.start(), label.end(), ' '))
        results.append((FAMILY, edit(source, edits)))
    arm_level = _arm_level(source, clean, part)
    if arm_level and all(arm_level != text for _, text in results):
        results.append((FAMILY, arm_level))
    exit_label = _falls_into_exit(source, clean, part)
    if exit_label and all(exit_label != text for _, text in results):
        results.append((FAMILY, exit_label))
    return results


def _switch_opener(clean, part, at):
    """The innermost open brace before `at` when it is a switch's, else None."""
    depth = 0
    for pos in range(at - 1, part.opening, -1):
        if clean[pos] == '}':
            depth += 1
        elif clean[pos] == '{':
            if depth == 0:
                return pos if re.search(r'\bswitch\s*\([^{}]*\)\s*$', clean[part.opening:pos]) else None
            depth -= 1
    return None


def _falls_into_exit(source, clean, part):
    """Labels at an arm's own level whose run falls into an arm that only leaves, copied over each `goto`.

        case 0x32: f(); v = 0x33;
        block_35: D = v;
        default: return;
        case 0x28: g(); v = 0x29; goto block_35;
     -> case 0x28: g(); v = 0x29; D = v; return;

    The shared store is the compiler's cross-jumping, and it keeps the copy of the last arm: with the label in an
    early arm the join sat there and every other arm branched backwards to it (a KMC GCC 2.7.2 N64 state-machine
    dispatcher of 158 instructions: with the empty case of its jump table's last entry, 1480 -> 0)."""
    edits = []
    for label in _LABEL.finditer(clean, part.opening + 1, part.end):
        name = label['l']
        if name in ('default', 'case'):
            continue
        opener = _switch_opener(clean, part, label.start())
        if opener is None:
            continue
        arm = re.compile(r'\b(?:case\b|default\s*:)').search(clean, label.end(), part.end)
        if not arm:
            continue
        run = clean[label.end():arm.start()]
        if not run.strip() or not run.rstrip().endswith(';') or re.search(
                rf'[{{}}]|\b(?:goto|break|return|continue)\b|^\s*{IDENT}\s*:(?!:)', run, re.M):
            continue
        leave = re.compile(r'(?:\s*(?:case\b[^:;{}]+|default\s*):)+\s*(?P<x>(?:return\b[^;{}]*|break\s*);)').match(
            clean, arm.start())
        if not leave:
            continue
        statements = source[label.end():arm.start()].strip()
        statements += ' ' + source[leave.start('x'):leave.end('x')]
        gotos = list(re.finditer(rf'\bgoto\s+{re.escape(name)}\s*;', clean[part.opening:part.end]))
        replaced = 0
        for goto in gotos:
            start, end = part.opening + goto.start(), part.opening + goto.end()
            # a `break` copied there must leave the same switch: the `goto` ends an arm of the label's own switch
            if _switch_opener(clean, part, start) == opener and re.compile(r'\s*(?:case\b|default\b|\})').match(clean, end):
                edits.append((start, end, statements))
                replaced += 1
        if replaced and replaced == len(gotos):
            edits.append((label.start(), label.end(), ' '))
    return edit(source, edits) if edits else None


def _arm_level(source, clean, part):
    """Labels at an arm's own level whose run ends in the arm's `break;`, copied over each `goto` that ends its arm.

        case 0x36: v = g; block_144: link(voice, v); r = 0; break;
        case 0x37: ...; v = w & 0xFF; goto block_144;
     -> case 0x37: ...; v = w & 0xFF; link(voice, v); r = 0; break;

    The arm that jumps had its own call; the compiler's cross-jumping merged the two calls into the second arm's copy
    (KMC GCC 2.7.2: on a 1315-instruction sound-sequence interpreter the copy took 10360 -> 9595, where the jump kept
    the first arm's copy and the target the second's)."""
    edits = []
    for label in _LABEL.finditer(clean, part.opening + 1, part.end):
        name = label['l']
        if name in ('default', 'case'):
            continue
        run = re.compile(r'[^{}]*?\bbreak\s*;').match(clean, label.end())
        if not run or re.search(rf'\bgoto\b|\b(?:case|default|return|continue)\b|^\s*{IDENT}\s*:(?!:)',
                                clean[label.end():run.end()], re.M):
            continue
        before = clean[part.opening:label.start()]
        if before.count('{') - before.count('}') < 1:
            continue
        # the label must sit at its arm's level: the innermost open brace before it is the switch's
        depth = 0
        opener = None
        for pos in range(label.start() - 1, part.opening, -1):
            if clean[pos] == '}':
                depth += 1
            elif clean[pos] == '{':
                if depth == 0:
                    opener = pos
                    break
                depth -= 1
        if opener is None or not re.search(r'\bswitch\s*\([^{}]*\)\s*$', clean[part.opening:opener]):
            continue
        statements = source[label.end():run.end()].strip()
        gotos = list(re.finditer(rf'\bgoto\s+{re.escape(name)}\s*;', clean[part.opening:part.end]))
        replaced = 0
        for goto in gotos:
            at = part.opening + goto.end()
            if re.compile(r'\s*(?:case\b|default\b|\})').match(clean, at):
                edits.append((part.opening + goto.start(), at, statements))
                replaced += 1
        if replaced and replaced == len(gotos):
            edits.append((label.start(), label.end(), ' '))
    return edit(source, edits) if edits else None


REPAIR = {'families': FAMILIES, 'variants': variants, 'needs': ('source', 'name')}
