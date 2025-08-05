from django.shortcuts import render
from rest_framework import viewsets
from rest_framework.views import APIView
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from rest_framework import status
from django.db.models import Sum
from django.shortcuts import get_object_or_404
from rest_framework.exceptions import ValidationError
from django.utils.crypto import get_random_string
from django.utils import timezone
from django.contrib.auth import authenticate, login
from django.views.decorators.csrf import csrf_exempt
from .ai_logic import get_chatbot_response
from .models import (
 UserPolicies, Category, Company, InsurancePolicy, Claim,  Messages, Payment, User, Transaction
)
from .serializers import (
 UserPoliciesSerializer, CategorySerializer, CompanySerializer, InsurancePolicySerializer, ClaimSerializer,  UserLoginSerializer, UserSerializer
)
from rest_framework.authtoken.models import Token
from rest_framework.permissions import IsAuthenticated
from django.contrib.auth.models import Group


# Create your views here.


@api_view(["POST"])
def userLogin(request):
    serializer = UserLoginSerializer(data=request.data)
    
    if serializer.is_valid():
        username = serializer.validated_data["username"]
        password = serializer.validated_data["password"]

        user = authenticate(request, username=username, password=password)

        if user is not None:
            login(request, user)
            token, created = Token.objects.get_or_create(user=user)
            
            # Serialize user details, including groups
            user_data = UserSerializer(user).data
            
            return Response({
                "token": token.key,
                "user": user_data
            }, status=status.HTTP_200_OK)

        return Response(
            {"error": "Invalid credentials"}, status=status.HTTP_401_UNAUTHORIZED
        )

    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)



@api_view(["POST"])
@permission_classes([IsAuthenticated])
def logoutView(request):
    request.user.auth_token.delete()
    return Response({"message": "Logged out successfully"})



@api_view(["POST"])
@permission_classes([IsAuthenticated])
def join_policy(request):
    data = request.data

    policy_id = data.get('policy_id')
    plan_type = data.get('plan_type')
    duration = data.get('duration')
    momo_number = data.get('momo_number')

    if not all([policy_id, plan_type, duration, momo_number]):
        return Response({'error': 'Missing required fields.'}, status=status.HTTP_400_BAD_REQUEST)

    policy = get_object_or_404(InsurancePolicy, id=policy_id)

    if plan_type == 'Premium':
        monthly_price = policy.premium
    elif plan_type == 'Regular':
        monthly_price = policy.regular
    else:
        return Response({'error': 'Invalid plan type.'}, status=status.HTTP_400_BAD_REQUEST)

    try:
        duration_months = int(duration)
    except ValueError:
        return Response({'error': 'Duration must be a number.'}, status=status.HTTP_400_BAD_REQUEST)

    # Create policy subscription
    user_policy = UserPolicies.objects.create(
        user=request.user,
        policy=policy,
        plan_type=plan_type,
        duration=duration_months,
        momo_number=momo_number,
        status="active"
    )

    # Log the first monthly payment only
    Transaction.objects.create(
        user=request.user,
        policy_subscription=user_policy,
        transaction_type="Policy Payment",
        amount=monthly_price,  
        momo_number=momo_number
    )

    return Response({'message': 'Successfully joined policy and first month\'s payment recorded.'}, status=status.HTTP_201_CREATED)




@api_view(["GET"])
@permission_classes([IsAuthenticated])
def my_policies(request):
    subs = UserPolicies.objects.filter(user=request.user)
    data = [{
        "policy_id": sub.policy.id,
        "policy": sub.policy.name,
        "plan": sub.plan_type,
        "duration": sub.duration,
        "status": sub.status,
        "joined_on": sub.creation_date
    } for sub in subs]

    return Response(data)




