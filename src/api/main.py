# Copyright (c) Microsoft. All rights reserved.
# Licensed under the MIT license.
# See LICENSE file in the project root for full license information.
import contextlib
import logging
import os
from typing import Union

import fastapi
from azure.ai.projects.aio import AIProjectClient
from azure.identity import AzureDeveloperCliCredential, ManagedIdentityCredential
from dotenv import load_dotenv
from fastapi.staticfiles import StaticFiles
from openai import AsyncAzureOpenAI

from .search_index_manager import SearchIndexManager
from .util import get_logger

logger = None
enable_trace = False


EMBEDDING_DIMENSIONS_BY_MODEL = {
    "text-embedding-3-small": 1536,
    "text-embedding-3-large": 3072,
    "text-embedding-ada-002": 1536,
}


def resolve_embedding_dimensions(model_name: str, configured_dimensions: str | None) -> int:
    """Return the configured dimensions unless the caller explicitly overrides a known model default."""
    if configured_dimensions is None or configured_dimensions == "":
        return EMBEDDING_DIMENSIONS_BY_MODEL.get(model_name, 1536)
    return int(configured_dimensions)


def build_openai_client(azure_openai_endpoint: str, credential):
    """Build the Azure OpenAI client using the Azure endpoint form required by the SDK."""
    normalized_endpoint = azure_openai_endpoint.rstrip("/")
    return AsyncAzureOpenAI(
        api_version=os.getenv("AZURE_OPENAI_API_VERSION", "2024-10-21"),
        azure_endpoint=normalized_endpoint,
        azure_ad_token_provider=lambda: credential.get_token("https://cognitiveservices.azure.com/.default").token,
    )


@contextlib.asynccontextmanager
async def lifespan(app: fastapi.FastAPI):
    azure_credential: Union[AzureDeveloperCliCredential, ManagedIdentityCredential]
    if not os.getenv("RUNNING_IN_PRODUCTION"):
        if tenant_id := os.getenv("AZURE_TENANT_ID"):
            logger.info("Using AzureDeveloperCliCredential with tenant_id %s", tenant_id)
            azure_credential = AzureDeveloperCliCredential(tenant_id=tenant_id)
        else:
            logger.info("Using AzureDeveloperCliCredential")
            azure_credential = AzureDeveloperCliCredential()
    else:
        # User-assigned identity was created and set in api.bicep
        user_identity_client_id = os.getenv("AZURE_CLIENT_ID")
        logger.info("Using ManagedIdentityCredential with client_id %s", user_identity_client_id)
        azure_credential = ManagedIdentityCredential(client_id=user_identity_client_id)

    endpoint = os.environ["AZURE_EXISTING_AIPROJECT_ENDPOINT"]
    project = AIProjectClient(
        credential=azure_credential,
        endpoint=endpoint,
    )

    if enable_trace:
        application_insights_connection_string = ""
        try:
            application_insights_connection_string = await project.telemetry.get_application_insights_connection_string()
        except Exception as e:
            e_string = str(e)
            logger.error("Failed to get Application Insights connection string, error: %s", e_string)
        if not application_insights_connection_string:
            logger.error("Application Insights was not enabled for this project.")
            logger.error("Enable it via the 'Tracing' tab in your AI Foundry project page.")
            exit()
        else:
            from azure.monitor.opentelemetry import configure_azure_monitor
            configure_azure_monitor(connection_string=application_insights_connection_string)


    azure_openai_endpoint = os.getenv("AZURE_OPENAI_ENDPOINT")
    if not azure_openai_endpoint:
        project_endpoint = os.environ.get("AZURE_EXISTING_AIPROJECT_ENDPOINT", "")
        if project_endpoint:
            azure_openai_endpoint = project_endpoint.split("/api/projects/")[0].replace(".services.ai.azure.com", ".openai.azure.com")
        else:
            raise RuntimeError("AZURE_OPENAI_ENDPOINT is not configured and could not be derived from AZURE_EXISTING_AIPROJECT_ENDPOINT.")

    openai_client = build_openai_client(azure_openai_endpoint, azure_credential)

    chat = openai_client
    embed = openai_client

    endpoint = os.environ.get('AZURE_AI_SEARCH_ENDPOINT')
    search_index_manager = None
    embed_model_name = os.getenv('AZURE_AI_EMBED_DEPLOYMENT_NAME')
    configured_embed_dimensions = os.getenv('AZURE_AI_EMBED_DIMENSIONS')
    embed_dimensions = resolve_embedding_dimensions(embed_model_name or "text-embedding-3-small", configured_embed_dimensions)

    if endpoint and os.getenv('AZURE_AI_SEARCH_INDEX_NAME') and embed_model_name:
        search_index_manager = SearchIndexManager(
            endpoint = endpoint,
            credential = azure_credential,
            index_name = os.getenv('AZURE_AI_SEARCH_INDEX_NAME'),
            dimensions = embed_dimensions,
            model = embed_model_name,
            embeddings_client=embed
        )
        # Create index and upload the documents only if index does not exist.
        logger.info(f"Creating index {os.getenv('AZURE_AI_SEARCH_INDEX_NAME')}.")
        await search_index_manager.ensure_index_created(
            vector_index_dimensions=embed_dimensions)
    else:
        logger.info("The RAG search will not be used.")

    app.state.chat = chat
    app.state.search_index_manager = search_index_manager
    app.state.chat_model = os.environ["AZURE_AI_CHAT_DEPLOYMENT_NAME"]
    yield

    await project.close()
    await chat.close()
    if search_index_manager is not None:
        await search_index_manager.close()


def create_app():
    if not os.getenv("RUNNING_IN_PRODUCTION"):
        load_dotenv(override=True)

    global logger
    logger = get_logger(
        name="azureaiapp",
        log_level=logging.INFO,
        log_file_name = os.getenv("APP_LOG_FILE"),
        log_to_console=True
    )

    enable_trace_string = os.getenv("ENABLE_AZURE_MONITOR_TRACING", "")
    global enable_trace
    enable_trace = False
    if enable_trace_string == "":
        enable_trace = False
    else:
        enable_trace = str(enable_trace_string).lower() == "true"
    if enable_trace:
        logger.info("Tracing is enabled.")
        try:
            from azure.monitor.opentelemetry import configure_azure_monitor
        except ModuleNotFoundError:
            logger.error("Required libraries for tracing not installed.")
            logger.error("Please make sure azure-monitor-opentelemetry is installed.")
            exit()
    else:
        logger.info("Tracing is not enabled")

    app = fastapi.FastAPI(lifespan=lifespan)
    app.mount("/static", StaticFiles(directory="api/static"), name="static")

    from . import routes  # noqa

    app.include_router(routes.router)

    return app
