"""
Example usage of Google AI service for WhatsApp bot
This demonstrates how to integrate Gemini AI into your WhatsApp responses
"""

from app.services.google_ai_service import GoogleAIClient, generate_text, generate_chat_response


def example_simple_text_generation():
    """Simple example: Generate text from a prompt"""
    print("=== Example 1: Simple Text Generation ===")
    
    prompt = "What are some fun activities to do in Paris?"
    response = generate_text(prompt, temperature=0.7, max_output_tokens=200)
    print(f"Prompt: {prompt}")
    print(f"Response: {response}\n")


def example_chat_conversation():
    """Example: Multi-turn chat conversation"""
    print("=== Example 2: Chat Conversation ===")
    
    client = GoogleAIClient()
    
    messages = [
        {"role": "user", "content": "Hello! I'm planning a trip to Paris."},
        {"role": "assistant", "content": "That sounds wonderful! Paris is an amazing destination. What would you like to know?"},
        {"role": "user", "content": "What's the best time to visit?"}
    ]
    
    response = generate_chat_response(messages, temperature=0.8, max_output_tokens=300)
    print(f"Response: {response}\n")


def example_whatsapp_response_generator():
    """Example: Use Google AI to generate WhatsApp responses"""
    print("=== Example 3: WhatsApp Response Generator ===")
    
    # Simulating a customer support scenario
    customer_message = "Hi, I have a problem with my Airbnb booking. The WiFi isn't working!"
    
    prompt = f"""You are a helpful Airbnb customer support assistant. 
    A customer sent this message: "{customer_message}"
    
    Please respond in a friendly and helpful manner. Keep response under 100 words.
    """
    
    response = generate_text(prompt, temperature=0.7, max_output_tokens=150)
    print(f"Customer: {customer_message}")
    print(f"AI Response: {response}\n")


def example_with_flask_integration():
    """Example: Integration with Flask route"""
    print("=== Example 4: Flask Integration (Reference) ===")
    
    example_code = '''
    from flask import Blueprint, request, current_app
    from app.services.google_ai_service import generate_text
    
    ai_bp = Blueprint('ai', __name__, url_prefix='/api/ai')
    
    @ai_bp.route('/ask', methods=['POST'])
    def ask_gemini():
        """Endpoint to ask Gemini AI"""
        data = request.json
        user_question = data.get('question', '')
        
        if not user_question:
            return {'error': 'No question provided'}, 400
        
        try:
            response = generate_text(
                prompt=user_question,
                temperature=0.7,
                max_output_tokens=500
            )
            return {
                'question': user_question,
                'answer': response,
                'model': 'gemini-pro'
            }
        except Exception as e:
            return {'error': str(e)}, 500
    '''
    print(example_code)


def example_custom_client():
    """Example: Using custom client with specific settings"""
    print("=== Example 5: Custom Client ===")
    
    # Create a client instance
    client = GoogleAIClient(model=GoogleAIClient.GEMINI_PRO)
    
    # Generate with custom parameters
    prompt = "Tell me a fun fact about Python programming"
    response = client.generate_text(
        prompt=prompt,
        temperature=0.9,  # More creative
        max_output_tokens=200
    )
    print(f"Fun fact: {response}\n")


def main():
    """Run all examples"""
    print("Google AI Service Examples for WhatsApp Bot\n")
    print("=" * 50)
    
    try:
        example_simple_text_generation()
        example_chat_conversation()
        example_whatsapp_response_generator()
        example_custom_client()
        example_with_flask_integration()
    except Exception as e:
        print(f"Error running examples: {e}")
        print("\nMake sure you have set GOOGLE_AI_API_KEY in your .env file!")
        print("Get your free key from: https://aistudio.google.com/app/apikey")


if __name__ == "__main__":
    main()
