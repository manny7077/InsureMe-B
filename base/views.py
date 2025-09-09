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

import logging

# Set up logging
logger = logging.getLogger(__name__)

def safe_float(value):
    """Safely convert Decimal, None, or other numeric types to float"""
    if value is None:
        return 0.0
    if isinstance(value, Decimal):
        return float(value)
    try:
        return float(value)
    except (ValueError, TypeError):
        return 0.0

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
def userSignup(request):
    """
    User registration endpoint
    Creates a new user account with basic information
    """
    try:
        data = request.data
        
        # Required fields
        username = data.get('username')
        email = data.get('email')
        password = data.get('password')
        first_name = data.get('first_name')
        last_name = data.get('last_name')
        
        # Validate required fields
        if not all([username, email, password, first_name, last_name]):
            return Response({
                'error': 'Missing required fields',
                'required': ['username', 'email', 'password', 'first_name', 'last_name']
            }, status=status.HTTP_400_BAD_REQUEST)
        
        # Check if username already exists
        if User.objects.filter(username=username).exists():
            return Response({
                'error': 'Username already exists'
            }, status=status.HTTP_400_BAD_REQUEST)
        
        # Check if email already exists
        if User.objects.filter(email=email).exists():
            return Response({
                'error': 'Email already registered'
            }, status=status.HTTP_400_BAD_REQUEST)
        
        # Validate email format
        from django.core.validators import validate_email
        from django.core.exceptions import ValidationError
        try:
            validate_email(email)
        except ValidationError:
            return Response({
                'error': 'Invalid email format'
            }, status=status.HTTP_400_BAD_REQUEST)
        
        # Validate password strength (minimum 8 characters)
        if len(password) < 8:
            return Response({
                'error': 'Password must be at least 8 characters long'
            }, status=status.HTTP_400_BAD_REQUEST)
        
        # Create the user
        user = User.objects.create_user(
            username=username,
            email=email,
            password=password,
            first_name=first_name,
            last_name=last_name
        )
        
        
        # Create authentication token
        token, created = Token.objects.get_or_create(user=user)
        
        # Serialize user data
        user_data = UserSerializer(user).data
        
        logger.info(f"New user registered: {username} ({email})")
        
        return Response({
            'message': 'Account created successfully',
            'token': token.key,
            'user': user_data
        }, status=status.HTTP_201_CREATED)
        
    except Exception as e:
        logger.error(f"Signup error: {e}")
        return Response({
            'error': 'Failed to create account',
            'details': str(e)
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

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
        
        logger.info(f"Chatbot request received: {user_input[:50] if user_input else 'None'}...")
        
        # Validate input
        if not user_input or not user_input.strip():
            logger.warning("Empty user input received")
            return Response({
                "error": "user_input is required and cannot be empty"
            }, status=status.HTTP_400_BAD_REQUEST)
        
        # Get chatbot response
        response = get_chatbot_response(user_input.strip(), session_id)
        
        logger.info("Chatbot response generated successfully")
        
        # Return successful response
        return Response({
            "success": True,
            "chatbot_response": response.get('chatbot_response'),
            "policies_response": response.get('policies_response'),
            "session_id": session_id
        }, status=status.HTTP_200_OK)
        
    except Exception as e:
        logger.error(f"Chatbot API Error: {e}")
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


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def insurer_analytics(request):
    """
    COMPREHENSIVE ANALYTICS DASHBOARD FOR INSURERS
    
    This endpoint calculates all key business metrics that insurers need to monitor:
    - Revenue Analytics: How much money is coming in
    - User Analytics: Customer base and growth
    - Policy Analytics: Product performance
    - Claims Analytics: Risk and payout analysis
    - Financial Analytics: Profitability and efficiency
    """
    if not is_insurer(request.user):
        return Response({'error': 'Only insurers can access analytics'}, status=status.HTTP_403_FORBIDDEN)
    
    try:
        # Date calculations for time-based metrics
        now = timezone.now()
        thirty_days_ago = now - timedelta(days=30)
        sixty_days_ago = now - timedelta(days=60)
        current_month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        last_month_start = (current_month_start - relativedelta(months=1))
        
        # ===== 1️⃣ REVENUE ANALYTICS =====
        """
        TOTAL REVENUE = Sum of all "Policy Payment" transactions
        This represents ALL money collected from customers for insurance premiums
        Sources: When users join policies, they make policy payments
        """
        total_revenue_result = Transaction.objects.filter(
            transaction_type="Policy Payment"  # Only policy payments count as revenue
        ).aggregate(total=Sum('amount'))['total']
        total_revenue = safe_float(total_revenue_result)
        
        """
        CURRENT MONTH REVENUE = Policy payments made this month
        Used to calculate growth trends
        """
        current_month_revenue_result = Transaction.objects.filter(
            transaction_type="Policy Payment",
            timestamp__gte=current_month_start  # From start of current month
        ).aggregate(total=Sum('amount'))['total']
        current_month_revenue = safe_float(current_month_revenue_result)
        
        """
        LAST MONTH REVENUE = Policy payments made last month
        Used to calculate month-over-month growth percentage
        """
        last_month_revenue_result = Transaction.objects.filter(
            transaction_type="Policy Payment",
            timestamp__gte=last_month_start,
            timestamp__lt=current_month_start  # Between last month start and current month start
        ).aggregate(total=Sum('amount'))['total']
        last_month_revenue = safe_float(last_month_revenue_result)
        
        """
        REVENUE GROWTH = ((Current Month - Last Month) / Last Month) * 100
        Positive = growing, Negative = declining
        """
        revenue_growth = 0
        if last_month_revenue > 0:
            revenue_growth = ((current_month_revenue - last_month_revenue) / last_month_revenue) * 100
        
        # Monthly revenue trend for charts (last 12 months)
        monthly_revenue = []
        for i in range(12):
            month_start = current_month_start - relativedelta(months=i)
            month_end = month_start + relativedelta(months=1) - timedelta(seconds=1)
            
            # Revenue for this month
            revenue_result = Transaction.objects.filter(
                transaction_type="Policy Payment",
                timestamp__gte=month_start,
                timestamp__lte=month_end
            ).aggregate(total=Sum('amount'))['total']
            revenue = safe_float(revenue_result)
            
            # Payouts for this month
            payouts_result = Transaction.objects.filter(
                transaction_type="Claim Payout",
                timestamp__gte=month_start,
                timestamp__lte=month_end
            ).aggregate(total=Sum('amount'))['total']
            payouts = safe_float(payouts_result)
            
            monthly_revenue.append({
                'month': month_start.strftime('%b %Y'),
                'revenue': revenue,
                'payouts': payouts
            })
        
        monthly_revenue.reverse()  # Show oldest to newest for charts
        
        # ===== 2️⃣ USER ANALYTICS =====
        """
        TOTAL USERS = All users except insurers
        This is your customer base size
        """
        total_users = User.objects.exclude(groups__name='Insurer').count()
        
        """
        ACTIVE USERS = Users who have at least one active policy
        This shows how many customers are currently paying
        """
        active_users = UserPolicies.objects.filter(
            status="Active"
        ).values('user').distinct().count()
        
        """
        ACTIVE USER RATE = (Active Users / Total Users) * 100
        Shows what percentage of your customers are currently active
        Higher is better - means more customers are engaged
        """
        active_user_rate = (active_users / total_users * 100) if total_users > 0 else 0
        
        """
        NEW USERS (30 DAYS) = Users who joined in last 30 days
        Shows recent customer acquisition
        """
        new_users_30_days = User.objects.exclude(groups__name='Insurer').filter(
            date_joined__gte=thirty_days_ago
        ).count()
        
        """
        NEW USERS (PREVIOUS 30 DAYS) = Users who joined 30-60 days ago
        Used to calculate user growth rate
        """
        new_users_previous_30_days = User.objects.exclude(groups__name='Insurer').filter(
            date_joined__gte=sixty_days_ago,
            date_joined__lt=thirty_days_ago
        ).count()
        
        """
        USER GROWTH = ((Recent 30 days - Previous 30 days) / Previous 30 days) * 100
        Shows if customer acquisition is accelerating or slowing
        """
        user_growth = 0
        if new_users_previous_30_days > 0:
            user_growth = ((new_users_30_days - new_users_previous_30_days) / new_users_previous_30_days) * 100
        
        # ===== 3️⃣ POLICY ANALYTICS =====
        """
        TOTAL POLICIES = All policy subscriptions ever created
        ACTIVE POLICIES = Currently active policy subscriptions
        EXPIRED POLICIES = Policies that have expired
        """
        total_policies = UserPolicies.objects.count()
        active_policies = UserPolicies.objects.filter(status="Active").count()
        expired_policies = UserPolicies.objects.filter(status="Expired").count()
        
        """
        PREMIUM vs REGULAR POLICIES
        Shows which plan types are more popular
        """
        premium_policies = UserPolicies.objects.filter(plan_type="Premium").count()
        regular_policies = UserPolicies.objects.filter(plan_type="Regular").count()
        
        # Top performing policies by revenue
        top_policies = []
        policies = InsurancePolicy.objects.all()
        for policy in policies:
            subscriber_count = UserPolicies.objects.filter(policy=policy).count()
            
            # Calculate total revenue from this policy
            revenue_result = Transaction.objects.filter(
                transaction_type="Policy Payment",
                policy_subscription__policy=policy
            ).aggregate(total=Sum('amount'))['total']
            revenue = safe_float(revenue_result)
            
            if subscriber_count > 0:
                top_policies.append({
                    'name': policy.name,
                    'subscribers': subscriber_count,
                    'revenue': revenue,
                    'category': policy.category.name if policy.category else 'Uncategorized'
                })
        
        top_policies.sort(key=lambda x: x['revenue'], reverse=True)  # Sort by revenue
        
        # ===== 4️⃣ CLAIMS ANALYTICS =====
        """
        CLAIMS BY STATUS
        - TOTAL CLAIMS = All claims ever submitted
        - SUBMITTED = Just submitted, not yet reviewed
        - PENDING = Under review by insurers
        - APPROVED = Approved for payout
        - DENIED = Rejected claims
        """
        total_claims = Claim.objects.count()
        submitted_claims = Claim.objects.filter(status="Submitted").count()
        pending_claims = Claim.objects.filter(status="Pending").count()
        approved_claims = Claim.objects.filter(status="Approved").count()
        denied_claims = Claim.objects.filter(status="Denied").count()
        
        """
        APPROVAL RATE = (Approved Claims / Total Claims) * 100
        Shows what percentage of claims you approve
        Industry standard is usually 85-95%
        """
        approval_rate = (approved_claims / total_claims * 100) if total_claims > 0 else 0
        
        """
        CLAIM RATE = (Total Claims / Active Users) * 100
        Shows how often your customers file claims
        Lower is better - means fewer incidents/risks
        """
        claim_rate = (total_claims / active_users * 100) if active_users > 0 else 0
        
        # Total payouts calculation (money paid out for claims)
        """
        TOTAL PAYOUTS = All money paid out for approved claims
        Comes from two sources:
        1. Transaction table (newer claims)
        2. Payment table (older claims, for backward compatibility)
        """
        transaction_payouts_result = Transaction.objects.filter(
            transaction_type="Claim Payout"
        ).aggregate(total=Sum('amount'))['total']
        transaction_payouts = safe_float(transaction_payouts_result)
        
        # Get payouts from Payment table that don't have corresponding transactions
        payment_payouts_result = Payment.objects.filter(
            is_paid=True
        ).exclude(
            claim__in=Transaction.objects.filter(
                transaction_type="Claim Payout"
            ).values_list('claim_id', flat=True)
        ).aggregate(total=Sum('amount'))['total']
        payment_payouts = safe_float(payment_payouts_result)
        
        total_payouts = transaction_payouts + payment_payouts
        
        # Average claim amounts
        """
        AVERAGE CLAIM AMOUNT = Average amount customers request
        AVERAGE PAYOUT AMOUNT = Average amount actually paid out
        Difference shows how much claims are adjusted down
        """
        avg_claim_amount_result = Claim.objects.aggregate(avg=Avg('claim_amount'))['avg']
        avg_claim_amount = safe_float(avg_claim_amount_result)
        
        avg_payout_amount_result = Claim.objects.filter(
            status="Approved",
            payout_amount__isnull=False
        ).aggregate(avg=Avg('payout_amount'))['avg']
        avg_payout_amount = safe_float(avg_payout_amount_result)
        
        """
        CLAIMS PROCESSING TIME = Average days to approve/deny claims
        Shows operational efficiency
        Faster is better for customer satisfaction
        """
        avg_processing_time = Claim.objects.filter(
            status__in=["Approved", "Denied"],
            approval_date__isnull=False
        ).aggregate(
            avg_days=Avg(
                F('approval_date') - F('claim_date')  # Difference in days
            )
        )['avg_days']
        
        avg_processing_days = avg_processing_time.days if avg_processing_time else 0
        
        # ===== 5️⃣ FINANCIAL ANALYTICS =====
        """
        PROFIT = Total Revenue - Total Payouts
        This is your net income from insurance operations
        """
        profit = total_revenue - total_payouts
        
        """
        PROFIT MARGIN = (Profit / Total Revenue) * 100
        Shows what percentage of revenue you keep as profit
        Industry standard is usually 5-15%
        """
        profit_margin = (profit / total_revenue * 100) if total_revenue > 0 else 0
        
        """
        LOSS RATIO = (Total Payouts / Total Revenue) * 100
        Critical insurance metric - shows what % of premiums are paid out as claims
        Industry standard is usually 60-80%
        Above 100% means you're losing money
        """
        loss_ratio = (total_payouts / total_revenue * 100) if total_revenue > 0 else 0
        
        """
        AVERAGE REVENUE PER USER (ARPU) = Total Revenue / Total Users
        Shows how much each customer is worth on average
        """
        arpu = total_revenue / (total_policies * 12) if total_policies > 0 else 0
        
        """
        CUSTOMER LIFETIME VALUE (CLV) = Average Monthly Premium × Average Policy Duration
        Estimates total value of a customer over their lifetime
        """
        avg_policy_duration_result = UserPolicies.objects.aggregate(avg=Avg('duration'))['avg']
        avg_policy_duration = safe_float(avg_policy_duration_result)
        avg_monthly_premium = total_revenue / (total_policies * 12) if total_policies > 0 else 0
        customer_ltv = avg_monthly_premium * avg_policy_duration if avg_policy_duration > 0 else 0
        
        # ===== 6️⃣ RECENT ACTIVITY (30 DAYS) =====
        """
        Recent activity metrics show business momentum
        """
        recent_signups = User.objects.exclude(groups__name='Insurer').filter(
            date_joined__gte=thirty_days_ago
        ).count()
        
        recent_policies = UserPolicies.objects.filter(
            creation_date__gte=thirty_days_ago
        ).count()
        
        recent_claims = Claim.objects.filter(
            claim_date__gte=thirty_days_ago
        ).count()
        
        # Return all calculated metrics
        return Response({
            'overview': {
                'total_revenue': total_revenue,           # All-time policy payments
                'total_users': total_users,               # Total customer count
                'active_policies': active_policies,       # Currently active subscriptions
                'total_claims': total_claims,             # All claims submitted
                'profit': profit,                         # Revenue - Payouts
                'profit_margin': profit_margin,           # Profit as % of revenue
                'loss_ratio': loss_ratio,                 # Payouts as % of revenue (key insurance metric)
                'claim_approval_rate': approval_rate      # % of claims approved
            },
            'revenue': {
                'total': total_revenue,                   # All-time policy payments
                'current_month': current_month_revenue,   # This month's payments
                'last_month': last_month_revenue,         # Last month's payments
                'growth': revenue_growth,                 # Month-over-month growth %
                'monthly_trend': monthly_revenue,         # 12-month trend data
                'arpu': arpu                             # Average revenue per user
            },
            'users': {
                'total': total_users,                     # Total customer count
                'active': active_users,                   # Users with active policies
                'active_rate': active_user_rate,          # % of users who are active
                'new_30_days': new_users_30_days,         # New customers (30 days)
                'growth': user_growth,                    # Customer growth rate
                'customer_ltv': customer_ltv              # Customer lifetime value
            },
            'policies': {
                'total': total_policies,                  # All policy subscriptions
                'active': active_policies,                # Currently active policies
                'expired': expired_policies,              # Expired policies
                'premium': premium_policies,              # Premium plan subscriptions
                'regular': regular_policies,              # Regular plan subscriptions
                'top_performing': top_policies[:10]       # Top 10 policies by revenue
            },
            'claims': {
                'total': total_claims,                    # All claims submitted
                'submitted': submitted_claims,            # Just submitted
                'pending': pending_claims,                # Under review
                'approved': approved_claims,              # Approved for payout
                'denied': denied_claims,                  # Rejected claims
                'approval_rate': approval_rate,           # % of claims approved
                'claim_rate': claim_rate,                 # Claims per active user
                'total_payouts': total_payouts,           # Total money paid out
                'avg_claim_amount': avg_claim_amount,     # Average claim request
                'avg_payout_amount': avg_payout_amount,   # Average actual payout
                'avg_processing_days': avg_processing_days # Average processing time
            },
            'risk': {
                'loss_ratio': loss_ratio                  # Critical risk metric
            },
            'recent_activity': {
                'signups': recent_signups,                # New customers (30 days)
                'policies': recent_policies,              # New policies (30 days)
                'claims': recent_claims                   # New claims (30 days)
            }
        })
        
    except Exception as e:
        return Response({
            'error': 'Failed to fetch analytics data',
            'details': str(e)
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)