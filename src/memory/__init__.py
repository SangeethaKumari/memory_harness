#  -------------------------------------------------------------------------------------------------
#   Copyright (c) 2016-2025.  SupportVectors AI Lab
#   This code is part of the training material and, therefore, part of the intellectual property.
#   It may not be reused or shared without the explicit, written permission of SupportVectors.
#
#   Use is limited to the duration and purpose of the training at SupportVectors.
#
#   Author: SupportVectors AI Training Team
#  -------------------------------------------------------------------------------------------------
from dotenv import load_dotenv
from svlearn.config.configuration import ConfigurationMixin

load_dotenv()

config = ConfigurationMixin().load_config()

# Lab helpers used by docs/notebooks/*.ipynb
from memory.adk_runtime import (
    create_session,
    get_session_state,
    ground_message_to_user,
    make_agent,
    make_runner,
    run_turn,
)
from memory.fact_store import Fact, FactStore
from memory.llm_config import (
    complete,
    litellm_model_id,
    load_lab_env,
    make_model,
    model_summary,
)

__all__ = [
    "Fact",
    "FactStore",
    "complete",
    "config",
    "create_session",
    "get_session_state",
    "ground_message_to_user",
    "litellm_model_id",
    "load_lab_env",
    "make_agent",
    "make_model",
    "make_runner",
    "model_summary",
    "run_turn",
]
