import os
import json
import pandas as pd
from datetime import date, timedelta, datetime
from typing import Annotated


# Define custom annotated types
# VerboseType = Annotated[bool, "Whether to print data to console. Default to True."]
SavePathType = Annotated[str, "File path to save data. If None, data is not saved."]


# def process_output(data: pd.DataFrame, tag: str, verbose: VerboseType = True, save_path: SavePathType = None) -> None:
#     if verbose:
#         print(data.to_string())
#     if save_path:
#         data.to_csv(save_path)
#         print(f"{tag} saved to {save_path}")


def save_output(data: pd.DataFrame, tag: str, save_path: SavePathType = None) -> None:
    if save_path:
        data.to_csv(save_path)
        print(f"{tag} saved to {save_path}")


def get_current_date():
    return date.today().strftime("%Y-%m-%d")


def register_keys_from_json(config_file_path: str) -> None:
    """
    Load API keys from a JSON config file into environment variables.
    
    Args:
        config_file_path (str): Path to the JSON config file containing API keys
    """
    try:
        with open(config_file_path, 'r') as f:
            config = json.load(f)
            
        for key, value in config.items():
            os.environ[key] = value
            
        print("API keys loaded successfully into environment variables.")
    except FileNotFoundError:
        print(f"Config file not found at: {config_file_path}")
    except json.JSONDecodeError:
        print(f"Error parsing JSON from config file: {config_file_path}")
    except Exception as e:
        print(f"Unexpected error loading API keys: {str(e)}")


def decorate_all_methods(decorator):
    def class_decorator(cls):
        for attr_name, attr_value in cls.__dict__.items():
            if callable(attr_value):
                setattr(cls, attr_name, decorator(attr_value))
        return cls

    return class_decorator


def get_next_weekday(date):

    if not isinstance(date, datetime):
        date = datetime.strptime(date, "%Y-%m-%d")

    if date.weekday() >= 5:
        days_to_add = 7 - date.weekday()
        next_weekday = date + timedelta(days=days_to_add)
        return next_weekday
    else:
        return date


# def create_inner_assistant(
#         name, system_message, llm_config, max_round=10,
#         code_execution_config=None
#     ):

#     inner_assistant = autogen.AssistantAgent(
#         name=name,
#         system_message=system_message + "Reply TERMINATE when the task is done.",
#         llm_config=llm_config,
#         is_termination_msg=lambda x: x.get("content", "").find("TERMINATE") >= 0,
#     )
#     executor = autogen.UserProxyAgent(
#         name=f"{name}-executor",
#         human_input_mode="NEVER",
#         code_execution_config=code_execution_config,
#         default_auto_reply="",
#         is_termination_msg=lambda x: x.get("content", "").find("TERMINATE") >= 0,
#     )
#     assistant.register_nested_chats(
#         [{"recipient": assistant, "message": reflection_message, "summary_method": "last_msg", "max_turns": 1}],
#         trigger=ConversableAgent
#         )
#     return manager
