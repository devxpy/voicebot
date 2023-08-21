import inspect
import json
import os
from functools import wraps
from time import sleep
import datetime

from decouple import config
from fastapi import FastAPI, WebSocketDisconnect
from google.cloud import translate_v2 as translate
from starlette.background import BackgroundTasks
from starlette.concurrency import run_in_threadpool
from starlette.datastructures import FormData
from starlette.requests import Request
from starlette.responses import Response
from twilio.rest import Client

from functions import (
    gcal_get_upcoming_events,
    gcal_add_event,
    gcal_delete_event,
    gcal_update_event,
    google_search,
    send_email,
    get_unread_emails,
)

app = FastAPI()


ACCOUNT_SID = config("ACCOUNT_SID")
AUTH_TOKEN = config("AUTH_TOKEN")

TIMEOUT = 5
ENABLE_MISSED_CALL = True
LOCATION = "Bengaluru, India"

LANG_CODE = "en-US"
VOICE_NAME = "Google.en-US-Wavenet-F"

# LANG_CODE = "en-IN"
# VOICE_NAME = "Google.en-IN-Wavenet-A"

# LANG_CODE = "hi-IN"
# VOICE_NAME = "Google.hi-IN-Neural2-B"

# LANG_CODE = "te-IN"
# VOICE_NAME = "Google.te-IN-Standard-B"

service_account_key_path = "serviceAccountKey.json"
os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = service_account_key_path
# save json file from env var if available
try:
    _json = os.environ["GOOGLE_APPLICATION_CREDENTIALS_JSON"]
except KeyError:
    pass
else:
    with open(service_account_key_path, "w") as f:
        f.write(_json)

intro_text = "How can I help you?"
fallaback_text = "I didn't hear anything. Goodbye!"
if not LANG_CODE.startswith("en"):
    translate_client = translate.Client()
    intro_text, fallaback_text = [
        item["translatedText"]
        for item in translate_client.translate(
            [intro_text, fallaback_text], target_language=LANG_CODE
        )
    ]


FUNCTIONS = [
    gcal_add_event,
    gcal_get_upcoming_events,
    gcal_delete_event,
    gcal_update_event,
    google_search,
    send_email,
    get_unread_emails,
]