@api_view(["POST"])
@permission_classes([IsAuthenticated])
def submit_claim(request):
    data = request.data
    policy_id = data.get('policy_id')
    title = data.get('title')
    claim_amount = data.get('claim_amount')
    date = data.get('date_of_occurrence')
    time = data.get('time_of_occurrence')
    location = data.get('location')
    incident_type = data.get('incident_type')
    
    if not all([policy_id, title, claim_amount, date, time, location, incident_type]):
        return Response({'error': 'Missing fields'}, status=status.HTTP_400_BAD_REQUEST)
    
    policy = get_object_or_404(InsurancePolicy, id=policy_id)
    
    if float(claim_amount) > float(policy.coverage_amount):
        return Response({'error': 'Claim amount exceeds coverage'}, status=status.HTTP_400_BAD_REQUEST)
    
    description = (
        f"Date: {date}\n"
        f"Time: {time}\n"
        f"Location: {location}\n"
        f"Incident: {incident_type}\n"
        f"Claim Amount: {claim_amount}"
    )
    
    claim = Claim.objects.create(
        policy=policy,
        title=title,
        claimant=request.user,
        claim_amount=claim_amount,
        description=description
    )
    
    # Return more complete claim information
    return Response({
        'message': 'Claim submitted successfully',
        'claim_number': claim.claim_number,
        'claim_id': claim.id,
        'claim_date': claim.claim_date.isoformat(),  
        'status': claim.status
    }, status=status.HTTP_201_CREATED)



@api_view(["GET"])
@permission_classes([IsAuthenticated])
def list_claims(request):
    claims = Claim.objects.filter(claimant=request.user)
    serializer = ClaimSerializer(claims, many=True)
    return Response(serializer.data)


@api_view(["GET"])
def list_policies(request):
    policies = InsurancePolicy.objects.filter(is_active=True)

    data = []
    for policy in policies:
        data.append({
            "id": policy.id,
            "name": policy.name,
            "description": policy.description,
            "coverage_amount": policy.coverage_amount,
            "premium_price": policy.premium,
            "regular_price": policy.regular,
            "company": policy.company.name,
            "category": policy.category.name
      
        })

    return Response(data, status=status.HTTP_200_OK)



@api_view(["GET"])
def get_policy_by_id(request, pk):
    try:
        policy = InsurancePolicy.objects.get(pk=pk)
    except InsurancePolicy.DoesNotExist:
        return Response({"detail": "Policy not found."}, status=status.HTTP_404_NOT_FOUND)

    serializer = InsurancePolicySerializer(policy)
    return Response(serializer.data, status=status.HTTP_200_OK)



@api_view(["GET"])
@permission_classes([IsAuthenticated])
def recent_transactions(request):
    transactions = Transaction.objects.filter(user=request.user).order_by('-timestamp')
    policy_payment_count = transactions.filter(transaction_type="Policy Payment").count()
    data = [{
        "amount": tx.amount,
        "type": tx.transaction_type,
        "momo_number": tx.momo_number,
        "timestamp": tx.timestamp,
        "policy_name": tx.policy_subscription.policy.name,
        "policy_payment_count": policy_payment_count
    } for tx in transactions]

    return Response(data)


def is_insurer(user):
    return user.groups.filter(name='Insurer').exists()

@api_view(["GET"])
@permission_classes([IsAuthenticated])
def all_claims(request):
    # For insurers to see all claims
    if not request.user.groups.filter(name='Insurer').exists():
        return Response({'error': 'Permission denied'}, status=status.HTTP_403_FORBIDDEN)
    
    claims = Claim.objects.all().order_by('-claim_date')  # Order by newest first
    serializer = ClaimSerializer(claims, many=True)
    return Response(serializer.data)



@api_view(["POST"])
@permission_classes([IsAuthenticated])
def process_claim(request, claim_id):
    user = request.user

    if not is_insurer(user):
        return Response({'error': 'Only insurers can process claims'}, status=status.HTTP_403_FORBIDDEN)

    claim = get_object_or_404(Claim, id=claim_id)
    status_update = request.data.get('status')  
    payout_amount = request.data.get('payout_amount')
    adjustment_note = request.data.get('adjustment_note')

    if status_update not in ['Approved', 'Denied']:
        return Response({'error': 'Invalid status value'}, status=status.HTTP_400_BAD_REQUEST)

    if status_update == 'Approved':
        if payout_amount is None:
            return Response({'error': 'Payout amount is required for approval'}, status=status.HTTP_400_BAD_REQUEST)
        
        try:
            payout_amount = float(payout_amount)
            if payout_amount <= 0:
                raise ValueError
        except ValueError:
            return Response({'error': 'Invalid payout amount'}, status=status.HTTP_400_BAD_REQUEST)

        claim.payout_amount = payout_amount
        claim.status = 'Approved'
        claim.approval_date = timezone.now()
        if adjustment_note:
            claim.adjustment_note = adjustment_note

        # Prevent duplicate payments
        if not Payment.objects.filter(claim=claim).exists():
            Payment.objects.create(
                claim=claim,
                amount=payout_amount,
                is_paid=False
            )

        claim.save()
        return Response({
            'message': 'Claim approved successfully',
            'claim_number': claim.claim_number,
            'payout_amount': claim.payout_amount
        })

    else:  # Denied
        claim.status = 'Denied'
        claim.approval_date = timezone.now()
        claim.save()
        return Response({'message': 'Claim denied'})



