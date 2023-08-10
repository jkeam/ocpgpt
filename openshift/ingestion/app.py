from parliament import Context, event
from os import environ
from json import loads
from dotenv import load_dotenv
from typing import Any
load_dotenv()

@event
def main(context: Context) -> dict[str, Any]:
    sender_email_address  = environ['SENDER_EMAIL_ADDRESS']
    sender_email_password = environ['SENDER_EMAIL_PASSWORD']

    data = loads(context.cloud_event.data)
    receiver  = data['recipient']
    body      = "Hello there from the PyMailer Function as a Service, running in OpenShift using OpenShift Serverless Functions."

    return { "message": receiver }
