from django.db import models
from django.contrib.auth.models import User
import uuid

class Category(models.Model):
    name = models.CharField(max_length=30, unique=True)
    created_date = models.DateField(auto_now_add=True)

    def __str__(self):
        return self.name

class Company(models.Model):
    company_category = models.ForeignKey(Category, on_delete=models.CASCADE)
    admin = models.ForeignKey(User, on_delete=models.CASCADE)
    name = models.CharField(max_length=50, unique=True)
    allow_policies = models.BooleanField(default=True)
    description = models.TextField(max_length=2000)
    rating = models.DecimalField(
        default=3.0, max_digits=3, decimal_places=1, editable=False)  # Support ratings like 4.5
    logo = models.URLField(max_length=500, null=True, blank=True)
    latitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    longitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    availability = models.BooleanField(default=True)
    creation_date = models.DateField(auto_now_add=True)
    

    def __str__(self):
        return self.name

class InsurancePolicy(models.Model):
    company = models.ForeignKey(Company, on_delete=models.CASCADE)
    category = models.ForeignKey(Category, on_delete=models.CASCADE, related_name="policies", null=True)  # add this
    name = models.CharField(max_length=50)
    description = models.TextField()
    coverage_amount = models.DecimalField(max_digits=15, decimal_places=2)  # Max payout
    premium = models.DecimalField(max_digits=10, decimal_places=2)  # Premium plan monthly price
    regular = models.DecimalField(max_digits=10, decimal_places=2)  # Regular plan monthly price
    duration = models.CharField(max_length=100)
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return f"{self.name}"



class UserPolicies(models.Model):
    PLAN_CHOICES = [
        ('Premium', 'Premium'),
        ('Regular', 'Regular')
    ]


    user = models.ForeignKey(User, on_delete=models.CASCADE)
    policy = models.ForeignKey(InsurancePolicy, on_delete=models.CASCADE)
    plan_type = models.CharField(max_length=10, choices=PLAN_CHOICES)
    duration = models.PositiveIntegerField(help_text="duration in months")
    momo_number = models.CharField(max_length=20)  
    document = models.FileField(upload_to='documents/', null=True, blank=True)
    creation_date = models.DateTimeField(auto_now_add=True)
    status = models.CharField(max_length=20, choices=[('Active', 'Active'), ('On Pause', 'On Pause'), ('Complete', 'Complete')], default='Active')
    expiry_date = models.DateField(null=True, blank=True)  

    def __str__(self):
        return f"{self.user.username} - {self.policy.name}"




class Claim(models.Model):
    policy = models.ForeignKey(InsurancePolicy, on_delete=models.CASCADE)
    title = models.CharField(max_length=100)
    claimant = models.ForeignKey(User, on_delete=models.CASCADE, related_name='claims')
    claim_number = models.CharField(max_length=50, unique=True, blank=True)
    description = models.TextField()
    claim_amount = models.DecimalField(max_digits=15, decimal_places=2, null=True, blank=True)
    payout_amount = models.DecimalField(max_digits=15, decimal_places=2, null=True, blank=True)
    adjustment_note = models.TextField(blank=True, null=True)
    status = models.CharField(max_length=20, choices=[('Submitted', 'Submitted'),('Pending', 'Pending'), ('Approved', 'Approved'), ('Denied', 'Denied')], default='Pending')
    claim_date = models.DateTimeField(auto_now_add=True)
    approval_date = models.DateTimeField(null=True, blank=True)

    def save(self, *args, **kwargs):
        if not self.claim_number:
             self.claim_number = f"CLM-{uuid.uuid4().hex[:8].upper()}"  # Short UUID for auto generated claim number 
        super().save(*args, **kwargs)

    def __str__(self):
        return f"Claim {self.claim_number} - {self.status}"



class Transaction(models.Model):
    TRANSACTION_TYPE_CHOICES = [
        ('Policy Payment', 'Policy Payment'),
        ('Claim Payout', 'Claim Payout'),
    ]

    user = models.ForeignKey(User, on_delete=models.CASCADE)
    policy_subscription = models.ForeignKey(UserPolicies, on_delete=models.CASCADE)
    transaction_type = models.CharField(max_length=20, choices=TRANSACTION_TYPE_CHOICES)
    amount = models.DecimalField(max_digits=15, decimal_places=2)
    momo_number = models.CharField(max_length=20)
    timestamp = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.user.username} - {self.transaction_type} - {self.amount}"




class Messages(models.Model):
    sender = models.ForeignKey(User, on_delete=models.CASCADE, related_name='sent_messages')
    receiver = models.ForeignKey(User, on_delete=models.CASCADE, related_name='received_messages')
    message = models.TextField(max_length=1000)
    read_status = models.BooleanField(default=False)
    timestamp = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Message from {self.sender.username} to {self.receiver.username} at {self.timestamp}"



class Payment(models.Model):
    claim = models.ForeignKey(Claim, on_delete=models.CASCADE)
    amount = models.DecimalField(max_digits=15, decimal_places=2)
    payment_date = models.DateField(auto_now_add=True)
    is_paid = models.BooleanField(default=False)

    def __str__(self):
        return f"Payment of {self.amount} for {self.claim.claim_number}"
