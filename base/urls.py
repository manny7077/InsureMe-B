from django.urls import path
from .views import (
    userLogin,
    logoutView,
    chatbot_interact,
    categories,
    submit_claim,
    join_policy, my_policies, submit_claim, list_claims,
    list_policies,
    recent_transactions,
    claim_timeline,
    get_policy_by_id,
    dashboard_summary,
    all_claims,
    process_claim,
    # analytics_dashboard

)

urlpatterns = [
    path('login/', userLogin),
    path('logout/', logoutView),

    path('join-policy/', join_policy),
    path('my-policies/', my_policies),
    path('submit-claim/', submit_claim),
    path('claims/', list_claims),
    path('all-claims/', all_claims),
    path('policies/', list_policies),
    path('recent-transactions/', recent_transactions),
    # path('analytics-dashboard/', analytics_dashboard),
    path('claim-timeline/<int:claim_id>/', claim_timeline),
    path("policies/<int:pk>/", get_policy_by_id),
    path("process-claim/<int:claim_id>/", process_claim),



    path('chatbot-interaction/', chatbot_interact, name='chatbot-interation'),
    
    # Categories
    path('categories/', categories, name='list-categories'),
    path('dashboard/summary/', dashboard_summary),
   
    
]
