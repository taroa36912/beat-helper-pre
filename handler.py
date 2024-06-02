import json, os, requests, time
from nacl.signing import VerifyKey
from dotenv import load_dotenv
from concurrent.futures import ThreadPoolExecutor

DISCORD_ENDPOINT = "https://discord.com/api/v8"
CHAT_UPDATE_INTERVAL_SEC = 1

load_dotenv()

DISCORD_TOKEN = os.getenv('DISCORD_TOKEN')
APPLICATION_ID = os.getenv('APPLICATION_ID')
APPLICATION_PUBLIC_KEY = os.getenv('APPLICATION_PUBLIC_KEY')
COMMAND_GUILD_ID = os.getenv('COMMAND_GUILD_ID')
OPENAI_API_KEY = os.getenv('OPENAI_API_KEY')

verify_key = VerifyKey(bytes.fromhex(APPLICATION_PUBLIC_KEY))

executor = ThreadPoolExecutor(max_workers=5)

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
    
    aiAnswer = getAiAnswer(text + "\n256トークン以内で返答してください.")
    
    url2 = f"{DISCORD_ENDPOINT}/webhooks/{APPLICATION_ID}/{interactionToken}/messages/@original"
    body2 = {
        "content" : f"あなたの入力 : {text}\nGPTの回答 : {aiAnswer}"
    }
    requests.patch(url2, headers=headers, json=body2)


def getAiAnswer(text):
    url = "https://api.openai.com/v1/chat/completions"
    if not OPENAI_API_KEY:
        return f"API KEYが取得できませんでした. 入力 : {text}"

    # POSTデータの作成
    request_data = {
        "model": "gpt-4o",
        "messages": [
            {"role": "user", "content": text}
        ],
        "max_tokens": 256
    }

    # ヘッダーの設定
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {OPENAI_API_KEY}",
    }
    
    response = requests.post(url, headers=headers, data=json.dumps(request_data))
    response.raise_for_status()  # HTTPエラーチェック
    
    response_data = response.json()
    return parse_response(response_data)


def parse_response(response_data):
    if "choices" not in response_data or len(response_data["choices"]) == 0:
        return "値を正しく取得できませんでした"

    return response_data["choices"][0]["message"]["content"]