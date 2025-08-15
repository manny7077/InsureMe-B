from django.shortcuts import render
from rest_framework import viewsets
from rest_framework.views import APIView
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from rest_framework import status
from django.shortcuts import get_object_or_404
from rest_framework.exceptions import ValidationError
from django.utils.crypto import get_random_string
from django.utils import timezone
from django.contrib.auth import authenticate, login
from django.views.decorators.csrf import csrf_exempt
from .ai_logic import get_chatbot_response
from .models import (
    UserPolicies, Category, Company, InsurancePolicy, Claim, Messages, Payment, User, Transaction, ClaimDocument
)
from django.db.models import Sum, Count, Avg, Q, F, Max
from .serializers import (
    UserPoliciesSerializer, CategorySerializer, CompanySerializer, InsurancePolicySerializer, ClaimSerializer, UserLoginSerializer, UserSerializer
)
from rest_framework.authtoken.models import Token
from rest_framework.permissions import IsAuthenticated
from django.contrib.auth.models import Group
import os
from dateutil.relativedelta import relativedelta
from datetime import timedelta
from decimal import Decimal


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

    # Calculate expiry date
 
    expiry_date = timezone.now().date() + relativedelta(months=duration_months)

    # Create policy subscription
    user_policy = UserPolicies.objects.create(
        user=request.user,
        policy=policy,
        plan_type=plan_type,
        duration=duration_months,
        momo_number=momo_number,
        status="Active",
        expiry_date=expiry_date
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
        "joined_on": sub.creation_date,
        "expiry_date": sub.expiry_date,
        "premium": sub.policy.premium if sub.plan_type == 'Premium' else sub.policy.regular,
        "coverage_amount": sub.policy.premium_coverage_amount if sub.plan_type == 'Premium' else sub.policy.regular_coverage_amount
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
    
    # Get user's subscription to determine plan type and coverage
    user_subscription = UserPolicies.objects.filter(
        user=request.user, 
        policy=policy, 
        status='Active'
    ).first()
    
    if not user_subscription:
        return Response({'error': 'You do not have an active subscription for this policy'}, status=status.HTTP_400_BAD_REQUEST)
    
    # Check coverage based on plan type
    max_coverage = (
        policy.premium_coverage_amount if user_subscription.plan_type == 'Premium' 
        else policy.regular_coverage_amount
    )
    
    if float(claim_amount) > float(max_coverage):
        return Response({
            'error': f'Claim amount exceeds {user_subscription.plan_type} plan coverage of GHS {max_coverage}'
        }, status=status.HTTP_400_BAD_REQUEST)
    
    description = (
        f"Date: {date}\n"
        f"Time: {time}\n"
        f"Location: {location}\n"
        f"Incident: {incident_type}\n"
        f"Claim Amount: {claim_amount}\n"
        f"Plan Type: {user_subscription.plan_type}"
    )
    
    claim = Claim.objects.create(
        policy=policy,
        title=title,
        claimant=request.user,
        claim_amount=claim_amount,
        description=description
    )
    
    # Handle document uploads if provided
    uploaded_files = request.FILES.getlist('documents')
    for file in uploaded_files:
        ClaimDocument.objects.create(
            claim=claim,
            file=file
        )
    
    # Return more complete claim information
    return Response({
        'message': 'Claim submitted successfully',
        'claim_number': claim.claim_number,
        'claim_id': claim.id,
        'claim_date': claim.claim_date.isoformat(),  
        'status': claim.status,
        'documents_uploaded': len(uploaded_files)
    }, status=status.HTTP_201_CREATED)

@api_view(["GET"])
@permission_classes([IsAuthenticated])
def list_claims(request):
    claims = Claim.objects.filter(claimant=request.user)
    data = []
    
    for claim in claims:
        # Get user's plan type for this claim
        user_subscription = UserPolicies.objects.filter(
            user=request.user,
            policy=claim.policy,
            status='Active'
        ).first()
        
        claim_data = {
            'id': claim.id,
            'claim_number': claim.claim_number,
            'title': claim.title,
            'policy_name': claim.policy.name,
            'policy_type': user_subscription.plan_type if user_subscription else 'Unknown',
            'claim_amount': claim.claim_amount,
            'payout_amount': claim.payout_amount,
            'status': claim.status,
            'claim_date': claim.claim_date,
            'approval_date': claim.approval_date,
            'adjustment_note': claim.adjustment_note,
            'description': claim.description,
            'documents': [
                {
                    'id': doc.id,
                    'file_url': request.build_absolute_uri(doc.file.url), 
                    'filename': os.path.basename(doc.file.name),
                    'uploaded_at': doc.uploaded_at
                } for doc in claim.documents.all()
            ]
        }
        data.append(claim_data)
    
    return Response(data)

@api_view(["GET"])
def list_policies(request):
    policies = InsurancePolicy.objects.filter(is_active=True)

    data = []
    for policy in policies:
        data.append({
            "id": policy.id,
            "name": policy.name,
            "description": policy.description,
            "premium_coverage_amount": policy.premium_coverage_amount,
            "regular_coverage_amount": policy.regular_coverage_amount,
            "premium_price": policy.premium,
            "regular_price": policy.regular,
           
            "company": {
                "name": policy.company.name,
                "contact": policy.company.contact,
                "rating": policy.company.rating
            },
            "category": policy.category.name if policy.category else None
        })

    return Response(data, status=status.HTTP_200_OK)

@api_view(["GET"])
def get_policy_by_id(request, pk):
    try:
        policy = InsurancePolicy.objects.get(pk=pk)
    except InsurancePolicy.DoesNotExist:
        return Response({"detail": "Policy not found."}, status=status.HTTP_404_NOT_FOUND)

    data = {
        "id": policy.id,
        "name": policy.name,
        "description": policy.description,
        "premium_coverage_amount": policy.premium_coverage_amount,
        "regular_coverage_amount": policy.regular_coverage_amount,
        "premium_price": policy.premium,
        "regular_price": policy.regular,
      
        "company": {
            "name": policy.company.name,
            "contact": policy.company.contact,
            "rating": policy.company.rating,
            "description": policy.company.description
        },
        "category": policy.category.name if policy.category else None,
        "is_active": policy.is_active
    }
    
    return Response(data, status=status.HTTP_200_OK)

@api_view(["GET"])
@permission_classes([IsAuthenticated])
def recent_transactions(request):
    # Get regular transactions (policy payments and claim payouts)
    transactions = Transaction.objects.filter(user=request.user).order_by('-timestamp')
    
    data = []
    for tx in transactions:
        transaction_data = {
            "id": tx.id,
            "amount": tx.amount,
            "type": tx.transaction_type,
            "momo_number": tx.momo_number,
            "timestamp": tx.timestamp,
            "policy_name": tx.policy_subscription.policy.name,
        }
        
        # Add claim information for claim payouts
        if tx.transaction_type == "Claim Payout" and tx.claim:
            transaction_data.update({
                "claim_number": tx.claim.claim_number,
                "claim_title": tx.claim.title
            })
        
        data.append(transaction_data)

    # For backward compatibility, also include claim payouts from Payment records 
    # that don't have corresponding Transaction records
    existing_claim_transaction_ids = set(
        transactions.filter(transaction_type="Claim Payout", claim__isnull=False)
        .values_list('claim_id', flat=True)
    )
    
    # Get payments for approved claims that don't have transaction records
    payments_without_transactions = Payment.objects.filter(
        claim__claimant=request.user,
        is_paid=True
    ).exclude(claim_id__in=existing_claim_transaction_ids).select_related('claim', 'claim__policy')
    
    for payment in payments_without_transactions:
        # Get user's subscription for this claim
        user_subscription = UserPolicies.objects.filter(
            user=request.user,
            policy=payment.claim.policy
        ).first()
        
        if user_subscription:
            transaction_data = {
                "id": f"payment_{payment.id}",  # Unique ID for payment-based transactions
                "amount": payment.amount,
                "type": "Claim Payout",
                "momo_number": user_subscription.momo_number,
                "timestamp": payment.payment_date,
                "policy_name": payment.claim.policy.name,
                "claim_number": payment.claim.claim_number,
                "claim_title": payment.claim.title
            }
            data.append(transaction_data)

    # Sort all transactions by timestamp (most recent first)
    data.sort(key=lambda x: x['timestamp'], reverse=True)

    # Calculate summary statistics
    policy_payment_count = transactions.filter(transaction_type="Policy Payment").count()
    claim_payout_count = transactions.filter(transaction_type="Claim Payout").count() + payments_without_transactions.count()
    total_paid = transactions.filter(transaction_type="Policy Payment").aggregate(Sum("amount"))["amount__sum"] or 0
    total_received = (
        (transactions.filter(transaction_type="Claim Payout").aggregate(Sum("amount"))["amount__sum"] or 0) +
        (payments_without_transactions.aggregate(Sum("amount"))["amount__sum"] or 0)
    )

    return Response({
        "transactions": data,
        "summary": {
            "policy_payment_count": policy_payment_count,
            "claim_payout_count": claim_payout_count,
            "total_paid": total_paid,
            "total_received": total_received
        }
    })

def is_insurer(user):
    return user.groups.filter(name='Insurer').exists()

@api_view(["GET"])
@permission_classes([IsAuthenticated])
def all_claims(request):
    # For insurers to see all claims
    if not request.user.groups.filter(name='Insurer').exists():
        return Response({'error': 'Permission denied'}, status=status.HTTP_403_FORBIDDEN)
    
    claims = Claim.objects.all().order_by('-claim_date')
    data = []
    
    for claim in claims:
        # Get claimant's plan type
        user_subscription = UserPolicies.objects.filter(
            user=claim.claimant,
            policy=claim.policy
        ).first()
        
        claim_data = {
            'id': claim.id,
            'claim_number': claim.claim_number,
            'title': claim.title,
            'claimant': f"{claim.claimant.first_name} {claim.claimant.last_name}",
            'claimant_email': claim.claimant.email,
            'policy_name': claim.policy.name,
            'policy_type': user_subscription.plan_type if user_subscription else 'Unknown',
            'claim_amount': claim.claim_amount,
            'payout_amount': claim.payout_amount,
            'status': claim.status,
            'claim_date': claim.claim_date,
            'approval_date': claim.approval_date,
            'adjustment_note': claim.adjustment_note,
            'description': claim.description,
            'documents': [
                {
                    'id': doc.id,
                    'file_url': request.build_absolute_uri(doc.file.url),  
                    'filename': os.path.basename(doc.file.name),
                    'uploaded_at': doc.uploaded_at
                } for doc in claim.documents.all()
            ]
        }
        data.append(claim_data)
    
    return Response(data)

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

        # Get user's subscription to validate payout amount
        user_subscription = UserPolicies.objects.filter(
            user=claim.claimant,
            policy=claim.policy
        ).first()
        
        if user_subscription:
            max_coverage = (
                claim.policy.premium_coverage_amount if user_subscription.plan_type == 'Premium'
                else claim.policy.regular_coverage_amount
            )
            
            if payout_amount > float(max_coverage):
                return Response({
                    'error': f'Payout amount exceeds {user_subscription.plan_type} plan coverage of GHS {max_coverage}'
                }, status=status.HTTP_400_BAD_REQUEST)

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
                is_paid=True  # Mark as paid immediately for now
            )
            
            # Create a claim payout transaction
            if user_subscription:
                Transaction.objects.create(
                    user=claim.claimant,
                    policy_subscription=user_subscription,
                    transaction_type="Claim Payout",
                    claim=claim,
                    amount=payout_amount,
                    momo_number=user_subscription.momo_number
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
        if adjustment_note:
            claim.adjustment_note = adjustment_note
        claim.save()
        return Response({
            'message': 'Claim denied',
            'claim_number': claim.claim_number,
            'adjustment_note': claim.adjustment_note
        })

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
    approved_claims = Claim.objects.filter(claimant=user, status="Approved").count()
    total_paid = Transaction.objects.filter(user=user, transaction_type="Policy Payment").aggregate(Sum("amount"))["amount__sum"] or 0
    total_received = Transaction.objects.filter(user=user, transaction_type="Claim Payout").aggregate(Sum("amount"))["amount__sum"] or 0

    return Response({
        "active_policies": active_policies,
        "total_claims": total_claims,
        "pending_claims": pending_claims,
        "approved_claims": approved_claims,
        "total_paid": total_paid,
        "total_received": total_received,
    })

@api_view(["POST"])
@permission_classes([IsAuthenticated])
def upload_claim_document(request, claim_id):
    """Upload additional documents to an existing claim"""
    claim = get_object_or_404(Claim, id=claim_id, claimant=request.user)
    
    if claim.status not in ['Pending', 'Submitted']:
        return Response({
            'error': 'Cannot upload documents to processed claims'
        }, status=status.HTTP_400_BAD_REQUEST)
    
    uploaded_files = request.FILES.getlist('documents')
    if not uploaded_files:
        return Response({
            'error': 'No files provided'
        }, status=status.HTTP_400_BAD_REQUEST)
    
    documents = []
    for file in uploaded_files:
        doc = ClaimDocument.objects.create(
            claim=claim,
            file=file
        )
        documents.append({
            'id': doc.id,
            'file_url': doc.file.url,
            'uploaded_at': doc.uploaded_at
        })
    
    return Response({
        'message': f'{len(documents)} documents uploaded successfully',
        'documents': documents
    }, status=status.HTTP_201_CREATED)





@api_view(["GET"])
@permission_classes([IsAuthenticated])
def dashboard_summary(request):
    user = request.user

    # Customize depending on your models
    active_policies = UserPolicies.objects.filter(user=user, status="Active").count()
    total_claims = Claim.objects.filter(claimant=user).count()
    pending_claims = Claim.objects.filter(claimant=user, status="Pending").count()
    approved_claims = Claim.objects.filter(claimant=user, status="Approved").count()
    total_paid = Transaction.objects.filter(user=user, transaction_type="Policy Payment").aggregate(Sum("amount"))["amount__sum"] or 0
    total_received = Transaction.objects.filter(user=user, transaction_type="Claim Payout").aggregate(Sum("amount"))["amount__sum"] or 0

    return Response({
        "active_policies": active_policies,
        "total_claims": total_claims,
        "pending_claims": pending_claims,
        "approved_claims": approved_claims,
        "total_paid": total_paid,
        "total_received": total_received,
    })
