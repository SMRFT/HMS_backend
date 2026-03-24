import os
import django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'shanmugahospital_backend.settings')
django.setup()
from djongo import models
class TestModel(models.Model):
    data = models.JSONField(default=list)
    class Meta:
        managed = False
print(models.JSONField)
