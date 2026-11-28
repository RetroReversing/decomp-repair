from decomprepair.sdk_audio_driver_calls import variants

SOURCE = '''
void alSynSetVol(void *, void *, short, int);
void alSynSetPan(void *, void *, int);
void n_alSynSetVol(void *, short, int);
void n_alSynSetPan(void *, int);
void f(Player *p, Voice *v) {
    alSynSetVol(p->drvr, v, 12, 100);
    alSynSetPan(p->drvr, v, 64);
}
'''
ASM = 'jal n_alSynSetVol\njal n_alSynSetPan\n'


def test_adapts_only_the_driverless_calls_proven_by_target_assembly():
    children = [text for _, text in variants(SOURCE, 'f', '', ASM)]
    assert any('n_alSynSetVol(v, 12, 100)' in text and 'n_alSynSetPan(v, 64)' in text for text in children)
    vol_only = [text for _, text in variants(SOURCE, 'f', '', 'jal n_alSynSetVol')]
    assert vol_only and all('alSynSetPan(p->drvr' in text for text in vol_only)


def test_requires_prototype_and_does_not_remove_volatile_read():
    assert not variants(SOURCE.replace('void n_alSynSetVol(void *, short, int);', ''), 'f', '', 'jal n_alSynSetVol')
    assert not variants(SOURCE.replace('Player *p', 'volatile Player *p'), 'f', '', ASM)
    assert not variants(SOURCE, 'f', 'volatile void *drvr;', ASM)
    assert not variants(SOURCE, 'f', '', 'not_a_call n_alSynSetVol')


def test_rejects_more_donor_calls_than_target_calls():
    source = SOURCE.replace('    alSynSetPan', '    alSynSetVol(p->drvr, v, 13, 100);\n    alSynSetPan')
    assert not variants(source, 'f', '', 'jal n_alSynSetVol')


def test_rejects_incompatible_driverless_prototypes():
    wrong = SOURCE.replace('void n_alSynSetVol(void *, short, int);', 'void n_alSynSetVol(void *, float);')
    assert not variants(wrong, 'f', '', 'jal n_alSynSetVol')


def test_does_not_replace_macros_or_opaque_volatile_typedefs():
    assert not variants(SOURCE, 'f', '#define alSynSetVol(...) side_effect()', 'jal n_alSynSetVol')
    assert not variants(SOURCE, 'f', 'typedef void *volatile Driver;', ASM)
    assert not variants(SOURCE, 'f', 'class Player;', ASM)


def test_requires_the_standard_driver_prototype_and_unshadowed_player():
    assert not variants(SOURCE.replace('void alSynSetVol(void *, void *, short, int);', ''),
                        'f', '', 'jal n_alSynSetVol')
    assert not variants(SOURCE, 'f', '#define drvr side_effect()', ASM)
    assert not variants(SOURCE, 'f', '#define p get_player()', ASM)


def test_does_not_rewrite_member_calls_or_local_function_pointers():
    member = SOURCE.replace('alSynSetVol(p->drvr', 'object.alSynSetVol(p->drvr')
    assert not variants(member, 'f', '', 'jal n_alSynSetVol')
    local = SOURCE.replace('    alSynSetVol(', '    Callback alSynSetVol;\n    alSynSetVol(')
    assert not variants(local, 'f', '', 'jal n_alSynSetVol')
