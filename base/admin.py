from django.contrib import admin
from .models import (
 UserPolicies, Category, Company, InsurancePolicy, Claim,  Messages, Payment, Transaction
)

# Register your models here.

admin.site.register(UserPolicies)
admin.site.register(Category)
admin.site.register(Company)
admin.site.register(InsurancePolicy)
admin.site.register(Claim)
admin.site.register(Messages)
admin.site.register(Payment)
admin.site.register(Transaction)