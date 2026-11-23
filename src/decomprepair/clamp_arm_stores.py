"""A clamp m2c merged into one store, written as the two stores the game branched to.

m2c writes a store that clamps a value as one store of a shared temporary, the temporary set to one bound before the
test and to the other inside it:

    var = -0xDC;
    if ((s16) x < -0xDC || (var = 0xDC, ((s16) x < 0xDD) == 0)) {
        dst = var;
    }

or, when the test is split over two `if`s and the store is a label both arms jump to:

    var = -0xDCU;
    if ((s16) dst >= -0xDC) { if ((s16) dst >= 0xDD) { var = 0xDC; goto L; } } else { L: dst = var; }

The shared temporary is live across the compare, so GCC gives it a register of its own (`$a0` where the game had
`$v0` for both the compare result and the bound: the game's `li $v0,-0xDC` sits in the branch's delay slot, after the
branch has read `$v0`). The game's source assigned each bound where it applies:

    if ((s16) x < -0xDC) { dst = -0xDC; } else if (!((s16) x < 0xDD)) { dst = 0xDC; }

which has no shared temporary (`li` in each delay slot, the one `sh` shared by cross-jumping).

The float form m2c writes for the same branches (`c.lt.s`, `bc1tl` with the store of the bound in its slot) tests the
upper bound directly:

    var_fv1_2 = -0.5625f;
    if ((temp_fv0_5 < (-0.5625f)) || ((var_fv1_2 = 0.5625f, temp_fv0_5 > 0.5625f))) {
        o->x = var_fv1_2;
    }

and the game's `if (v < -0.5625f) { o->x = -0.5625f; } else if (v > 0.5625f) { o->x = 0.5625f; }` loads the value
before the bound's `lui`/`mtc1` (the shared temporary took the bound's register first). Six such clamps in a
1300-instruction KMC GCC 2.7.2 controller routine, all rewritten together: 4470 -> 2380. A GCC 2.7.2 KMC N64
function with two such clamps (`-G0 -mips3 -mgp32 -mfp32 -O2 -fno-strength-reduce`) went 1009 -> 979 with both
rewritten (a 731-instruction function: the clamps' six register rows were exact). Only a candidate: the judge's byte
comparison decides, and the rewrite is offered for the two shapes above, nothing else that looks like a clamp.
"""
import re

from .integer_repair_support import edit, view

FAMILY = 'clamp_arm_stores'
FAMILIES = (FAMILY,)
IDENT = r'[A-Za-z_]\w*'
NUMBER = r'(?:0[xX][0-9a-fA-F]+|[0-9]+)'
LIMIT = 8

# var = -K; if (LOW || (var = K, (HIGH) == 0)) { dst = var; }
COMMA = re.compile(
    rf'(?P<indent>[ \t]*)(?P<var>{IDENT})\s*=\s*(?P<low>-\s*{NUMBER}[uU]?)\s*;[ \t]*\n'
    rf'[ \t]*if\s*\(\s*\(?(?P<lowtest>[^;{{}}]*?)\)?\s*\|\|\s*\(\s*(?P=var)\s*=\s*(?P<high>{NUMBER}[uU]?)\s*,\s*'
    rf'\(\s*\(\s*(?P<hightest>[^;{{}}]*?)\s*\)\s*==\s*0\s*\)\s*\)\s*\)\s*{{[ \t]*\n'
    rf'[ \t]*(?P<dst>[^;{{}}=]+?)\s*=\s*(?P=var)\s*;[ \t]*\n'
    rf'[ \t]*}}[ \t]*\n')

# var = -K; if (X >= -K) { if (X >= K+1) { var = K; goto L; } } else { [{ junk }] L: dst = var; }
GOTO = re.compile(
    rf'(?P<indent>[ \t]*)(?P<var>{IDENT})\s*=\s*(?P<low>-\s*{NUMBER}[uU]?)\s*;[ \t]*\n'
    rf'[ \t]*if\s*\(\s*(?P<x>[^;{{}}]*?)\s*>=\s*-\s*(?P<k>{NUMBER})[uU]?\s*\)\s*{{[ \t]*\n'
    rf'[ \t]*if\s*\(\s*(?P=x)\s*>=\s*(?P<k1>{NUMBER})\s*\)\s*{{[ \t]*\n'
    rf'[ \t]*(?P=var)\s*=\s*(?P<high>{NUMBER}[uU]?)\s*;[ \t]*\n'
    rf'[ \t]*goto\s+(?P<label>{IDENT})\s*;[ \t]*\n'
    rf'[ \t]*}}[ \t]*\n'
    rf'[ \t]*}}\s*else\s*{{[ \t]*\n'
    rf'(?:[ \t]*{{[^;{{}}]*;[ \t]*}}[ \t]*\n)?'
    rf'(?P<labelline>[ \t]*)(?P=label):[ \t]*\n?'
    rf'[ \t]*(?P<dst>[^;{{}}=]+?)\s*=\s*(?P=var)\s*;[ \t]*\n'
    rf'[ \t]*}}[ \t]*\n')


