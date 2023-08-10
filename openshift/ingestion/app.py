from flask import Flask, request, make_response, Response
import uuid

# from typing import Any
# from os import environ
# from json import loads
from dotenv import load_dotenv
load_dotenv()

app = Flask(__name__)

@app.route('/', methods=['GET'])
def health() -> Response:
    return make_response({
        "message": "ok",
        "status": "healhty"
    })

@app.route('/', methods=['POST'])
def main() -> Response:
    data = request.data
    app.logger.debug(data)

    response = make_response({
        "message": "hi"
    })
    response.headers["Ce-Id"] = str(uuid.uuid4())
    response.headers["Ce-specversion"] = "0.3"
    response.headers["Ce-Source"] = "keam/io/ai/ocpgpt"
    response.headers["Ce-Type"] = "keam.io.ai.ocpgpt"
    return response

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=8080)
