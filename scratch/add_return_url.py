import re

file_path = "/Users/parthibanmurugan/Desktop/Live Projects/HMS/HMS_backend/hospital/urls.py"

with open(file_path, "r") as f:
    content = f.read()

new_url = '    path("return_medicine_ward_request/", NursingStation.return_medicine_ward_request, name="return_medicine_ward_request"),'

if "return_medicine_ward_request" not in content:
    # Insert it near save_medicine_ward_request
    content = content.replace(
        'path("save_medicine_ward_request/", NursingStation.save_medicine_ward_request, name="save_medicine_ward_request"),',
        'path("save_medicine_ward_request/", NursingStation.save_medicine_ward_request, name="save_medicine_ward_request"),\n' + new_url
    )
    with open(file_path, "w") as f:
        f.write(content)
    print("Added return_medicine_ward_request to urls.py")
else:
    print("Already exists in urls.py")
