"""Two arms that end in the same float-zero store and jump to one label: the final jump pass merges their tails."""
from decomprepair import identical_tail_store_mode as p
from decomprepair import registry

SOURCE = '''typedef float f32;
typedef struct { char pad[0x12C]; f32 field_12C; } Marker;
extern Marker *gMarker;
extern void first(int);
extern void second(void);
extern void shared(int);

void step(int mode)
{
    int var_a0;
    switch (mode) {
    case 0:
        first(0);
        do
        {
            second();
        }
        while (0);
        var_a0 = 0x12;
        ((Marker *) gMarker)->field_12C = 0.0f;
        goto block_63;
    case 15:
        second();
        var_a0 = 0x12;
        ((Marker *) gMarker)->field_12C = 0.0f;
        goto block_63;
    case 3:
        var_a0 = 4;
        block_63:
        shared(var_a0);
        break;
    }
}
'''
STORE = '((Marker *) gMarker)->field_12C = 0.0f;'
VIEW = '*(s32 *)&((Marker *) gMarker)->field_12C = 0;'


def texts(source=SOURCE):
    return [text for _, text in p.variants(source, 'step')]


def test_one_arms_zero_is_stored_through_an_integer_view():
    assert any(t.count(VIEW) == 1 and t.count(STORE) == 1 for t in texts())


def test_the_arms_fence_is_removed_together_with_the_view():
    """349 instructions, 60 -> 0: the fence alone made it 650, the view alone left it at 60."""
    combined = [t for t in texts() if t.count(VIEW) == 1 and 'while (0)' not in t]
    assert len(combined) == 1 and 'first(0);' in combined[0] and 'second();' in combined[0]


def test_an_arm_without_a_fence_has_only_the_view_child():
    assert sum(1 for t in texts() if t.count(VIEW) == 1 and t.count(STORE) == 1 and 'while (0)' in t) == 2


def test_a_zero_store_with_no_twin_is_left_alone():
    assert texts(SOURCE.replace('        ((Marker *) gMarker)->field_12C = 0.0f;\n        goto block_63;\n    case 3', '        goto block_63;\n    case 3')) == []


def test_two_stores_of_different_places_are_not_twins():
    assert texts(SOURCE.replace('        second();\n        var_a0 = 0x12;\n        ((Marker *) gMarker)->field_12C = 0.0f;',
                                '        second();\n        var_a0 = 0x12;\n        ((Marker *) gMarker)->pad[0] = 0.0f;')) == []


def test_it_is_declared_for_every_caller():
    repair = registry.get('identical_tail_store_mode')
    assert repair and registry.problems(repair) == []
