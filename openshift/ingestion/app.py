from flask import Flask, request, make_response
import uuid

# from os import environ
# from json import loads
from dotenv import load_dotenv
# from typing import Any
load_dotenv()

app = Flask(__name__)

@app.route('/', methods=['GET'])
def health():
    return make_response({
        "message": "ok",
        "status": "healhty"
    })

@app.route('/', methods=['POST'])
def main():
    app.logger.warning(request.data)
    # Respond with another event (optional)
    response = make_response({
        "message": "hi"
    })
    response.headers["Ce-Id"] = str(uuid.uuid4())
    response.headers["Ce-specversion"] = "0.3"
    response.headers["Ce-Source"] = "knative/eventing/samples/hello-world"
    response.headers["Ce-Type"] = "dev.knative.samples.hifromknative"
    return response

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=8080)
