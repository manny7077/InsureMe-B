import os
import json
import time
from difflib import get_close_matches
import requests
from groq import Groq
from django.conf import settings
import logging
from .models import InsurancePolicy, Category, Company
from .serializers import InsurancePolicySerializer

# Set up logging
logger = logging.getLogger(__name__)

# Load environment variables
try:
    from dotenv import load_dotenv
    load_dotenv()
    logger.info("✅ dotenv loaded successfully")
except ImportError:
    logger.warning("❌ python-dotenv not installed")

def get_available_categories():
    """Get all available categories from the database"""
    try:
        categories = Category.objects.all().values('id', 'name')
        return list(categories)
    except Exception as e:
        logger.error(f"Error fetching categories from database: {e}")
        return []

# Initialize Groq client with better error handling
def get_groq_client():
    # Try multiple ways to get API key
    api_key = (
        os.getenv('GROQ_API_KEY') or 
        getattr(settings, 'GROQ_API_KEY', None)
    )
    
    logger.info(f"🔍 Environment API Key: {'Found' if api_key else 'Not Found'}")
    
    if not api_key:
        logger.error("❌ GROQ_API_KEY not found in environment or settings")
        return None
    
    try:
        client = Groq(api_key=api_key)
        # Test the client with a simple request
        test_response = client.chat.completions.create(
            messages=[{"role": "user", "content": "test"}],
            model="llama-3.1-8b-instant",
            max_tokens=10
        )
        logger.info("✅ Groq client initialized and tested successfully")
        return client
    except Exception as e:
        logger.error(f"❌ Error initializing Groq client: {e}")
        return None

# Initialize client
client = get_groq_client()

# Session-based conversation history
conversation_sessions = {}

def get_chatbot_response(user_input, session_id='default'):
    global client
    
    logger.info(f"Processing chatbot request: {user_input[:50]}...")
    
    if not client:
        logger.error("Groq client not available")
        return {
            "chatbot_response": "Sorry, the AI service is currently unavailable. Please check the API configuration.",
            "policies_response": None
        }
    
    # Get or create session history
    if session_id not in conversation_sessions:
        conversation_sessions[session_id] = []
    
    conversation_history = conversation_sessions[session_id]
    
    available_categories = get_available_categories()
    category_names = [cat['name'] for cat in available_categories]
    
    actual_policies = []
    try:
        policies = InsurancePolicy.objects.filter(is_active=True).select_related('company', 'category')[:10]
        for policy in policies:
            actual_policies.append({
                'name': policy.name,
                'category': policy.category.name,
                'company': policy.company.name,
                'regular_price': f"GHS {float(policy.regular):.2f}",
                'premium_price': f"GHS {float(policy.premium):.2f}",
                'description': policy.description[:100] + '...' if len(policy.description) > 100 else policy.description
            })
    except Exception as e:
        logger.error(f"Error fetching policies for system prompt: {e}")
    
    # Add system message if new session
    if not conversation_history:
        system_message = {
            "role": "system",
            "content": (
                f"You are a helpful insurance assistant for our specific insurance platform. "
                f"IMPORTANT: You can ONLY discuss the insurance categories and policies that we actually offer. "
                f"Our available insurance categories are: {', '.join(category_names)}. "
                f"Here are our actual available policies: {actual_policies}. "
                f"When users ask about insurance, you must ONLY reference these specific policies and categories. "
                f"Do NOT mention any insurance products, companies, or coverage types that are not in our database. "
                f"If a user asks about insurance types we don't offer, politely tell them we don't currently provide that type. "
                f"CURRENCY: Always use GHS (Ghana Cedis) for all pricing. Never use $ or any other currency symbol. "
                f"When mentioning prices, always format them as 'GHS X' where X is the amount. "
                f"Always be conversational, helpful, and professional. Never respond in JSON format - always use natural language. "
                f"When discussing policies, reference the actual names, companies, and prices from our database using GHS currency only."
            )
        }
        conversation_history.append(system_message)
    
    # Add user message
    conversation_history.append({"role": "user", "content": user_input})
    
    try:
        # Generate response
        logger.info("Calling Groq API...")
        chat_completion = client.chat.completions.create(
            messages=conversation_history,
            model="llama-3.1-8b-instant",
            temperature=0.7,
            max_tokens=1024,
            top_p=1,
            stop=None,
            stream=False
        )
        
        response_content = chat_completion.choices[0].message.content
        logger.info(f"Groq API response received: {response_content[:100]}...")
        
        # Add assistant response to history
        conversation_history.append({"role": "assistant", "content": response_content})
        
        # Limit conversation history
        if len(conversation_history) > 20:
            conversation_sessions[session_id] = [conversation_history[0]] + conversation_history[-18:]
        
        detected_category = detect_insurance_category(user_input)
        policies_response = None
        
        if detected_category:
            logger.info(f"Category detected from user input: {detected_category}")
            policies_response = get_policies_by_category_name(detected_category)
            
            # Log interaction
            log_interaction(user_input, detected_category, response_content)
        
        combined_response = {
            "chatbot_response": response_content,
            "policies_response": policies_response
        }
        
        return combined_response
        
    except Exception as e:
        logger.error(f"Error getting chatbot response: {e}")
        return {
            "chatbot_response": f"Sorry, I encountered an error: {str(e)}",
            "policies_response": None
        }

