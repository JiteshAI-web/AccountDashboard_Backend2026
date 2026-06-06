from django.db import models

# Create your models here.


class Bank(models.Model):
    bank_name = models.CharField(max_length=255)
    short_name = models.CharField(max_length=50, blank=True, null=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = 'banks'

    def __str__(self):
        return self.bank_name