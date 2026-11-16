from __future__ import annotations

import json
import subprocess
import sys

from credentials.bulk_text_parser import credentials_text_to_json


SAMPLE = """
Server Credentials
URL     :  ssh -p 65002 u636798823@82.25.107.214
Password    :  secret-one

Server Configuration
URL     :  ssh root@2.24.85.179
Password    :  secret-two

Google Gemini API Key
GOOGLE_API_KEY=gemini-secret
REPLICATE_API_TOKEN=replicate-secret
MONGO_URI=mongodb+srv://user:pass@example.mongodb.net/app
USE_MONGO=true

Pinecone Vector Database
PINECONE_API_KEY=pinecone-secret
PINECONE_INDEX_NAME =atelis-products
PINECONE_NAMESPACE =default

AWS Credentials
AWS Console:[Sign-in Link](https://198200019618.signin.aws.amazon.com/console)
Username: ITInfonity
Password: aws-secret
"""


def test_bulk_text_parser_converts_mixed_credentials_to_import_json() -> None:
    data = credentials_text_to_json(SAMPLE, project_name="Atelis")
    project = data["projects"][0]
    items = project["items"]
    by_title = {item["title"]: item for item in items}

    assert project["name"] == "Atelis"
    assert by_title["Server Credentials"]["kind"] == "server_login"
    assert by_title["Server Credentials"]["username"] == "u636798823"
    assert by_title["Server Credentials"]["url_host"] == "82.25.107.214:65002"
    assert by_title["Server Configuration"]["url_host"] == "2.24.85.179:22"
    assert by_title["GOOGLE_API_KEY"]["kind"] == "api_key"
    assert by_title["MONGO_URI"]["kind"] == "database"
    assert by_title["PINECONE_INDEX_NAME"]["environment_key"] == "PINECONE_INDEX_NAME"
    assert by_title["AWS Credentials"]["kind"] == "cloud_provider"
    assert by_title["AWS Credentials"]["url_host"] == "https://198200019618.signin.aws.amazon.com/console"
    assert by_title["AWS Credentials"]["secret_value"] == "aws-secret"


def test_bulk_text_parser_handles_provider_specific_database_labels() -> None:
    data = credentials_text_to_json(
        """
        Database Connection
        RDS URL : deload-db-2026.cn2u4wq2eoa3.us-east-2.rds.amazonaws.com
        RDS Password : database-secret
        """,
        project_name="Deload",
    )
    item = data["projects"][0]["items"][0]

    assert item["title"] == "Database Connection"
    assert item["kind"] == "database"
    assert item["url_host"] == "deload-db-2026.cn2u4wq2eoa3.us-east-2.rds.amazonaws.com"
    assert item["secret_value"] == "database-secret"


def test_bulk_text_parser_strips_google_docs_bullet_markers() -> None:
    data = credentials_text_to_json(
        """
        AWS Credentials
        • AWS Console: https://123456789012.signin.aws.amazon.com/console
        • Username: ITInfonity
        • Password: aws-secret
        """,
        project_name="Deload",
    )
    item = data["projects"][0]["items"][0]

    assert item["kind"] == "cloud_provider"
    assert item["url_host"] == "https://123456789012.signin.aws.amazon.com/console"
    assert item["username"] == "ITInfonity"
    assert item["secret_value"] == "aws-secret"


def test_bulk_text_parser_cli_reads_stdin_and_outputs_json() -> None:
    completed = subprocess.run(
        [sys.executable, "scripts/credentials_text_to_json.py", "--project", "Demo"],
        input="API_KEY=secret\n",
        text=True,
        capture_output=True,
        check=True,
    )

    data = json.loads(completed.stdout)

    assert data["projects"][0]["name"] == "Demo"
    assert data["projects"][0]["items"][0]["title"] == "API_KEY"
    assert data["projects"][0]["items"][0]["secret_value"] == "secret"
