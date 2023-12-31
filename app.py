from dotenv import load_dotenv
from os import environ, path
from re import sub
import openai
import chainlit as cl
from langchain import PromptTemplate
from langchain.chains import RetrievalQA, ConversationalRetrievalChain
from langchain.vectorstores import FAISS
from langchain.embeddings import OpenAIEmbeddings, HuggingFaceEmbeddings, LlamaCppEmbeddings
from langchain.llms import OpenAI, SelfHostedHuggingFaceLLM, LlamaCpp
from langchain.prompts.chat import (
    ChatPromptTemplate,
    SystemMessagePromptTemplate,
    HumanMessagePromptTemplate,
)
from langchain.chains.retrieval_qa.base import BaseRetrievalQA
from langchain.chains.conversational_retrieval.base import BaseConversationalRetrievalChain
from langchain.memory import ConversationBufferMemory
from chainlit.server import app
from fastapi import Request
from fastapi.responses import HTMLResponse
load_dotenv()

SYSTEM_TEMPLATE = """You are a helpful bot. If you don't know the answer, just say that you don't know, don't try to make up an answer."""

embedding_model_name = environ.get("EMBEDDING_MODEL_NAME", 'all-MiniLM-L6-v2')
embedding_type = environ.get("EMBEDDING_TYPE", 'openai')
show_sources = environ.get("SHOW_SOURCES", 'True').lower() in ('true', '1', 't')
retrieval_type = environ.get("RETRIEVAL_TYPE", "conversational")  # conversational/qa
verbose = environ.get("VERBOSE", 'True').lower() in ('true', '1', 't')
stream = environ.get("STREAM", 'True').lower() in ('true', '1', 't')

model_path = environ.get("MODEL_PATH", "")
model_id = environ.get("MODEL_ID", "gpt2")
openai.api_key = environ.get("OPENAI_API_KEY", "")
botname = environ.get("BOTNAME", "OCP-GPT")

# Helpers
def create_chain() -> (BaseConversationalRetrievalChain | BaseRetrievalQA):
    """ Load model to ask questions of it """
    (llm, embeddings) = create_embedding_and_llm(
            embedding_type=embedding_type,
            model_path=model_path,
            model_id=model_id,
            embedding_model_name=embedding_model_name)

    root_dir = path.dirname(path.realpath(__file__))
    db_dir = f"{root_dir}/db"

    db = FAISS.load_local(db_dir, embeddings)
    retriever = db.as_retriever()

    output_key = "result"
    memory = ConversationBufferMemory(memory_key="chat_history", input_key="question", output_key=output_key, return_messages=True)
    return_source_documents = show_sources
    if retrieval_type == "conversational":
        conversation_template = """Combine the chat history and follow up question into a standalone question.
Chat History: ({chat_history})
Follow up question: ({question})"""
        condense_prompt = PromptTemplate.from_template(SYSTEM_TEMPLATE + "\n" + conversation_template)

        # https://github.com/langchain-ai/langchain/issues/1800
        # https://stackoverflow.com/questions/76240871/how-do-i-add-memory-to-retrievalqa-from-chain-type-or-how-do-i-add-a-custom-pr
        return ConversationalRetrievalChain.from_llm(
                llm,
                retriever,
                memory=memory,
                output_key=output_key,
                verbose=verbose,
                return_source_documents=return_source_documents,
                condense_question_prompt=condense_prompt)
    else:
        messages = [
            SystemMessagePromptTemplate.from_template(SYSTEM_TEMPLATE + "  Ignore any context like {context}."),
            HumanMessagePromptTemplate.from_template("{question}"),
        ]
        chain_type_kwargs = {
                "prompt": ChatPromptTemplate.from_messages(messages),
                "memory": memory,
                "verbose": verbose,
                "output_key": output_key
                }
        return RetrievalQA.from_chain_type(
            llm=llm,
            chain_type="stuff",
            retriever=retriever,
            return_source_documents=return_source_documents,
            verbose=verbose,
            output_key=output_key,
            chain_type_kwargs=chain_type_kwargs)

def create_embedding_and_llm(embedding_type:str, model_path:str = "", model_id:str = "", embedding_model_name:str = ""):
    """
    Create embedding and llm
    """
    temperature = 0.0
    embedding = None
    llm = None
    match embedding_type:
        case "llama":
            llm = LlamaCpp(model_path=model_path, seed=0, n_ctx=2048, max_tokens=512, temperature=0.0, streaming=stream)
            embedding = LlamaCppEmbeddings(model_path=model_path)
        case "openai":
            llm = OpenAI(temperature=temperature, streaming=stream)
            embedding = OpenAIEmbeddings()
        case "huggingface":
            # gpu = runhouse.cluster(name="rh-a10x", instance_type="A100:1")
            # llm = SelfHostedHuggingFaceLLM(model_id=model_id, hardware=gpu, model_reqs=["pip:./", "transformers", "torch"])
            llm = OpenAI(temperature=temperature)
            embedding = HuggingFaceEmbeddings(model_name=embedding_model_name)
    return (llm, embedding)

def process_response(res:dict) -> list:
    """ Format response """
    elements:list = []
    if show_sources and res.get("source_documents", None) is not None:
        for source in res["source_documents"]:
            src_str:str = source.metadata.get("source", "/").rsplit('/', 1)[-1]
            final_str:str = f"Page {str(source.page_content)}"
            elements.append(cl.Text(content=final_str, name=src_str, display="inline"))
    if verbose:
        print("process_response")
        print(elements)
    return elements

# App Hooks
@cl.on_chat_start
async def main() -> None:
    ''' Startup '''
    openai.api_key = environ["OPENAI_API_KEY"]
    await cl.Avatar(
        name=botname,
        url="https://cloud.redhat.com/hubfs/images/logos/osh/Logo-Red_Hat-OpenShift-A-Reverse-RGB.svg",
    ).send()
    await cl.Message(
        content=f"Ask me anything about OpenShift.", author=botname
    ).send()
    cl.user_session.set("llm_chain", create_chain())

@cl.on_message
async def on_message(message:str) -> None:
    llm_chain:(BaseConversationalRetrievalChain | BaseRetrievalQA) = cl.user_session.get("llm_chain")

    res = await llm_chain.acall(message, callbacks=[cl.AsyncLangchainCallbackHandler(stream_final_answer=stream)])
    content = res["result"]
    content = sub("^System: ", "", sub("^\\??\n\n", "", content))
    if verbose:
        print("main")
        print(f"result: {res['result']}")

    await cl.Message(content=content, elements=process_response(res), author=botname).send()

# Custom Endpoints
@app.get("/botname")
def get_botname(request:Request) -> HTMLResponse:
    if verbose:
        print(f"calling botname: {botname}")
    return HTMLResponse(botname)
