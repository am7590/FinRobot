import os
import autogen
from textwrap import dedent
from finrobot.utils import register_keys_from_json
from finrobot.agents.workflow import SingleAssistantShadow

llm_config = {
    "config_list": autogen.config_list_from_json(
        "OAI_CONFIG_LIST",
        filter_dict={
            "model": ["gpt-4o-mini"],
        },
    ),
    "timeout": 120,
    "temperature": 0.5,
}
register_keys_from_json("config_api_keys")

work_dir = "../report"
os.makedirs(work_dir, exist_ok=True)

assistant = SingleAssistantShadow(
    "Expert_Investor",
    llm_config,
    max_consecutive_auto_reply=None,
    human_input_mode="ALWAYS",
)

company = "Microsoft"
fyear = "2023"

message = dedent(
    f"""
    With the tools you've been provided, write an annual report based on {company}'s {fyear} 10-k report, format it into a pdf.
    Pay attention to the followings:
    - Explicitly explain your working plan before you kick off.
    - Use tools one by one for clarity, especially when asking for instructions. 
    - All your file operations should be done in "{work_dir}". 
    - Display any image in the chat once generated.
    - All the paragraphs should combine between 400 and 450 words, don't generate the pdf until this is explicitly fulfilled.

    Check in with the user after each MAJOR milestone to ask for feedback and approval before continuing. Don't check in after API calls or agent actions, only after substantial progress is made. When presenting feedback, be concise and show the new content.
    """
)

assistant.chat(message, use_cache=True, max_turns=50,
               summary_method="last_msg")
