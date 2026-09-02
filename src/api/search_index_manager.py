from typing import Optional, Dict, Any, Iterable, List

import glob
import csv
import json
import os

from azure.core.credentials_async import AsyncTokenCredential
from azure.search.documents.aio import SearchClient
from azure.search.documents.indexes.aio import SearchIndexClient
from azure.search.documents.models import VectorizedQuery 
from azure.search.documents.indexes.models import (
    SearchField,
    SearchFieldDataType,  
    SimpleField,
    SearchIndex,
    VectorSearch,
    VectorSearchProfile,
    HnswAlgorithmConfiguration)
from openai import AsyncAzureOpenAI
from azure.core.exceptions import ResourceNotFoundError, HttpResponseError
from .util import ChatRequest


class SearchIndexManager:
    """
    The class for searching of context for user queries.

    :param endpoint: The search endpoint to be used.
    :param credential: The credential to be used for the search.
    :param index_name: The name of an index to get or to create.
    :param dimensions: The number of dimensions in the embedding. Set this parameter only if
                       embedding model accepts dimensions parameter.
    :param model: The embedding model to be used,
                  must be the same as one use to build the file with embeddings.
    :param embeddings_client: The embedding client.
    """

    DEFAULT_METADATA_FIELDS = [
        "sector",
        "region",
        "document_type",
        "source_owner",
        "language",
    ]

    MIN_DIFF_CHARACTERS_IN_LINE = 5
    MIN_LINE_LENGTH = 5
    
    def __init__(
            self,
            endpoint: str,
            credential: AsyncTokenCredential,
            index_name: str,
            dimensions: Optional[int],
            model: str,
            embeddings_client: AsyncAzureOpenAI,
        ) -> None:
        """Constructor."""
        self._dimensions = dimensions
        self._index_name = index_name
        self._embeddings_client = embeddings_client
        self._endpoint = endpoint
        self._credential = credential
        self._index = None
        self._model = model
        self._client = None

    @staticmethod
    def infer_document_metadata(
        source_file: str,
        default_sector: Optional[str] = None,
        default_region: Optional[str] = None,
        default_document_type: Optional[str] = None,
        default_source_owner: Optional[str] = None,
        default_language: Optional[str] = "en",
    ) -> Dict[str, Optional[str]]:
        """Infer a common metadata schema for content from different document types."""
        normalized_name = (source_file or "").lower()
        extension = os.path.splitext(source_file or "")[1].lower().lstrip(".")

        sector = default_sector
        if sector is None:
            sector_map = {
                "healthcare": "healthcare",
                "hospital": "healthcare",
                "clinic": "healthcare",
                "education": "education",
                "school": "education",
                "university": "education",
                "finance": "finance",
                "bank": "finance",
                "insurance": "finance",
                "driving": "driving_licensing",
                "driver": "driving_licensing",
                "license": "driving_licensing",
                "licence": "driving_licensing",
                "permit": "driving_licensing",
            }
            for token, mapped_sector in sector_map.items():
                if token in normalized_name:
                    sector = mapped_sector
                    break

        region = default_region
        if region is None:
            region_map = {
                "aleppo": "Aleppo",
                "damascus": "Damascus",
                "latakia": "Latakia",
                "syria": "Syria",
            }
            for token, mapped_region in region_map.items():
                if token in normalized_name:
                    region = mapped_region
                    break

        document_type = default_document_type or {
            "md": "markdown",
            "pdf": "pdf",
            "docx": "word",
            "doc": "word",
            "xlsx": "excel",
            "xls": "excel",
            "csv": "csv",
            "txt": "text",
            "pptx": "powerpoint",
        }.get(extension, extension or "unknown")

        return {
            "sector": sector,
            "region": region,
            "document_type": document_type,
            "source_owner": default_source_owner or "unknown",
            "language": default_language,
        }

    @staticmethod
    def build_filter_expression(filters: Optional[Dict[str, Any]]) -> Optional[str]:
        """Build an Azure Search filter expression from a simple metadata dictionary."""
        if not filters:
            return None

        clauses = []
        for key, value in filters.items():
            if value in (None, ""):
                continue
            safe_value = str(value).replace("'", "''")
            clauses.append(f"{key} eq '{safe_value}'")
        return " and ".join(clauses) if clauses else None

    @staticmethod
    def format_source_reference(source_file: Optional[str], page_number: Optional[object]) -> str:
        """Format a source label with optional page information."""
        source_name = source_file or "Unknown source"
        if page_number is None or page_number == "" or page_number == "None":
            return source_name

        page_value = str(page_number).strip()
        if page_value:
            return f"{source_name}, page {page_value}"
        return source_name

    def _get_client(self):
        """Get search client if it is absent."""
        if self._client is None:
            self._client = SearchClient(
                endpoint=self._endpoint, index_name=self._index.name, credential=self._credential)
        return self._client

    async def search(self, message: ChatRequest, filters: Optional[Dict[str, Any]] = None) -> str:
        """
        Search the message in the vector store.

        :param message: The customer question.
        :param filters: Optional metadata filters, e.g. {"sector": "healthcare"}.
        :return: The context for the question.
        """
        self._raise_if_no_index()

        response = await self._embeddings_client.embeddings.create(
            input=message.messages[-1].content,
            model=self._model,
        )
        embedded_question = response.data[0].embedding

        vector_query = VectorizedQuery(vector=embedded_question, k_nearest_neighbors=5, fields="embedding")
        search_kwargs = {
            "vector_queries": [vector_query],
            "select": ['token', 'source_file'],
        }
        filter_expression = self.build_filter_expression(filters)
        if filter_expression:
            search_kwargs["filter"] = filter_expression
        response = await self._get_client().search(**search_kwargs)

        results = []
        async for result in response:
            source = self.format_source_reference(
                result.get('source_file'),
                result.get('page_number')
            )
            token = result['token']
            results.append(f"[Source: {source}]\n{token}")

        return "\n------\n".join(results)
    
    async def upload_documents(self, embeddings_file: str) -> None:
        """
        Upload the embeddings file to index search.

        Supports both legacy CSVs with only token/source_file/embedding and newer metadata-aware CSVs.
        :param embeddings_file: The embeddings file to upload.
        """
        self._raise_if_no_index()
        documents = []
        index = 0
        with open(embeddings_file, newline='') as fp:
            reader = csv.DictReader(fp)
            for row in reader:
                document = {
                    'embedId': str(index),
                    'token': row['token'],
                    'source_file': row.get('source_file', 'Unknown source'),
                    'embedding': json.loads(row['embedding'])
                }

                for metadata_field, value in row.items():
                    if metadata_field in {'token', 'source_file', 'embedding'}:
                        continue
                    if value not in (None, ''):
                        document[metadata_field] = value

                documents.append(document)
                index += 1
        await self._get_client().upload_documents(documents)

    async def is_index_empty(self) -> bool:
        """
        Return True if the index is empty.

        :return: True f index is empty.
        """
        if self._index is None:
            raise ValueError(
                "Unable to perform the operation as the index is absent. "
                "To create index please call create_index")
        document_count = await self._get_client().get_document_count()
        return document_count == 0

    def _raise_if_no_index(self) -> None:
        """
        Raise the exception if the index was not created.

        :raises: ValueError
        """
        if self._index is None:
            raise ValueError(
                "Unable to perform the operation as the index is absent. "
                "To create index please call create_index")

    async def delete_index(self):
        """Delete the index from vector store."""
        self._raise_if_no_index()
        async with SearchIndexClient(endpoint=self._endpoint, credential=self._credential) as ix_client:
            await ix_client.delete_index(self._index.name)
        self._index = None

    def _check_dimensions(self, vector_index_dimensions: Optional[int] = None) -> int:
        """
        Check that the dimensions are set correctly.

        :return: the correct vector index dimensions.
        :raises: Value error if both dimensions of embedding model and vector_index_dimensions are not set
                 or both of them set and they do not equal each other.
        """
        if vector_index_dimensions is None:
            if self._dimensions is None:
                raise ValueError(
                    "No embedding dimensions were provided in neither dimensions in the constructor nor in vector_index_dimensions"
                    "Dimensions are needed to build the search index, please provide the vector_index_dimensions.")
            vector_index_dimensions = self._dimensions
        if self._dimensions is not None and vector_index_dimensions != self._dimensions:
            raise ValueError("vector_index_dimensions is different from dimensions provided to constructor.")
        return vector_index_dimensions

    async def ensure_index_created(
        self,
        vector_index_dimensions: Optional[int] = None,
        metadata_fields: Optional[Iterable[str]] = None,
    ) -> None:
        """
        Get the search index. Create the index if it does not exist.

        :param vector_index_dimensions: The number of dimensions in the vector index.
        :param metadata_fields: Optional list of searchable metadata fields for future multi-sector support.
        """
        vector_index_dimensions = self._check_dimensions(vector_index_dimensions)
        if self._index is None:
            self._index = await SearchIndexManager.get_or_create_index(
                self._endpoint,
                self._credential,
                self._index_name,
                vector_index_dimensions,
                metadata_fields=metadata_fields,
            )

    @staticmethod
    async def index_exists(
        endpoint: str,
        credential: AsyncTokenCredential,
        index_name: str) -> bool:
        """
        Check if index exists.

        :param endpoint: The search end point to be used.
        :param credential: The credential to be used for the search.
        :param index_name: The name of an index to get or to create.
        :return: True if index already exists.
        """
        exists = False
        async with SearchIndexClient(endpoint=endpoint, credential=credential) as ix_client:
            try:
                await ix_client.get_index(index_name)
                exists = True
            except ResourceNotFoundError:
                pass
        return exists

    @staticmethod
    async def get_or_create_index(
            endpoint: str,
            credential: AsyncTokenCredential,
            index_name: str,
            dimensions: int,
            metadata_fields: Optional[Iterable[str]] = None,
        ) -> SearchIndex:
        """
        Get or create the search index, recreating it when the stored schema is stale.

        :param endpoint: The search end point to be used.
        :param credential: The credential to be used for the search.
        :param index_name: The name of an index to get or to create.
        :param dimensions: The number of dimensions in the embedding.
        :param metadata_fields: Optional additional metadata fields for future multi-sector indexing.
        :return: the search index object.
        """
        index = None
        async with SearchIndexClient(endpoint=endpoint, credential=credential) as ix_client:
            try:
                index = await ix_client.get_index(index_name)
            except ResourceNotFoundError:
                pass

        if index is not None:
            field_names = {field.name for field in index.fields}
            required_fields = {"embedId", "embedding", "token", "source_file"}
            required_metadata = set(metadata_fields or [])
            metadata_is_filterable = True
            for field_name in required_metadata:
                matching_field = next((field for field in index.fields if field.name == field_name), None)
                if matching_field is None or not getattr(matching_field, "filterable", False):
                    metadata_is_filterable = False
                    break

            if "page_number" in field_names:
                async with SearchIndexClient(endpoint=endpoint, credential=credential) as ix_client:
                    try:
                        await ix_client.delete_index(index_name)
                    except ResourceNotFoundError:
                        pass
                index = None
            elif required_fields.issubset(field_names) and required_metadata.issubset(field_names) and metadata_is_filterable:
                return index
            else:
                async with SearchIndexClient(endpoint=endpoint, credential=credential) as ix_client:
                    try:
                        await ix_client.delete_index(index_name)
                    except ResourceNotFoundError:
                        pass
                index = None

        if index is None:
            return await SearchIndexManager._index_create(
                endpoint=endpoint,
                credential=credential,
                index_name=index_name,
                dimensions=dimensions,
                metadata_fields=list(metadata_fields) if metadata_fields else None,
            )

        return index

    async def create_index(
        self,
        vector_index_dimensions: Optional[int] = None,
        metadata_fields: Optional[Iterable[str]] = None,
    ) -> bool:
        """
        Create index or return false if it already exists.

        :param vector_index_dimensions: The number of dimensions in the vector index.
        :param metadata_fields: Optional metadata fields used for future multi-sector indexing.
        :return: True if index was created, False otherwise.
        """
        vector_index_dimensions = self._check_dimensions(vector_index_dimensions)
        try:
            self._index = await SearchIndexManager._index_create(
                endpoint=self._endpoint,
                credential=self._credential,
                index_name=self._index_name,
                dimensions=vector_index_dimensions,
                metadata_fields=list(metadata_fields) if metadata_fields else None,
            )
            return True
        except HttpResponseError:
            return False

    @staticmethod
    async def _index_create(
        endpoint: str,
        credential: AsyncTokenCredential,
        index_name: str,
        dimensions: int,
        metadata_fields: Optional[Iterable[str]] = None,
    ) -> SearchIndex:
        """Create the index."""
        async with SearchIndexClient(endpoint=endpoint, credential=credential) as ix_client:
            fields = [
                SimpleField(name="embedId", type=SearchFieldDataType.String, key=True),
                SearchField(
                    name="embedding",
                    type=SearchFieldDataType.Collection(SearchFieldDataType.Single),
                    vector_search_dimensions=dimensions,
                    searchable=True,
                    vector_search_profile_name="embedding_config"
                ),
                SimpleField(name="token", type=SearchFieldDataType.String, hidden=False),
                SimpleField(name="source_file", type=SearchFieldDataType.String, hidden=False),
            ]
            for field_name in metadata_fields or []:
                fields.append(SimpleField(
                    name=field_name,
                    type=SearchFieldDataType.String,
                    filterable=True,
                    hidden=False,
                ))
            vector_search = VectorSearch(
                profiles=[VectorSearchProfile(name="embedding_config",
                                              algorithm_configuration_name="embed-algorithms-config")],
                algorithms=[HnswAlgorithmConfiguration(name="embed-algorithms-config")],
            )
            search_index = SearchIndex(name=index_name, fields=fields, vector_search=vector_search)
            new_index = await ix_client.create_index(search_index)
        return new_index
        

    async def build_embeddings_file(
        self,
        input_directory: str,
        output_file: str,
        sentences_per_embedding: int = 4,
        metadata_fields: Optional[Iterable[str]] = None,
    ) -> None:
        """Build embeddings CSV with a scalable, metadata-aware schema.

        This keeps the base ingestion flow generic across PDF/Markdown/Word/Excel files and makes it
        easy to add sector and region metadata without changing the core logic for each document type.
        """
        import nltk
        nltk.download('punkt', quiet=True)
        nltk.download('punkt_tab', quiet=True)

        from nltk.tokenize import sent_tokenize

        chunks = []
        metadata_fields = list(metadata_fields or self.DEFAULT_METADATA_FIELDS)
        globs = sorted(
            glob.glob(input_directory + '/*', recursive=True)
        )

        for fle in globs:
            if not os.path.isfile(fle):
                continue

            source_file = os.path.basename(fle)
            lower_name = source_file.lower()
            if not (lower_name.endswith('.md') or lower_name.endswith('.pdf') or lower_name.endswith('.docx') or lower_name.endswith('.xlsx') or lower_name.endswith('.csv')):
                continue

            sentences = []
            if lower_name.endswith('.md'):
                with open(fle, encoding='utf-8') as f:
                    for line in f:
                        line = line.strip()
                        if (
                            len(line) < SearchIndexManager.MIN_LINE_LENGTH
                            or len(set(line)) < SearchIndexManager.MIN_DIFF_CHARACTERS_IN_LINE
                        ):
                            continue
                        sentences.extend(sent_tokenize(line))
            elif lower_name.endswith('.pdf'):
                try:
                    import fitz
                except ModuleNotFoundError as exc:
                    raise ModuleNotFoundError(
                        "PyMuPDF is required to ingest PDF files. Install it with: pip install pymupdf"
                    ) from exc

                with fitz.open(fle) as pdf_document:
                    for page in pdf_document:
                        page_text = page.get_text("text")
                        if not page_text:
                            continue
                        for line in page_text.splitlines():
                            line = line.strip()
                            if (
                                len(line) < SearchIndexManager.MIN_LINE_LENGTH
                                or len(set(line)) < SearchIndexManager.MIN_DIFF_CHARACTERS_IN_LINE
                            ):
                                continue
                            sentences.extend(sent_tokenize(line))
            else:
                with open(fle, encoding='utf-8', errors='ignore') as f:
                    for line in f:
                        line = line.strip()
                        if (
                            len(line) < SearchIndexManager.MIN_LINE_LENGTH
                            or len(set(line)) < SearchIndexManager.MIN_DIFF_CHARACTERS_IN_LINE
                        ):
                            continue
                        sentences.extend(sent_tokenize(line))

            metadata = self.infer_document_metadata(source_file)
            for i in range(0, len(sentences), sentences_per_embedding):
                token = " ".join(sentences[i:i + sentences_per_embedding])
                if token:
                    chunk = {
                        "token": token,
                        "source_file": source_file,
                    }
                    for field_name in metadata_fields:
                        chunk[field_name] = metadata.get(field_name, "unknown")
                    chunks.append(chunk)

        batch_size = 2000
        fieldnames = ['token', 'source_file', 'embedding'] + metadata_fields

        with open(output_file, 'w', newline='', encoding='utf-8') as fp:
            writer = csv.DictWriter(fp, fieldnames=fieldnames)
            writer.writeheader()

            for i in range(0, len(chunks), batch_size):
                batch = chunks[i:i + batch_size]
                texts = [item["token"] for item in batch]

                embedding_data = (
                    await self._embeddings_client.embed(
                        input=texts,
                        dimensions=self._dimensions,
                        model=self._model
                    )
                )["data"]

                for item, float_data in zip(batch, embedding_data):
                    row = {
                        'token': item["token"],
                        'source_file': item["source_file"],
                        'embedding': json.dumps(float_data['embedding'])
                    }
                    for field_name in metadata_fields:
                        row[field_name] = item.get(field_name, 'unknown')
                    writer.writerow(row)

    async def close(self):
        """Close the closeable resources, associated with SearchIndexManager."""
        if self._client:
            await self._client.close()
