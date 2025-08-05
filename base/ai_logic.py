import os
import json
from difflib import get_close_matches
import requests
from groq import Groq
from .models import InsurancePolicy
from .serializers import InsurancePolicySerializer

# Load environment variables (add this if using .env file)
try:
    from dotenv import load_dotenv
    load_dotenv()
    print("✅ dotenv loaded successfully")
except ImportError:
    print("❌ python-dotenv not installed. Install with: pip install python-dotenv")

# Load subcategories
subcategories_path = os.path.join(os.path.dirname(__file__), 'subcategories.json')
try:
    with open(subcategories_path, 'r') as file:
        subcategories = json.load(file)
    print("✅ Subcategories loaded successfully")
except FileNotFoundError:
    print("❌ subcategories.json not found")
    subcategories = []

# Initialize Groq client with error handling
def get_groq_client():
    # Try to get API key from environment
    api_key = os.getenv('GROQ_API_KEY')
    
    print(f"🔍 Environment API Key: {'Found' if api_key else 'Not Found'}")
    
    if not api_key:
        print("❌ GROQ_API_KEY environment variable not set")
        print("Please set it with: export GROQ_API_KEY=your_api_key_here")
        return None
    
    try:
        client = Groq(api_key=api_key)
        print("✅ Groq client initialized successfully")
        return client
    except Exception as e:
        print(f"❌ Error initializing Groq client: {e}")
        return None

client = get_groq_client()

# Session-based conversation history (in production, use Redis or database)
conversation_sessions = {}

def get_chatbot_response(user_input, session_id='default'):
    global client
    
    if not client:
        return {
            "chatbot_response": "Sorry, the AI service is currently unavailable.",
            "policies_response": None
        }
    
    # Get or create session history
    if session_id not in conversation_sessions:
        conversation_sessions[session_id] = []
    
    conversation_history = conversation_sessions[session_id]
    
    # Define the categories that should populate the label
    valid_categories = [
        "Disability", "Travel", "Business", "Home",
        "Auto", "Health", "Life",
    ]
    
    # Add system message if this is a new session
    if not conversation_history:
        system_message = {
            "role": "system",
            "content": (
                "You are an insurance assistant. Help users find insurance policies. "
                f"When users ask about these categories: {', '.join(valid_categories)}, "
                "respond with JSON format: {{\"label\": \"category_name\", \"answer\": \"helpful_response\"}}. "
                "For other questions, provide helpful general responses about insurance."
            )
        }
        conversation_history.append(system_message)
    
    # Add the user message to the conversation history
    conversation_history.append({"role": "user", "content": user_input})
    
    try:
        # Generate a response from the chatbot using the entire conversation history
        chat_completion = client.chat.completions.create(
            messages=conversation_history,
            model="llama3-70b-8192",
            temperature=0.7,
            max_tokens=1024,
            top_p=1,
            stop=None,
            stream=False
        )
        
        response_content = chat_completion.choices[0].message.content
        
        # Add the assistant response to the conversation history
        conversation_history.append({"role": "assistant", "content": response_content})
        
        # Limit conversation history to prevent token overflow
        if len(conversation_history) > 20:
            # Keep system message and last 18 messages
            conversation_sessions[session_id] = [conversation_history[0]] + conversation_history[-18:]
        
        combined_response = {
            "chatbot_response": response_content,
            "policies_response": None
        }
        
        # Check if the response is in JSON format and extract the "label" field
        try:
            response_json = json.loads(response_content)
            
            if isinstance(response_json, dict) and "label" in response_json:
                label = response_json.get("label", "")
                
                if label in valid_categories:
                    category_id = get_category_id(label)
                    policies = get_policies(category_id)
                    combined_response["chatbot_response"] = response_json
                    combined_response["policies_response"] = policies
                    
                    # Log the interaction in chat_interactions.json
                    log_interaction(user_input, label, response_json.get("answer", ""))
                    
        except json.JSONDecodeError:
            label = None
        
        # Return the generated JSON content or text response
        return combined_response
        
    except Exception as e:
        print(f"Error getting chatbot response: {e}")
        return {
            "chatbot_response": "Sorry, I'm having trouble processing your request right now.",
            "policies_response": None
        }

# Rest of your functions remain the same...
BASE_URL = 'http://localhost:5173'

def get_categories():
    try:
        response = requests.get(f'{BASE_URL}categories/')
        response.raise_for_status()
        
        with open('subcategories.json', 'w') as file:
            json.dump(response.json(), file)
    except requests.exceptions.RequestException as e:
        print(f"An error occurred: {e}")
        return None

def get_category_id(subcat_name):
    if not subcat_name or not subcategories:
        return None
        
    subcat_name = subcat_name.lower()
    subcategory_names = [subcat['name'].lower() for subcat in subcategories]
    
    close_match = get_close_matches(subcat_name, subcategory_names, n=1, cutoff=0.6)
    
    if close_match:
        matched_subcategory_name = close_match[0]
        category_id = next(
            (subcat['id'] for subcat in subcategories 
             if subcat['name'].lower() == matched_subcategory_name), 
            None
        )
        return category_id
    
    return None

def get_policies(category_id):
    try:
        if category_id is None:
            return {"message": "We don't offer these type of policies yet"}
            
        policies = InsurancePolicy.objects.filter(company__company_category=category_id)
        
        if not policies.exists():
            return {"message": "We don't offer these type of policies yet"}
        
        policy_serializer = InsurancePolicySerializer(policies, many=True)
        return {"policies": policy_serializer.data}
        
    except Exception as e:
        print(f"Error fetching policies: {e}")
        return {"message": "Error fetching policies"}

def log_interaction(user_input, label, answer):
    log_entry = {
        "timestamp": json.dumps({"$date": {"$numberLong": str(int(os.time.time() * 1000))}}),
        "tag": label,
        "user_input": user_input,
        "ai_response": answer,
        "category": label
    }
    
    try:
        log_file = 'chat_interactions.json'
        if os.path.exists(log_file):
            with open(log_file, 'r+') as file:
                try:
                    data = json.load(file)
                except json.JSONDecodeError:
                    data = []
                
                data.append(log_entry)
                file.seek(0)
                file.truncate()
                json.dump(data, file, indent=2)
        else:
            with open(log_file, 'w') as file:
                json.dump([log_entry], file, indent=2)
                
    except Exception as e:
        print(f"Error logging interaction: {e}")

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
    get_categories()  # activate this to populate the subcategories JSON file
    chat_loop()
