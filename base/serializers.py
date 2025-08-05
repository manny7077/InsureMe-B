from rest_framework import serializers
from .models import (
  UserPolicies, Category, Company, InsurancePolicy, Claim,  Messages, Payment, User, Transaction
)
from django.contrib.auth.models import Group



class UserLoginSerializer(serializers.Serializer):
    username = serializers.CharField()
    password = serializers.CharField(write_only=True)

class UserSerializer(serializers.ModelSerializer):
    groups = serializers.SlugRelatedField(
        many=True,
        slug_field='name',
        queryset=Group.objects.all()
    )

    class Meta:
        model = User
        fields = ('id', 'username', 'email', 'first_name', 'last_name', 'groups')

class CategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = Category
        fields = '__all__'

class CompanySerializer(serializers.ModelSerializer):
    class Meta:
        model = Company
        fields = '__all__'

class InsurancePolicySerializer(serializers.ModelSerializer):
    company = serializers.StringRelatedField()
    category = serializers.StringRelatedField()

    class Meta:
        model = InsurancePolicy
        fields = '__all__'


class UserPoliciesSerializer(serializers.ModelSerializer):
    policy_name = serializers.CharField(source='policy.name', read_only=True)

    class Meta:
        model = UserPolicies
        fields = [
            'id', 'policy', 'policy_name', 'plan_type', 'duration',
            'momo_number', 'status', 'creation_date'
        ]   


class ClaimSerializer(serializers.ModelSerializer):
    claimant = serializers.CharField(source='claimant.get_full_name', read_only=True)
    policy = serializers.CharField(source='policy.name', read_only=True)
    amount_requested = serializers.DecimalField(source='claim_amount', max_digits=15, decimal_places=2, read_only=True)
    
    class Meta:
        model = Claim
        fields = [
            'id', 
            'claim_number', 
            'title', 
            'claimant', 
            'policy', 
            'description',
            'claim_amount',
            'amount_requested',  
            'payout_amount',
            'adjustment_note',
            'status',
            'claim_date',  
            'approval_date',
          
        ]




class MessagesSerializer(serializers.ModelSerializer):
    class Meta:
        model = Messages
        fields = '__all__'

class PaymentSerializer(serializers.ModelSerializer):
    class Meta:
        model = Payment
        fields = '__all__'




class TransactionSerializer(serializers.ModelSerializer):
    class Meta:
        model = Transaction
        fields = '__all__'
        read_only_fields = ['user', 'timestamp']
