import base64
import datetime
import typing
from concurrent.futures import ThreadPoolExecutor
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import pytz
import requests
from decouple import config
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

from google_creds import SCOPES

TIMEZONE = "Asia/Kolkata"

SERPER_API_KEY = config("SERPER_API_KEY")


def get_unread_emails(n: int = 5):
    service = gmail_service()
    results = (
        service.users()
        .messages()
        .list(userId="me", labelIds=["UNREAD"], maxResults=n)
        .execute()
        .get("messages", [])
    )
    with ThreadPoolExecutor(max_workers=n) as pool:
        emails = pool.map(
            lambda result: gmail_service()
            .users()
            .messages()
            .get(userId="me", id=result["id"], format="full")
            .execute(),
            results,
        )
    return [
        {
            "id": email["id"],
            "snippet": email["snippet"],
            "time": datetime.datetime.fromtimestamp(
                int(email["internalDate"]) / 1000
            ).isoformat(),
        }
        for email in emails
    ]


def send_email(to_email: str, subject: str, body: str):
    service = gmail_service()
    message = (
        service.users()
        .messages()
        .send(userId="me", body=create_email_message(to_email, subject, body))
        .execute()
    )
    # print("Message Id: %s" % message["id"])
    return message


def create_email_message(to_email: str, subject: str, body: str):
    message = MIMEMultipart()
    message["to"] = to_email
    message["subject"] = subject

    msg = MIMEText(body)
    message.attach(msg)

    encoded_message = base64.urlsafe_b64encode(message.as_bytes()).decode()
    return {"raw": encoded_message}


def google_search(query, location="in"):
    response = requests.post(
        "https://google.serper.dev/search",
        headers={"X-API-KEY": SERPER_API_KEY},
        json={"q": query, "gl": location, "num": 5},
    )
    assert response.ok, response.text
    data = response.json()
    return {
        "results": [
            {
                "title": entry.get("title", ""),
                "link": entry.get("link", ""),
                "snippet": entry.get("snippet", ""),
            }
            for entry in data.get("organic", [])
        ],
        "peopleAlsoAsk": data.get("peopleAlsoAsk", []),
    }


def gcal_delete_event(event_id: str):
    service = get_calendar_service()
    return service.events().delete(calendarId="primary", eventId=event_id).execute()


def gcal_update_event(
    event_id: str,
    summary: str,
    start_time: str,
    end_time: str,
    location: str = None,
    attendee_emails: typing.List[str] = None,
):
    service = get_calendar_service()
    event = service.events().get(calendarId="primary", eventId=event_id).execute()
    event["summary"] = summary
    event["location"] = location
    event["start"]["dateTime"] = start_time
    event["end"]["dateTime"] = end_time
    if attendee_emails:
        event["attendees"] = [{"email": email} for email in attendee_emails]
    return (
        service.events()
        .update(calendarId="primary", eventId=event_id, body=event)
        .execute()
    )


def gcal_get_upcoming_events(start_time: str, end_time: str):
    service = get_calendar_service()
    start_time = (
        datetime.datetime.fromisoformat(start_time)
        .astimezone(pytz.timezone("UTC"))
        .isoformat()
    )
    end_time = (
        datetime.datetime.fromisoformat(end_time)
        .astimezone(pytz.timezone("UTC"))
        .isoformat()
    )
    events_result = (
        service.events()
        .list(
            calendarId="primary",
            timeMin=start_time,
            timeMax=end_time,
            maxResults=10,
            singleEvents=True,
            orderBy="startTime",
        )
        .execute()
    )
    events = events_result.get("items", [])
    return [
        {
            "event_id": event["id"],
            "time": event["start"].get("dateTime", event["start"].get("date")),
            "summary": event.get("summary", ""),
            "location": event.get("location", ""),
            "attendees": event.get("attendees", []),
        }
        for i, event in enumerate(events)
    ]
    # return "\n".join(
    #     f'[{i + 1}] Event ID: {event["id"]} | Time: {event["start"].get("dateTime", event["start"].get("date"))} | Summary: {event["summary"]}'
    #     for i, event in enumerate(events)
    # )


def gcal_add_event(
    summary: str,
    start_time: str,
    end_time: str,
    location: str = None,
    attendee_emails: typing.List[str] = None,
):
    event = {
        "summary": summary,
        "location": location,
        "start": {
            "dateTime": start_time,
            "timeZone": TIMEZONE,
        },
        "end": {
            "dateTime": end_time,
            "timeZone": TIMEZONE,
        },
        "attendees": [{"email": email} for email in (attendee_emails or [])],
    }
    service = get_calendar_service()
    event = service.events().insert(calendarId="primary", body=event).execute()
    # print("Event created: %s" % (event.get("htmlLink")))
    return event


def gmail_service():
    return build("gmail", "v1", credentials=get_credentials())


def get_calendar_service():
    return build("calendar", "v3", credentials=get_credentials())


_credentials = None


def get_credentials():
    global _credentials
    if _credentials is None:
        _credentials = Credentials.from_authorized_user_file("token.json", SCOPES)
    return _credentials
