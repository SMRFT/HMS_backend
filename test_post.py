import requests

payload = {
    "auth-user-id": "test_user",
    "uhid": "S026/0000006",
    "ipNumber": "S026/500005",
    "doctor": "Jothika",
    "patient_name": "Test Patient",
    "item": [{"test_id": 1, "name": "CBC"}],
    "billTypeNo": "LAB123"
}
try:
    res = requests.post('http://127.0.0.1:2609/_b_a_c_k_e_n_d/HMS/save_lab_ward_request/', json=payload)
    print(res.status_code)
    print(res.text)
except Exception as e:
    print(e)
