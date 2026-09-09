from .Views import (
    shanmuga360_registration,
    get_360_medicinelist,
    get_360_doctorlist,
    get_360_testlist,
    shanmuga360_report,
)

__all__ = [
    'shanmuga360_registration',
    'get_360_medicinelist',
    'get_360_doctorlist',
    'get_360_testlist',
    'shanmuga360_report',
]

import sys
setattr(sys.modules[__name__], '360_report', shanmuga360_report)


