from .Views import (
    shanmuga360_registration,
    get_360_medicinelist,
    get_360_doctorlist,
    get_360_testlist,
    shanmuga360_report,
    get_sample_collector,
    sample_collector,
)

__all__ = [
    'shanmuga360_registration',
    'get_360_medicinelist',
    'get_360_doctorlist',
    'get_360_testlist',
    'shanmuga360_report',
    'get_sample_collector',
    'sample_collector',
]

import sys
setattr(sys.modules[__name__], '360_report', shanmuga360_report)


