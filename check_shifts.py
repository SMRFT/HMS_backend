from hospital.models import Cashcountershiftdetails
all_nos = list(Cashcountershiftdetails.objects.values_list('shiftno', flat=True))
print(f"Existing Shift Nos: {all_nos}")