def get_context():
    now = datetime.datetime.now()
    today = now.replace(hour=0, minute=0, second=0)
    return """
You are a helpful personal assistant. Your name is Matrix.

You run in a loop of Thought, Action, << PAUSE >>, Observation.
At the end of the loop you output an Answer
Use Thought to describe your thoughts about the question you have been asked.
Use Action to run one of the actions available to you - then return << PAUSE >>.
Observation will be the result of running those actions.

Contacts: 
- Myself <dev@gooey.ai>
- Ravi <ravi.theja@glance.com>
- Sean <sean@gooey.ai>
- Rohit <hitanand4@gmail.com>

The Current Date and Time is: %(curtime)s
The Current Location is: %(location)s

Your available actions are:

%(functions)s

Examples:

What does my calendar look like tomorrow?
[assistant] Thought: I should check the upcoming events on the calendar between %(tomorrow_start)s to %(tomorrow_end)s 
Action: gcal_get_upcoming_events(start_time='%(tomorrow_start)s', end_time='%(tomorrow_end)s')
<< PAUSE >>
Observation: [{'time': '%(tomorrow)s', 'summary': 'fishing'}, {'time': '%(not_tomorrow)s', 'summary': 'football'}]
Answer: 
You have 1 event tomorrow - fishing

Send an email about my resignation to Myself
Thought: I should send an email to Myself about my resignation 
Action: send_email(to_email='dev@gooey.ai', subject='Resgination', body=''I am writing to inform you of my resignation from my position as a software engineer at Glance. My last day of employment will be August 31, 2023.')
<< PAUSE >>
Observation: {'id': '18a10f37c6918d1f', 'threadId': '18a10f37c6918d1f', 'labelIds': ['UNREAD', 'SENT', 'INBOX']}
Answer: 
The email has been sent to yourself.

Who are the current world cup champions?
Thought: I should search the web for the world cup champions in 2023
Action: google_search(query='world cup champions 2023')
<< PAUSE >>
Observation: {'results': [{'title': \"FIFA Men's World Cup History - Past World Cup Winners, Hosts, Most Goals and more | FOX Sports\", 'link': 'https://www.foxsports.com/soccer/2022-fifa-world-cup/history', 'snippet': \"See our comprehensive FIFA Men's World Cup history guide for everything you need about the tournament. FIFA Men's World Cup results and which countries have ...\"}, {'title': 'FIFA World Cup - Wikipedia', 'link': 'https://en.wikipedia.org/wiki/FIFA_World_Cup', 'snippet': 'The reigning champions are Argentina, who won their third title at the 2022 tournament. FIFA World Cup. Organising body, FIFA. Founded, 1930; 93 years ago ...'}, {'title': 'List of FIFA World Cup finals - Wikipedia', 'link': 'https://en.wikipedia.org/wiki/List_of_FIFA_World_Cup_finals', 'snippet': 'Current champion Argentina has three titles, Uruguay and France have two each, while England and Spain have one each. Czechoslovakia, Hungary, Sweden, the ...'}, {'title': 'FIFA World Cup winners list: Know the champions - Olympics.com', 'link': 'https://olympics.com/en/news/fifa-world-cup-winners-list-champions-record', 'snippet': 'FIFA World Cup winners list ; 1998, France, Brazil ; 2002, Brazil, Germany ; 2006, Italy, France ; 2010, Spain, The Netherlands.'}], 'peopleAlsoAsk': []}"}
Answer:
The current world cup champions are Argentina. 
    """.strip() % dict(
        location=LOCATION,
        functions="\n\n".join(
            [f"{func.__name__}{inspect.signature(func)}" for func in FUNCTIONS]
        ),
        curtime=now.isoformat(),
        tomorrow=(now + datetime.timedelta(days=1)).isoformat(),
        tomorrow_start=(today + datetime.timedelta(days=1)).isoformat(),
        tomorrow_end=(today + datetime.timedelta(days=2)).isoformat(),
        not_tomorrow=(now + datetime.timedelta(days=8)).isoformat(),
    )


EXAMPLES = []


@app.get("/twilio/voice/")
@app.post("/twilio/voice/")
async def twilio_voice_webhook(request: Request, background_tasks: BackgroundTasks):
    # print(request.headers)
    form_data = await request.form()
    print(">> twilio_voice_webhook:", form_data)

    if ENABLE_MISSED_CALL:
        twiml = """
        <?xml version="1.0" encoding="UTF-8"?>
        <Response>
            <Reject/>
        </Response>
        """
        if not form_data.get("StirVerstat"):
            background_tasks.add_task(send_call, request, form_data)
    else:
        twiml = f"""
        <?xml version="1.0" encoding="UTF-8"?>
        {gather_input_twiml(request)}
        """
    return Response(twiml.strip(), media_type="text/xml")


def send_call(request: Request, form_data: FormData):
    sleep(2)
    client = Client(ACCOUNT_SID, AUTH_TOKEN)
    from_ = form_data.get("To")
    to = form_data.get("Caller")
    twiml = gather_input_twiml(request)
    call = client.calls.create(
        twiml=twiml.strip(),
        to=to,
        from_=from_,
    )
    print(">> call:", call.sid)


@app.post("/twilio/onaudio")
@app.post("/twilio/onaudio/")
async def onaudio(request: Request):
    # print(request.headers)
    form_data = await request.form()
    print(">> onaudio:", form_data)
    prompt = form_data.get("SpeechResult") or ""
    prompt = prompt.strip()
    print(">> prompt:", prompt)

    # lang_code = translate_client.detect_language(prompt)["language"]
    if not LANG_CODE.startswith("en"):
        prompt = await run_translate(prompt, target_language="en")

    if not prompt:
        response = f"""
        <?xml version="1.0" encoding="UTF-8"?>
        <Response>
            <Say voice="{VOICE_NAME}" language="{LANG_CODE}">{fallaback_text}</Say>
            <Hangup/>
        </Response>
        """
    else:
        prediction = await run_in_threadpool(_palm_react, prompt)

        if not LANG_CODE.startswith("en"):
            prediction = await run_translate(prediction, target_language=LANG_CODE)
        print(">> prediction:", prediction)

        response = f"""
        <?xml version="1.0" encoding="UTF-8"?>
        {gather_input_twiml(request, prediction)}
        """

    return Response(response.strip(), media_type="text/xml")


