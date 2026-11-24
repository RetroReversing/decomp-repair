"""Which switch arm carries the shared join block, the arms' order, and the constants two joining arms assign."""
from decomprepair import registry
from decomprepair import switch_join_arms as arms
from decomprepair import targeted_switch_labels as labels

DRAFT = '''s32 f(void *a) {
    s32 t;
    s32 v;
    t = g();
    switch (t) {
    case 0x12:
        v = 0x13;
block_4:
        if (a == v) {
        case 0x6:
        case 0x8:
            return 1;
        }
        return 0;
    case 0x20:
        v = 0x21;
        goto block_4;
    default:
        return 0;
    }
}
'''
# the target's jump table: case 6.. entering: 6 -> block's return 1 (0xF4), 0x12 -> 0xE0, 0x20 -> 0xE8, the rest 0xFC
TABLE = (6, [0xF4, 0xFC, 0xF4] + [0xFC] * 9 + [0xE0] + [0xFC] * 13 + [0xE8])


def flat(text):
    return ' '.join(text.split())


def found(family, **context):
    return [flat(text) for label, text in arms.variants(DRAFT, 'f', **context) if label == family]


def test_the_block_moves_into_the_arm_that_jumped_to_it_in_every_order():
    out = found(arms.FAMILY_HOST)
    assert len(out) == 6
    target = ('case 0x12: v = 0x13; goto block_4; default: return 0; case 0x20: v = 0x21; block_4: '
              'if (a == v) { case 0x6: case 0x8: return 1; } return 0; }')
    assert any(target in text for text in out)
    assert all(text.count('block_4:') == 1 and text.count('goto block_4;') == 1 for text in out)


def test_the_jump_table_names_the_arm_and_the_order():
    out = found(arms.FAMILY_HOST, tables=[TABLE])
    assert len(out) == 3
    for text in out:
        assert text.index('case 0x12:') < text.index('case 0x20:') < text.index('block_4:')


def test_a_table_that_puts_the_block_under_the_arm_that_holds_it_offers_nothing():
    here = (6, [0xE0, 0xFC, 0xE0] + [0xFC] * 9 + [0xD0] + [0xFC] * 13 + [0xF8])
    assert found(arms.FAMILY_HOST, tables=[here]) == []


def test_the_constants_of_two_arms_that_reach_the_join_are_exchanged():
    out = found(arms.FAMILY_VALUES)
    assert len(out) == 1
    assert 'case 0x12: v = 0x21; block_4:' in out[0] and 'case 0x20: v = 0x13; goto block_4;' in out[0]


def test_a_goto_in_the_function_no_longer_stops_the_relabel_the_exchanged_constants_need():
    swapped = arms.variants(DRAFT, 'f')[-1][1]
    rows = [{'table': 1, 'case': 0x12, 'target': 0xE0, 'candidate': 0xE8},
            {'table': 1, 'case': 0x20, 'target': 0xE8, 'candidate': 0xE0}]
    text = flat(dict(labels.variants(swapped, 'f', rows))['linked_switch_labels'])
    assert 'case 0x20: v = 0x21;' in text and 'case 0x12: v = 0x13; goto block_4;' in text


def test_nothing_without_a_goto_to_the_label_or_with_a_declaration_in_an_arm():
    assert arms.variants(DRAFT.replace('goto block_4;', 'return 2;'), 'f') == []
    assert arms.variants(DRAFT.replace('v = 0x21;', 'int w = 0x21; v = w;'), 'f') == []
    assert arms.variants('void f(void) { g(); }', 'f') == []


def test_it_declares_itself_and_asks_for_the_tables():
    repair = registry.get('switch_join_arms')
    assert registry.problems(repair) == []
    assert 'tables' in repair.needs
    assert repair.arguments({'source': 'x', 'name': 'f'}) == {'source': 'x', 'name': 'f'}
