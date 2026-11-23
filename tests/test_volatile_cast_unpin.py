"""A volatile cast written plain."""
import re

from decomprepair import registry
from decomprepair.volatile_cast_unpin import FAMILY, variants

CODE = '''typedef int s32;
extern s32 gMode;

void set(char *p, s32 big)
{
    if (big != 0) {
        *((volatile s32 *) (p + 0x5C)) |= 0x5E600;
    } else {
        *((volatile s32 *) (p + 0x5C)) |= 0x20600;
    }
    gMode = *((volatile unsigned char *) (p + 4));
}
'''


def squash(text):
    return re.sub(r'\s+', ' ', text)


def test_all_the_volatile_casts_are_written_plain_at_once_then_each_alone():
    children = [squash(text) for fam, text in variants(CODE, 'set')]
    assert len(children) == 4
    assert 'volatile' not in children[0]
    assert '*((s32 *) (p + 0x5C)) |= 0x5E600;' in children[0] and '*((unsigned char *) (p + 4))' in children[0]
    assert children[1].count('volatile') == 2 and '*((s32 *) (p + 0x5C)) |= 0x5E600;' in children[1]
    assert children[3].count('volatile') == 2 and '*((unsigned char *) (p + 4))' in children[3]


def test_one_cast_gives_one_proposal_and_a_declaration_is_left_alone():
    single = CODE.split('} else {')[0] + '}\n}\n'
    assert len(variants(single, 'set')) == 1
    declared = 'typedef int s32;\nextern volatile s32 gReg;\nvoid f(void)\n{\n    gReg = 1;\n}\n'
    assert variants(declared, 'f') == []


def test_a_function_without_the_qualifier_has_no_proposal():
    assert variants(CODE.replace('volatile ', ''), 'set') == []


def test_the_family_declares_itself_to_the_registry():
    [repair] = [item for item in registry.declared() if FAMILY in item.families]
    assert registry.problems(repair) == []