async def run_translate(prompt, *, target_language):
    return await run_in_threadpool(
        lambda: translate.Client().translate(
            prompt,
            target_language=target_language,
        )["translatedText"],
    )


def gather_input_twiml(request, text=intro_text):
    return f"""
    <Response>
        <Gather input="speech" speechModel="phone_call" enhanced="true" language="{LANG_CODE}" timeout="{TIMEOUT}" action="http://{request.headers["host"]}/twilio/onaudio">
            <Say voice="{VOICE_NAME}" language="{LANG_CODE}">{text}</Say>
        </Gather>
        <Say voice="{VOICE_NAME}" language="{LANG_CODE}">{fallaback_text}</Say>
    </Response>
    """


def handle_ws_disconnect(fn):
    @wraps(fn)
    async def wrapper(*args, **kwargs):
        try:
            return await fn(*args, **kwargs)
        except WebSocketDisconnect:
            print(">> websocket disconnected")

    return wrapper


def _palm_react(prompt):
    history = get_msgs()
    response = _palm_chat(prompt, history)
    # print(">> raw_response:", repr(response))
    code = response.split("Action: ")[-1].split("<< PAUSE >>")[0].strip()
    code = repr(code).strip("'").strip('"')
    print(">> run code:", code)
    try:
        observation = eval(code)
    except (SyntaxError, NameError) as e:
        if code:
            print(repr(e))
        history += [
            {"author": "user", "content": prompt},
            {"author": "assistant", "content": response},
        ]
    else:
        print("<< ret:", observation)
        history += [
            {"author": "user", "content": prompt},
            {
                "author": "assistant",
                "content": response.split("<< PAUSE >>")[0].strip()
                + "\n<< PAUSE >>\n"
                + f"Observation: {observation}",
            },
        ]
        next_prompt = "Answer:"
        # print(">> next_prompt:", history, repr(next_prompt))
        response = _palm_chat(next_prompt, history)
        history += [
            {"author": "user", "content": next_prompt},
            {"author": "assistant", "content": response},
        ]
    save_msgs(history)
    # print(">> final:", repr(response))
    # print(history)
    return response.split("Answer:")[-1].strip()


def _palm_chat(prompt, history=None, model_id="chat-bison"):
    session, project = get_google_auth_session()
    history = history or []
    r = session.post(
        f"https://us-central1-aiplatform.googleapis.com/v1/projects/{project}/locations/us-central1/publishers/google/models/{model_id}:predict",
        json={
            "instances": [
                {
                    "context": get_context(),
                    "examples": EXAMPLES,
                    "messages": history
                    + [
                        {"author": "user", "content": prompt},
                    ],
                },
            ],
            "parameters": {
                "maxOutputTokens": 256,
                # "topK": topK,
                # "topP": topP,
                "temperature": 0.2,
            },
        },
    )
    assert r.ok, r.text
    return "".join(
        candidate["content"]
        for pred in r.json()["predictions"]
        for candidate in pred["candidates"]
    )


_session = None


def get_google_auth_session():
    global _session

    if _session is None:
        import google.auth
        from google.auth.transport.requests import AuthorizedSession

        creds, project = google.auth.default(
            scopes=["https://www.googleapis.com/auth/cloud-platform"]
        )
        # takes care of refreshing the token and adding it to request headers
        _session = AuthorizedSession(credentials=creds), project

    return _session


def save_msgs(msgs):
    with open("msgs.json", "w") as f:
        json.dump(msgs, f)


def get_msgs():
    try:
        with open("msgs.json") as f:
            return json.load(f)
    except FileNotFoundError:
        return []


if __name__ == "__main__":
    from functions import *

    print(get_context())

    while True:
        prompt = input(">> ")
        response = _palm_react(prompt)
        print(response)

# What's on my cal tomorrow
# What's on my cal on 24th?
# add an event for tomorrow - "fishing"
# What's on my cal on 26th after 8pm?
# Show me directions to the event on 26th
