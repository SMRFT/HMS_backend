import os
import django
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "shanmugahospital_backend.settings")
django.setup()

from django.test import RequestFactory
from hospital.Views.room import room_shifting_view
import json

factory = RequestFactory()
request = factory.post('/_b_a_c_k_e_n_d/HMS/room-shifting/', data=json.dumps({"ip_number": "S026/500001", "newRoomNo": "102", "newBedNo": "1"}), content_type='application/json')
try:
    response = room_shifting_view(request)
    print("STATUS:", response.status_code)
    print("CONTENT:", response.content)
except Exception as e:
    import traceback
    traceback.print_exc()
