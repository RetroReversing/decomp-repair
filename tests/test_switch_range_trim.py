"""The aliases of `default:` outside the target's range check are removed."""
import re

from decomprepair import registry
from decomprepair.switch_range_trim import FAMILIES, FAMILY, UNPIN, variants

CODE = '''typedef int s32;
extern void f(s32 a);

void g(s32 k)
{
    switch (k) {
        case 2:
        case 3:
        case 44:
        case 0:
        case 1:
        case 45:
        case 46:
        default:
            f(1);
            break;
        case 6:
            f(6);
            break;
        case 30:
            f(30);
            break;
    }
}
'''

ASM = '''    addiu      $v1, $v0, -0x2
    sltiu      $v0, $v1, 0x2b
    beqz       $v0, .L1
'''


def squash(text):
    return re.sub(r'\s+', ' ', text)


def test_the_aliases_beyond_the_targets_range_go_and_the_ends_stay():
    [(family, text)] = variants(CODE, 'g', ASM)
    text = squash(text)
    assert family == FAMILY
    assert 'case 2: case 3: case 44: default:' in text
    assert 'case 0:' not in text and 'case 1:' not in text and 'case 45:' not in text and 'case 46:' not in text


def test_a_range_that_misses_an_arm_of_the_switch_is_another_switchs():
    assert variants(CODE, 'g', ASM.replace('-0x2', '-0x8')) == []
    assert variants(CODE, 'g', ASM.replace('0x2b', '0x5')) == []


def test_nothing_is_proposed_without_the_target_or_with_every_alias_inside_it():
    assert variants(CODE, 'g', '') == []
    assert variants(CODE, 'g', ASM.replace('-0x2', '-0x0').replace('0x2b', '0x40')) == []


def test_the_trim_is_offered_again_with_the_volatile_casts_written_plain():
    code = CODE.replace('f(30);', '*((volatile s32 *) (void *) 0) |= 0x20600;')
    children = {family: squash(text) for family, text in variants(code, 'g', ASM)}
    assert set(children) == set(FAMILIES)
    assert 'volatile' in children[FAMILY] and 'volatile' not in children[UNPIN]
    assert 'case 0:' not in children[UNPIN] and 'case 2: case 3: case 44: default:' in children[UNPIN]
    assert [family for family, _ in variants(CODE, 'g', ASM)] == [FAMILY]


def test_the_family_declares_itself_to_the_registry():
    [repair] = [item for item in registry.declared() if set(FAMILIES) <= set(item.families)]
    assert registry.problems(repair) == []
