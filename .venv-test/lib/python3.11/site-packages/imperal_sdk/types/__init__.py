"""Imperal SDK shared types."""
from imperal_sdk.types.identity import User, UserContext, Tenant, TenantContext
from imperal_sdk.types.action_result import ActionResult
from imperal_sdk.types.chat_result import ChatResult, FunctionCall
from imperal_sdk.types.models import (
    Document, CompletionResult, LimitsResult, SubscriptionInfo,
    BalanceInfo, FileInfo, HTTPResponse,
)
from imperal_sdk.types.pagination import Page
from imperal_sdk.types.events import Event, WebhookRequest, WebhookResponse
from imperal_sdk.types.health import HealthStatus
from imperal_sdk.types.contributions import Panel, Widget, Command, ContextMenu, Setting, Theme
from imperal_sdk.types.contracts import (
    # Cross-boundary platform payloads (v1.5.10+)
    ActionResultModel, EventModel, FunctionCallModel, ChatResultModel,
    validate_action_result_dict, validate_event_dict,
    validate_function_call_dict, validate_chat_result_dict,
    get_action_result_schema, get_event_schema,
    get_function_call_schema, get_chat_result_schema,
    ACTION_RESULT_SCHEMA, EVENT_SCHEMA,
    FUNCTION_CALL_SCHEMA, CHAT_RESULT_SCHEMA,
)
from imperal_sdk.types.client_contracts import (
    # HTTP client response types (v1.5.13+)
    DocumentModel, CompletionResultModel, LimitsResultModel,
    SubscriptionInfoModel, BalanceInfoModel, FileInfoModel, HTTPResponseModel,
    validate_document_dict, validate_completion_result_dict,
    validate_limits_result_dict, validate_subscription_info_dict,
    validate_balance_info_dict, validate_file_info_dict,
    validate_http_response_dict,
    get_document_schema, get_completion_result_schema,
    get_limits_result_schema, get_subscription_info_schema,
    get_balance_info_schema, get_file_info_schema,
    get_http_response_schema,
    DOCUMENT_SCHEMA, COMPLETION_RESULT_SCHEMA, LIMITS_RESULT_SCHEMA,
    SUBSCRIPTION_INFO_SCHEMA, BALANCE_INFO_SCHEMA, FILE_INFO_SCHEMA,
    HTTP_RESPONSE_SCHEMA,
)

__all__ = [
    "User", "UserContext", "Tenant", "TenantContext",
    "ActionResult", "ChatResult", "FunctionCall", "Page",
    "Document", "CompletionResult", "LimitsResult", "SubscriptionInfo",
    "BalanceInfo", "FileInfo", "HTTPResponse",
    "Event", "WebhookRequest", "WebhookResponse", "HealthStatus",
    "Panel", "Widget", "Command", "ContextMenu", "Setting", "Theme",
    # Cross-boundary platform payloads (v1.5.10+)
    "ActionResultModel", "EventModel", "FunctionCallModel", "ChatResultModel",
    "validate_action_result_dict", "validate_event_dict",
    "validate_function_call_dict", "validate_chat_result_dict",
    "get_action_result_schema", "get_event_schema",
    "get_function_call_schema", "get_chat_result_schema",
    "ACTION_RESULT_SCHEMA", "EVENT_SCHEMA",
    "FUNCTION_CALL_SCHEMA", "CHAT_RESULT_SCHEMA",
    # HTTP client response types (v1.5.13+)
    "DocumentModel", "CompletionResultModel", "LimitsResultModel",
    "SubscriptionInfoModel", "BalanceInfoModel", "FileInfoModel",
    "HTTPResponseModel",
    "validate_document_dict", "validate_completion_result_dict",
    "validate_limits_result_dict", "validate_subscription_info_dict",
    "validate_balance_info_dict", "validate_file_info_dict",
    "validate_http_response_dict",
    "get_document_schema", "get_completion_result_schema",
    "get_limits_result_schema", "get_subscription_info_schema",
    "get_balance_info_schema", "get_file_info_schema",
    "get_http_response_schema",
    "DOCUMENT_SCHEMA", "COMPLETION_RESULT_SCHEMA", "LIMITS_RESULT_SCHEMA",
    "SUBSCRIPTION_INFO_SCHEMA", "BALANCE_INFO_SCHEMA", "FILE_INFO_SCHEMA",
    "HTTP_RESPONSE_SCHEMA",
]
