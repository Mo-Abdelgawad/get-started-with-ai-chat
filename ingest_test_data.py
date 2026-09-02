import asyncio
import os
from azure.identity.aio import AzureDeveloperCliCredential
from openai import AsyncAzureOpenAI

from src.api.search_index_manager import SearchIndexManager


async def main():
    credential = AzureDeveloperCliCredential()

    endpoint = os.environ["AZURE_OPENAI_ENDPOINT"]

    search_endpoint = os.environ["AZURE_AI_SEARCH_ENDPOINT"]
    index_name = os.environ.get("AZURE_AI_SEARCH_INDEX_NAME", "index_sample")
    embedding_model = os.environ.get(
        "AZURE_AI_EMBED_DEPLOYMENT_NAME",
        "text-embedding-3-small",
    )
    dimensions = int(os.environ.get("AZURE_AI_EMBED_DIMENSIONS", "1536"))

    embed = AsyncAzureOpenAI(
        azure_endpoint=endpoint,
        api_version="preview",
        azure_ad_token_provider=lambda: credential.get_token(
            "https://cognitiveservices.azure.com/.default"
        ).token,
    )

    manager = SearchIndexManager(
        endpoint=search_endpoint,
        credential=credential,
        index_name=index_name,
        dimensions=dimensions,
        model=embedding_model,
        embeddings_client=embed,
    )

    print("Building embeddings...")
    await manager.build_embeddings_file(
        input_directory="data",
        output_file="data/embeddings.csv",
        sentences_per_embedding=4,
    )

    print("Creating/checking Azure AI Search index...")
    await manager.ensure_index_created(
        vector_index_dimensions=1536
    )

    print("Uploading documents...")
    await manager.upload_documents("data/embeddings.csv")

    print("SUCCESS: Test data uploaded to Azure AI Search.")

    await manager.close()
    await embed.close()
    await credential.close()


asyncio.run(main())
