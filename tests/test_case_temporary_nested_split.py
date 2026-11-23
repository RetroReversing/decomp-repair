"""A switch's shared temporary split per case when the cases nest their first assignment or the switch has labels."""
from decomprepair import case_temporary_nested_split as p
from decomprepair import case_temporary_repairs, registry

SOURCE = '''typedef float f32;
extern f32 gA;
extern f32 gB;
extern void tick(void);
extern void other(int);

void step(int mode)
{
    f32 temp;
    int arg;
    switch (mode) {
    case 1:
        if (gA > 0.0f) {
            temp = gA - 1.0f;
            if (temp < 0.0f) {
                gA = 0.0f;
                tick();
                arg = 4;
                goto done;
            }
        }
        arg = 8;
        done:
        other(arg);
        break;
    case 2:
        do {
            if (((temp = gB) <= 0.0f) || (temp >= 1.0f)) {
                gB = temp;
            }
        } while (0);
        break;
    }
}
'''


def texts(source=SOURCE):
    return [text for _, text in p.variants(source, 'step')]


def test_the_old_family_declines_this_switch():
    """A label inside the switch and an assignment nested in a block: `case_temporary_split` gives nothing."""
    assert case_temporary_repairs.variants(SOURCE, 'step') == []


def test_each_case_gets_its_own_local():
    both = texts()
    assert any('f32 temp_2;' in t and 'if (((temp_2 = gB) <= 0.0f) || (temp_2 >= 1.0f))' in t for t in both)
    assert any('f32 temp_1;' in t and 'temp_1 = gA - 1.0f;' in t and 'temp_1 < 0.0f' in t for t in both)


def test_the_cases_that_stay_keep_the_original_name():
    first = [t for t in texts() if 'temp_2' in t and 'temp_1' not in t][0]
    assert 'temp = gA - 1.0f;' in first and 'if (temp < 0.0f)' in first


def test_a_read_in_the_middle_of_a_case_after_a_label_is_left_alone():
    """A `goto` could enter after the label and read the other case's value."""
    source = SOURCE.replace('        arg = 8;\n        done:\n        other(arg);', '        arg = 8;\n        done:\n        other((int) temp);')
    assert texts(source) == []


def test_a_first_mention_that_is_a_read_is_left_alone():
    source = SOURCE.replace('        do {\n            if (((temp = gB) <= 0.0f)', '        do {\n            if (((gB = temp) <= 0.0f)')
    assert texts(source) == []


def test_a_use_outside_the_switch_is_left_alone():
    assert texts(SOURCE.replace('    switch (mode) {', '    temp = 0.0f;\n    switch (mode) {')) == []


def test_an_address_taken_local_is_left_alone():
    assert texts(SOURCE.replace('        arg = 8;', '        other((int) &temp);\n        arg = 8;')) == []


def test_it_is_declared_for_every_caller():
    repair = registry.get('case_temporary_nested_split')
    assert repair and registry.problems(repair) == []
