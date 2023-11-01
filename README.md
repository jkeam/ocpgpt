# OCP GPT

OpenShift GPT Solution

## Prerequisite

1. Python 3.11 or later

## Setup

1. Clone this repo

2. Create virtual environment

    ```shell
    python -m venv venv
    source ./venv/bin/activate
    ```

3. Install dependencies

    ```shell
    pip install -r requirements.txt
    ```

4. Create an `.env` file that looks like

    ```dotenv
    OPEN_API_KEY=YOUR_KEY_HERE
    ```

### Ingesting

1. Move all documents that you want to index into the `docs` directory

2. Run the ingester

   ```shell
   python ./ingest.py
   ```

### Running the App

1. Start the app using chainlit

    ```shell
    chainlit run app.py
    ```

## References

1. [Inspired by this](https://github.com/redhat-et/foundation-models-for-documentation/blob/master/notebooks/langchain-openai.ipynb)
2. [Chroma DB](https://python.langchain.com/en/latest/modules/indexes/vectorstores/examples/chroma.html)
