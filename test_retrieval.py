import asyncio
import os
from azure.identity.aio import AzureDeveloperCliCredential
from openai import AsyncAzureOpenAI
from src.api.search_index_manager import SearchIndexManager
from src.api.util import ChatRequest


async def main():
    credential = AzureDeveloperCliCredential()

    embed = AsyncAzureOpenAI(
        azure_endpoint=os.environ["AZURE_OPENAI_ENDPOINT"],
        api_version="preview",
        azure_ad_token_provider=lambda: credential.get_token(
            "https://cognitiveservices.azure.com/.default"
        ).token,
    )

    manager = SearchIndexManager(
        endpoint=os.environ["AZURE_AI_SEARCH_ENDPOINT"],
        credential=credential,
        index_name=os.environ["AZURE_AI_SEARCH_INDEX_NAME"],
        dimensions=1536,
        model=os.environ["AZURE_AI_EMBED_DEPLOYMENT_NAME"],
        embeddings_client=embed,
    )

    await manager.ensure_index_created(
        vector_index_dimensions=1536
    )

    question = ChatRequest(
        messages=[
            {
                "role": "user",
                "content": "What part of Aleppo has lower access to MRI and CT services?"
            }
        ]
    )

    result = await manager.search(question)

    print("\n===== RETRIEVED CONTEXT =====\n")
    print(result)

    await manager.close()
    await embed.close()
    await credential.close()


asyncio.run(main())
