import os
import sys

BASE_DIR = r"d:\SMRFT\Projects\HMS\HMS_backend"
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "shanmugahospital_backend.settings")
import django
django.setup()

from django.test import RequestFactory
from django.contrib.auth.models import AnonymousUser
from hospital.Views.MasterAccountsReport.master_urls import urlpatterns

# Mock HasRoleAndDataPermission.has_permission to return True during testing
from pyauth.auth import HasRoleAndDataPermission
HasRoleAndDataPermission.has_permission = lambda self, request, view: True

def test_endpoints():
    rf = RequestFactory()
    params = {"from_date": "2026-11-16", "to_date": "2026-11-16"}
    
    print("\n" + "="*80)
    print("VERIFYING MASTER ACCOUNTS REPORT ENDPOINTS (2026-11-16)")
    print("="*80)

    success_count = 0
    fail_count = 0

    for p in urlpatterns:
        view_func = p.callback
        name = p.name
        pattern = str(p.pattern)
        
        req = rf.get(f"/_b_a_c_k_e_n_d/HMS/master-accounts/{pattern}", params)
        req.user = AnonymousUser()

        try:
            res = view_func(req)
            st = res.status_code
            if st == 200:
                data = res.data
                title = data.get('report_title') or 'N/A'
                print(f"[OK 200] {name:38} | Title: {title}")
                success_count += 1
            else:
                msg = res.data.get('message') if hasattr(res, 'data') and isinstance(res.data, dict) else str(res.content)[:60]
                print(f"[FAIL {st}] {name:38} | Msg: {msg}")
                fail_count += 1
        except Exception as e:
            import traceback
            print(f"[ERROR] {name:38} | Exception: {e}")
            traceback.print_exc()
            fail_count += 1

    print("="*80)
    print(f"RESULTS: {success_count} Passed, {fail_count} Failed out of {len(urlpatterns)} endpoints")
    print("="*80)

if __name__ == "__main__":
    test_endpoints()