def detect_insurance_category(user_input):
    """Detect insurance category from user input using database categories and keywords"""
    user_input_lower = user_input.lower()
    
    # Get actual categories from database
    available_categories = get_available_categories()
    
    # First, try direct category name matching
    for category in available_categories:
        if category['name'].lower() in user_input_lower:
            return category['name']
    
    # If no direct match, use keyword matching
    category_keywords = {
        "Health": ["health", "medical", "healthcare", "doctor", "hospital", "medicine", "clinic"],
        "Auto": ["auto", "car", "vehicle", "driving", "motor", "automotive", "automobile"],
        "Life": ["life", "death", "beneficiary", "term life", "whole life", "life insurance"],
        "Travel": ["travel", "trip", "vacation", "international", "abroad", "journey"],
        "Business": ["business", "commercial", "company", "enterprise", "liability", "professional"],
        "Home": ["home", "house", "property", "homeowner", "dwelling", "residential"],
        "Disability": ["disability", "disabled", "income protection", "unable to work", "injury"]
    }
    
    # Check if any of our available categories match the keywords
    for category in available_categories:
        category_name = category['name']
        if category_name in category_keywords:
            keywords = category_keywords[category_name]
            if any(keyword in user_input_lower for keyword in keywords):
                return category_name
    
    return None

def get_policies_by_category_name(category_name):
    """Get policies by category name from the database"""
    try:
        # Find the category
        category = Category.objects.filter(name__iexact=category_name).first()
        
        if not category:
            return {"message": f"We don't offer {category_name} insurance policies yet"}
        
        # Get policies for this category
        policies = InsurancePolicy.objects.filter(
            category=category, 
            is_active=True
        ).select_related('company', 'category')
        
        if not policies.exists():
            return {"message": f"We don't offer {category_name} insurance policies yet"}
        
        policy_data = []
        for policy in policies:
            policy_info = {
                "id": policy.id,
                "name": policy.name,
                "description": policy.description,
                "company": {
                    "name": policy.company.name,
                    "rating": float(policy.company.rating),
                    "contact": policy.company.contact
                },
                "category": policy.category.name,
                "pricing": {
                    "regular": {
                        "monthly_price": f"GHS {float(policy.regular):.2f}",
                        "monthly_price_raw": float(policy.regular),
                        "coverage_amount": f"GHS {float(policy.regular_coverage_amount):,.2f}"
                    },
                    "premium": {
                        "monthly_price": f"GHS {float(policy.premium):.2f}",
                        "monthly_price_raw": float(policy.premium),
                        "coverage_amount": f"GHS {float(policy.premium_coverage_amount):,.2f}"
                    }
                },
                "regular_price": float(policy.regular),
                "is_active": policy.is_active
            }
            policy_data.append(policy_info)
        
        logger.info(f"Found {len(policy_data)} policies for category {category_name}")
        return {"policies": policy_data}
        
    except Exception as e:
        logger.error(f"Error fetching policies for category {category_name}: {e}")
        return {"message": "Error fetching policies"}

def log_interaction(user_input, label, answer):
    log_entry = {
        "timestamp": int(time.time() * 1000),
        "tag": label,
        "user_input": user_input,
        "ai_response": answer,
        "category": label
    }
    
    try:
        log_file = os.path.join(os.path.dirname(__file__), 'chat_interactions.json')
        
        # Load existing data
        if os.path.exists(log_file):
            with open(log_file, 'r') as file:
                try:
                    data = json.load(file)
                except json.JSONDecodeError:
                    data = []
        else:
            data = []
        
        # Add new entry
        data.append(log_entry)
        
        # Write back to file
        with open(log_file, 'w') as file:
            json.dump(data, file, indent=2)
            
        logger.info("Interaction logged successfully")
                
    except Exception as e:
        logger.error(f"Error logging interaction: {e}")

# Test function
def test_chatbot():
    """Test function to verify chatbot is working"""
    test_input = "I need health insurance"
    response = get_chatbot_response(test_input)
    print(f"Test Response: {response}")
    return response

def refresh_categories():
    """Refresh categories from database - no longer needed but kept for compatibility"""
    try:
        categories = get_available_categories()
        logger.info(f"Found {len(categories)} categories in database")
        return categories
    except Exception as e:
        logger.error(f"Error refreshing categories: {e}")
        return []

# Progressive chat loop with memory
def chat_loop():
    print("Welcome to the Progressive Chatbot with Memory! (Type 'exit' to end the chat)\n")
    while True:
        user_input = input("You: ")
        if user_input.lower() == 'exit':
            break
        response = get_chatbot_response(user_input)
        print(f"Bot: {response}\n")

if __name__ == "__main__":
    refresh_categories()  # Check available categories
    chat_loop()
