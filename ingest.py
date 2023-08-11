#!/usr/bin/env python3
import os
import glob
import boto3
from typing import List
from dotenv import load_dotenv
from multiprocessing import Pool
from tqdm import tqdm

from langchain.document_loaders import (
    CSVLoader,
    EverNoteLoader,
    PyMuPDFLoader,
    TextLoader,
    UnstructuredEmailLoader,
    UnstructuredEPubLoader,
    UnstructuredHTMLLoader,
    UnstructuredMarkdownLoader,
    UnstructuredODTLoader,
    UnstructuredPowerPointLoader,
    UnstructuredWordDocumentLoader,
)

from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain.vectorstores import Chroma, FAISS
from langchain.embeddings import HuggingFaceEmbeddings, OpenAIEmbeddings, LlamaCppEmbeddings
from langchain.docstore.document import Document
from chromadb.config import Settings
import nltk
import openai


load_dotenv()


# Load environment variables
persist_directory = os.environ.get("PERSIST_DIRECTORY", 'db')
source_directory = os.environ.get("DOCUMENT_SOURCE_DIR", 'docs')
embedding_model_name = os.environ.get("EMBEDDING_MODEL_NAME", 'all-MiniLM-L6-v2')
embedding_type = os.environ.get("EMBEDDING_TYPE", 'openai')
model_path = os.environ.get("MODEL_PATH", "")
database_type = os.environ.get("DATABASE_TYPE", "faiss")
openai.api_key = os.environ.get("OPENAI_API_KEY", "")
verbose = os.environ.get("VERBOSE", 'True').lower() in ('true', '1', 't')
# aws
aws_enable = os.environ.get("AWS_ENABLE", 'True').lower() in ('true', '1', 't')
aws_access_key = os.environ.get("AWS_ACCESS_KEY", "")
aws_secret_key = os.environ.get("AWS_SECRET_KEY", "")
aws_region = os.environ.get("AWS_REGION", "us-east-1")
aws_bucket_name = os.environ.get("AWS_BUCKET_NAME", "")

# chunk_size = 500
# chunk_overlap = 50
chunk_size = 1000
chunk_overlap = 200

nltk.download("averaged_perceptron_tagger")

# Custom document loaders
class MyElmLoader(UnstructuredEmailLoader):
    """Wrapper to fallback to text/plain when default does not work"""

    def load(self) -> List[Document]:
        """Wrapper adding fallback for elm without html"""
        try:
            try:
                doc = UnstructuredEmailLoader.load(self)
            except ValueError as e:
                if 'text/html content not found in email' in str(e):
                    # Try plain text
                    self.unstructured_kwargs["content_source"]="text/plain"
                    doc = UnstructuredEmailLoader.load(self)
                else:
                    raise
        except Exception as e:
            # Add file_path to exception message
            raise type(e)(f"{self.file_path}: {e}") from e
        return doc


# Map file extensions to document loaders and their arguments
LOADER_MAPPING = {
    ".csv": (CSVLoader, {}),
    # ".docx": (Docx2txtLoader, {}),
    ".doc": (UnstructuredWordDocumentLoader, {}),
    ".docx": (UnstructuredWordDocumentLoader, {}),
    ".enex": (EverNoteLoader, {}),
    ".eml": (MyElmLoader, {}),
    ".epub": (UnstructuredEPubLoader, {}),
    ".html": (UnstructuredHTMLLoader, {}),
    ".md": (UnstructuredMarkdownLoader, {}),
    ".odt": (UnstructuredODTLoader, {}),
    ".pdf": (PyMuPDFLoader, {}),
    ".ppt": (UnstructuredPowerPointLoader, {}),
    ".pptx": (UnstructuredPowerPointLoader, {}),
    ".txt": (TextLoader, {"encoding": "utf8"}),
    ".adoc": (TextLoader, {"encoding": "utf8"}),
}


def load_single_document(file_path: str) -> List[Document]:
    """
    Loads a single document
    """
    ext:str = "." + file_path.rsplit(".", 1)[-1]
    if ext not in LOADER_MAPPING:
        raise ValueError(f"Unsupported file extension '{ext}'")

    docs:List[Document] = []
    loader_class, loader_args = LOADER_MAPPING[ext]
    loader = loader_class(file_path, **loader_args)
    try:
        docs = loader.load()
    except Exception as err:
        print(f"ERROR: {file_path}", err)
    return docs


