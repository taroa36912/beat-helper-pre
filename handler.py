import json, os, requests, logging, logging
from nacl.signing import VerifyKey
from dotenv import load_dotenv
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta, datetime
from typing import Any
from langchain.chains import ConversationalRetrievalChain
from langchain_openai import ChatOpenAI
from langchain.memory import ConversationBufferMemory
from langchain_community.chat_message_histories import MomentoChatMessageHistory
from langchain_openai import OpenAIEmbeddings
from langchain_pinecone import PineconeVectorStore

load_dotenv()

COMMAND_GUILD_ID = '1222864676191473754'
OPENAI_API_MODEL = 'gpt-4o'
OPENAI_API_TEMPERATURE = '0.5'
MOMENTO_CACHE = 'langchain-book'
MOMENTO_TTL = '1'
PINECONE_INDEX = 'langchain-book'
PINECONE_API_KEY = os.getenv("PINECONE_API_KEY")
PINECONE_ENV = os.getenv("PINECONE_ENV")
DISCORD_ENDPOINT = "https://discord.com/api/v8"
CHAT_UPDATE_INTERVAL_SEC = 1

DISCORD_TOKEN = os.getenv('DISCORD_TOKEN')
APPLICATION_ID = os.getenv('APPLICATION_ID')
APPLICATION_PUBLIC_KEY = os.getenv('APPLICATION_PUBLIC_KEY')
OPENAI_API_KEY = os.getenv('OPENAI_API_KEY')

verify_key = VerifyKey(bytes.fromhex(APPLICATION_PUBLIC_KEY))

executor = ThreadPoolExecutor(max_workers=5)

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

def handle_mention(text):
    history = MomentoChatMessageHistory.from_client_params(
        str(datetime.now().timestamp()),
        MOMENTO_CACHE,
        timedelta(hours=int(MOMENTO_TTL)),
    )
    memory = ConversationBufferMemory(
        chat_memory=history, memory_key="chat_history", return_messages=True
    )

    vectorstore = PineconeVectorStore(
        index_name=PINECONE_INDEX,
        embedding=OpenAIEmbeddings(),
        pinecone_api_key=PINECONE_API_KEY
    )
    
    llm = ChatOpenAI(
        model_name=OPENAI_API_MODEL,
        temperature=OPENAI_API_TEMPERATURE,
        streaming=True,
    )
    condense_question_llm = ChatOpenAI(
        model_name=OPENAI_API_MODEL,
        temperature=OPENAI_API_TEMPERATURE,
    )

    qa_chain = ConversationalRetrievalChain.from_llm(
        llm=llm,
        retriever=vectorstore.as_retriever(),
        memory=memory,
        condense_question_llm=condense_question_llm,
    )

    answer = qa_chain.invoke(text)
    
    return answer['answer']


def registerCommands():
    endpoint = f"{DISCORD_ENDPOINT}/applications/{APPLICATION_ID}/guilds/{COMMAND_GUILD_ID}/commands"
    print(f"registering commands: {endpoint}")

    commands = [
        {
            "name": "ynu",
            "description": "Input what you want to know!",
            "options": [
                {
                    "type": 3, # ApplicationCommandOptionType.String
                    "name": "message",
                    "description": "what do you want to know?",
                    "required": False
                }
            ]
        }
    ]

    headers = {
        "User-Agent": "beat-helper",
        "Content-Type": "application/json",
        "Authorization": f"Bot {DISCORD_TOKEN}"
    }

    for c in commands:
        requests.post(endpoint, headers=headers, json=c).raise_for_status()

def verify(signature: str, timestamp: str, body: str) -> bool:
    try:
        verify_key.verify(f"{timestamp}{body}".encode(), bytes.fromhex(signature))
    except Exception as e:
        print(f"failed to verify request: {e}")
        return False

    return True

def callback(event: dict, context: dict):
    # API Gateway has weird case conversion, so we need to make them lowercase.
    # See https://github.com/aws/aws-sam-cli/issues/1860
    headers: dict = { k.lower(): v for k, v in event['headers'].items() }
    rawBody: str = event['body']

    # validate request
    signature = headers.get('x-signature-ed25519')
    timestamp = headers.get('x-signature-timestamp')
    if not verify(signature, timestamp, rawBody):
        return {
            "cookies": [],
            "isBase64Encoded": False,
            "statusCode": 401,
            "headers": {},
            "body": ""
        }
    
    req: dict = json.loads(rawBody)
    if req['type'] == 1: # InteractionType.Ping
        registerCommands()
        return {
            "type": 1 # InteractionResponseType.Pong
        }
    elif req['type'] == 2: # InteractionType.ApplicationCommand
        # command options list -> dict
        opts = {v['name']: v['value'] for v in req['data']['options']} if 'options' in req['data'] else {}
        interactionId = req['id']
        interactionToken = req['token']

        if not 'message' in opts:
            return {
            "type": 4, # InteractionResponseType.ChannelMessageWithSource
            "data": {
                "content": "メッセージが入力されていません."
            }
        }
        else:
            text = f"{opts['message']}"
            sendMessage(interactionId, interactionToken, text)


def sendMessage(interactionId, interactionToken, text):
    url = f"{DISCORD_ENDPOINT}/interactions/{interactionId}/{interactionToken}/callback"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bot {DISCORD_TOKEN}"
    }
    body = {
        "type" : 5,
        "data" : {
            "content" : "現在回答を考え中"
        }
    }
    requests.post(url, headers=headers, json=body)
    
    aiAnswer = handle_mention(text)
    
    url2 = f"{DISCORD_ENDPOINT}/webhooks/{APPLICATION_ID}/{interactionToken}/messages/@original"
    body2 = {
        "content" : f"あなたの入力 : {text}\nGPTの回答 : {aiAnswer}"
    }
    requests.patch(url2, headers=headers, json=body2)