@api_view(["GET"])
@permission_classes([IsAuthenticated])
def claim_timeline(request, claim_id):
    claim = get_object_or_404(Claim, id=claim_id, claimant=request.user)

    timeline = []

    # Step 1: Submitted
    timeline.append({
        "label": "Submitted",
        "timestamp": claim.claim_date,
        "status": "done" if claim.status != 'Submitted' else "in-progress",
        "message": "Claim was submitted by user."
    })

    # Step 2: Pending
    if claim.status in ["Pending", "Approved", "Denied"]:
        timeline.append({
            "label": "Pending Review",
            "timestamp": claim.claim_date,
            "status": "in-progress" if claim.status == "Pending" else "done",
            "message": "Claim is under review by the insurer."
        })

    # Step 3: Approved or Denied
    if claim.status in ["Approved", "Denied"]:
        timeline.append({
            "label": claim.status,
            "timestamp": claim.approval_date,
            "status": "done",
            "message": f"Claim was {claim.status.lower()}."
        })

    # Step 4: Payment (if approved)
    if claim.status == "Approved":
        payment = Payment.objects.filter(claim=claim).first()
        timeline.append({
            "label": "Paid",
            "timestamp": payment.payment_date if payment and payment.is_paid else None,
            "status": "done" if payment and payment.is_paid else "waiting",
            "message": "Payment has been completed." if payment and payment.is_paid else "Awaiting payment."
        })

    return Response({"timeline": timeline})



@api_view(['POST'])
def chatbot_interact(request):
    try:
        # Get user input from request data
        user_input = request.data.get('user_input')
        session_id = request.data.get('session_id', 'default')  # Optional session ID
        
        # Validate input
        if not user_input or not user_input.strip():
            return Response({
                "error": "user_input is required and cannot be empty"
            }, status=status.HTTP_400_BAD_REQUEST)
        
        # Get chatbot response
        response = get_chatbot_response(user_input.strip(), session_id)
        
        # Return successful response
        return Response({
            "success": True,
            "chatbot_response": response.get('chatbot_response'),
            "policies_response": response.get('policies_response'),
            "session_id": session_id
        }, status=status.HTTP_200_OK)
        
    except Exception as e:
        print(f"Chatbot API Error: {e}")
        return Response({
            "success": False,
            "error": "Internal server error",
            "chatbot_response": "Sorry, I'm having trouble processing your request right now."
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)





# @api_view(['GET'])
# def get_simple_subcategories(request):
#     # Filter subcategories that are used in Services
#     used_categories = Category.objects.filter(services__isnull=False).distinct()

#     # Serialize the filtered subcategories
#     category_serializer = CategorySerializer(used_categories, many=True).data
    
#     response = used_categories
#         #save the response in the subcategories.json file 
        
#     with open('categories.json', 'w') as file:
#         json.dump(response.json(), file)
    
#     return Response(category_serializer, status=status.HTTP_200_OK)


# list main categories
@api_view(['GET'])
def categories(request):
    categories = Category.objects.all()
    category_serializer = CategorySerializer(categories, many=True)
    response_data = {'categories': category_serializer.data}
    return Response(response_data, status=status.HTTP_200_OK)



@api_view(["GET"])
@permission_classes([IsAuthenticated])
def dashboard_summary(request):
    user = request.user

    # Customize depending on your models
    active_policies = UserPolicies.objects.filter(user=user, status="active").count()
    total_claims = Claim.objects.filter(claimant=user).count()
    pending_claims = Claim.objects.filter(claimant=user, status="Pending").count()
    total_paid = Transaction.objects.filter(user=user, transaction_type="Policy Payment").aggregate(Sum("amount"))["amount__sum"] or 0

    return Response({
        "active_policies": active_policies,
        "total_claims": total_claims,
        "pending_claims": pending_claims,
        "total_paid": total_paid,
    })