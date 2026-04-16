prompt += f"""
CUSTOMER DATA SOURCE OF TRUTH (JSON):
{customer_data_str}
"""

# Include guidelines from Dialogflow parameters if available
metadata = conversation_json.get("conversation_metadata", {})
safety_guidelines = metadata.get("safety_guidelines")
brand_guidelines = metadata.get("brand_guidelines")

if safety_guidelines:
prompt += f"""
SAFETY GUIDELINES:
{safety_guidelines}
"""



test automation system prompt:
 