FLOAT = r'\(?\s*-?\s*(?:\d+\.\d*|\.\d+|\d+)(?:[eE][-+]?\d+)?[fF]?\s*\)?'

# var = LOW; if ((LOWTEST) || ((var = HIGH, HIGHTEST))) { dst = var; }   (float bounds, the upper test written plainly)
FLOAT_COMMA = re.compile(
    rf'(?P<indent>[ \t]*)(?P<var>{IDENT})\s*=\s*(?P<low>{FLOAT})\s*;[ \t]*\n'
    rf'[ \t]*if\s*\(\s*\((?P<lowtest>[^;{{}}|]*?)\)\s*\|\|\s*\(\s*\(\s*(?P=var)\s*=\s*(?P<high>{FLOAT})\s*,\s*'
    rf'(?P<hightest>[^;{{}}|,]*?)\s*\)\s*\)\s*\)\s*{{[ \t]*\n'
    rf'[ \t]*(?P<dst>[^;{{}}=]+?)\s*=\s*(?P=var)\s*;[ \t]*\n'
    rf'[ \t]*}}[ \t]*\n')


def _bare(number):
    return re.sub(r'\s+', '', number).strip('()') if re.fullmatch(r'\(\s*-?[^()]*\)', number.strip()) else number.strip()


def _number(text):
    return int(re.sub(r'[uU]$', '', text.replace(' ', '')), 0)


def variants(source, name):
    part = view(source, name)
    if not part:
        return []
    clean = part.clean
    edits, seen = [], set()
    for hit in COMMA.finditer(clean, part.opening, part.end):
        low, high = hit['low'].replace(' ', ''), hit['high']
        indent = hit['indent']
        lowtest, hightest = hit['lowtest'].strip(), hit['hightest'].strip()
        if not lowtest or not hightest or hit['var'] in lowtest + hightest or low[0] != '-':
            continue
        text = (f'{indent}if ({lowtest}) {{\n{indent}    {hit["dst"].strip()} = {low};\n{indent}}} '
                f'else if (!({hightest})) {{\n{indent}    {hit["dst"].strip()} = {high};\n{indent}}}\n')
        edits.append((hit.start(), hit.end(), text))
        seen.add(hit.start())
    for hit in FLOAT_COMMA.finditer(clean, part.opening, part.end):
        if hit.start() in seen:
            continue
        lowtest, hightest = hit['lowtest'].strip(), hit['hightest'].strip()
        low, high = _bare(hit['low']), _bare(hit['high'])
        if not lowtest or not hightest or hit['var'] in lowtest + hightest or '.' not in low + high:
            continue
        indent, dst = hit['indent'], hit['dst'].strip()
        text = (f'{indent}if ({lowtest}) {{\n{indent}    {dst} = {low};\n{indent}}} '
                f'else if ({hightest}) {{\n{indent}    {dst} = {high};\n{indent}}}\n')
        edits.append((hit.start(), hit.end(), text))
        seen.add(hit.start())
    for hit in GOTO.finditer(clean, part.opening, part.end):
        if hit.start() in seen or _number(hit['k1']) != _number(hit['k']) + 1:
            continue
        indent, x = hit['indent'], hit['x'].strip()
        dst = hit['dst'].strip()
        low = '-' + re.sub(r'[uU]$', '', hit['low'].replace(' ', '').lstrip('-'))
        text = (f'{indent}if ({x} < {low}) {{\n{indent}    {dst} = {low};\n{indent}}} '
                f'else if ({x} >= {hit["k1"]}) {{\n{indent}    {dst} = {re.sub("[uU]$", "", hit["high"])};\n{indent}}}\n')
        edits.append((hit.start(), hit.end(), text))
    result = []
    # every rewrite alone, then all of them together: the clamps of one function usually need the same shape
    for start, end, text in edits[:LIMIT]:
        result.append((FAMILY, edit(source, [(start, end, text)])))
    if len(edits) > 1:
        result.append((FAMILY, edit(source, edits)))
    return result
