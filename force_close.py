from hospital.models import Cashcountershiftdetails
res = Cashcountershiftdetails.objects.filter(CashCounter="OLET003", ShiftStatus="active").update(ShiftStatus="inactive", is_active=False)
print(f"Force closed {res} shifts via Django shell")