def load_documents(source_dir: str, ignored_files: List[str] = []) -> List[Document]:
    """
    Loads all documents from the source documents directory, ignoring specified files
    """
    all_files = []
    for ext in LOADER_MAPPING:
        all_files.extend(
            glob.glob(os.path.join(source_dir, f"**/*{ext}"), recursive=True)
        )
    filtered_files = [file_path for file_path in all_files if file_path not in ignored_files]

    with Pool(processes=os.cpu_count()) as pool:
        results = []
        with tqdm(total=len(filtered_files), desc='Loading new documents', ncols=80) as pbar:
            for i, docs in enumerate(pool.imap_unordered(load_single_document, filtered_files)):
                results.extend(docs)
                pbar.update()
    return results


def process_documents(ignored_files: List[str] = []) -> List[Document]:
    """
    Load documents and split in chunks
    """
    print(f"Loading documents from {source_directory}")
    documents = load_documents(source_directory, ignored_files)
    if not documents:
        print("No new documents to load")
        exit(0)
    print(f"Loaded {len(documents)} new documents from {source_directory}")
    text_splitter = RecursiveCharacterTextSplitter(chunk_size=chunk_size, chunk_overlap=chunk_overlap)
    texts = text_splitter.split_documents(documents)
    print(f"Split into {len(texts)} chunks of text (max. {chunk_size} tokens each)")
    return texts

def does_vectorstore_exist(persist_directory: str) -> bool:
    """
    Checks if vectorstore exists
    """
    if os.path.exists(os.path.join(persist_directory, 'index')):
        if os.path.exists(os.path.join(persist_directory, 'chroma-collections.parquet')) and os.path.exists(os.path.join(persist_directory, 'chroma-embeddings.parquet')):
            list_index_files = glob.glob(os.path.join(persist_directory, 'index/*.bin'))
            list_index_files += glob.glob(os.path.join(persist_directory, 'index/*.pkl'))
            # At least 3 documents are needed in a working vectorstore
            if len(list_index_files) > 3:
                return True
    return False


def create_embedding(embedding_type:str, model_path:str = "", embedding_model_name:str = "") -> (LlamaCppEmbeddings|OpenAIEmbeddings|HuggingFaceEmbeddings):
    """
    Create embedding
    """
    match embedding_type:
        case "llama":
            return LlamaCppEmbeddings(model_path=model_path)
        case "openai":
            embedding = OpenAIEmbeddings()
            embedding.max_retries = 20
            embedding.request_timeout = 30
            embedding.show_progress_bar = True
            return embedding
        case "huggingface":
            return HuggingFaceEmbeddings(model_name=embedding_model_name)
        case _:
            return LlamaCppEmbeddings(model_path=model_path)

def fetch_aws_documents(verbose:bool, source_dir:str, bucket_name:str, access_key:str, secret_key:str) -> None:
    if verbose:
        print("fetching aws documents")
    session = boto3.Session(
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key
    )
    s3 = session.resource('s3')

    # select bucket
    source_bucket = s3.Bucket(bucket_name)

    for s3_object in source_bucket.objects.all():
        path, filename = os.path.split(s3_object.key)
        if verbose:
            print(f"downloading {path}/{filename}")
        source_bucket.download_file(s3_object.key, os.path.join(source_dir, filename))


def main() -> None:
    embedding = create_embedding(embedding_type=embedding_type, model_path=model_path, embedding_model_name=embedding_model_name)
    if aws_enable:
        fetch_aws_documents(verbose, source_directory, aws_bucket_name, aws_access_key, aws_secret_key)
    match database_type:
        case "chroma":
            # prefer huggingface
            chroma_settings = Settings(
                    chroma_db_impl='duckdb+parquet',
                    persist_directory=persist_directory,
                    anonymized_telemetry=False
            )
            if does_vectorstore_exist(persist_directory):
                # Update and store locally vectorstore
                print(f"Appending to existing vectorstore at {persist_directory}")
                db = Chroma(persist_directory=persist_directory, embedding_function=embedding, client_settings=chroma_settings)
                collection = db.get()
                texts = process_documents([metadata['source'] for metadata in collection['metadatas']])
                print(f"Creating embedding. May take some minutes...")
                db.add_documents(texts)
            else:
                # Create and store locally vectorstore
                print("Creating new vectorstore")
                texts = process_documents()
                print(f"Creating embedding. May take some minutes...")
                db = Chroma.from_documents(texts, embedding, persist_directory=persist_directory, client_settings=chroma_settings)
            db.persist()
        case _:
            print("Creating new vectorstore")
            texts = process_documents()
            print(f"Creating embedding. May take some minutes...")
            db = FAISS.from_documents(texts, embedding)
            db.save_local(persist_directory)
    print(f"Ingestion complete!")


if __name__ == "__main__":
    main()
