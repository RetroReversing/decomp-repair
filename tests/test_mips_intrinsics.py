"""The fixed CP0/FPU leaves are proposed only for a compiler the caller says carries their header."""
import pytest

from decomprepair import mips_compare, mips_count, mips_debug_break, mips_fcsr, mips_status, mips_status_return_spacing

COUNT = ('glabel sample\n/* 0 80001000 40024800 */ mfc0 $v0,$9\n'
         '/* 4 80001004 03E00008 */ jr $ra\n'
         '/* 8 80001008 00000000 */ nop\nendlabel sample\n')


def test_count_read_is_proposed_only_for_a_registered_compiler():
    assert mips_count.candidate(COUNT, 'f', True) == 'unsigned int f(void) { return __builtin_mips_read_count(); }\n'
    assert mips_count.candidate(COUNT, 'f', False) is None
    assert mips_count.candidate(COUNT.replace('40024800', '40026000'), 'f', True) is None
    assert mips_count.candidate(COUNT, 'f()', True) is None


@pytest.mark.parametrize('module', [mips_compare, mips_count, mips_fcsr, mips_status, mips_status_return_spacing])
def test_unregistered_compilers_get_nothing(module):
    assert module.candidate(COUNT, 'f', False) is None
    assert module.header() in mips_debug_break.header()


def test_export_header_carries_only_what_the_source_uses():
    assert mips_debug_break.header_for('int f(void){return 0;}') == ''
    assert mips_debug_break.header_for('x = __builtin_mips_read_count();') == mips_count.header()
